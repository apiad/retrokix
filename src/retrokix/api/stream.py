"""/stream — live framebuffer over WebSocket + a self-contained HTML viewer.

Two routes:

  GET  /stream             — HTML viewer with the retrokix-stylish GBA
                             bezel. `?mode=viewer` (default) just
                             watches; `?mode=controller` adds an
                             on-screen D-pad + A/B + L/R + Start/Select
                             that drives the emulator via the WS below.
  WS   /stream/ws          — bidirectional.
                             Server → client: binary JPEG frames at
                             the requested fps. Each WS message is
                             one JPEG blob.
                             Client → server: JSON text messages
                             `{"type": "buttons", "buttons": [...]}`
                             with the currently-held button names —
                             same wire as POST /buttons. Replaces the
                             runtime's held set on every message; the
                             SDL keyboard + gamepad + couch all
                             continue to combine via set-union.

Query params on /stream and /stream/ws:
  mode     — viewer | controller (default viewer)
  fps      — target frame rate (1..60, default 30)
  format   — raw | jpeg (default raw)
  quality  — JPEG quality, only used when format=jpeg (10..95, default 92)

Wire formats:
  format=raw  — RGBA8888 bytes, row-major, 240*160*4 = 153,600 bytes
                per frame. Lossless, pixel-exact. ~4.6 MB/s at 30 fps —
                fine on localhost/LAN, real ceiling on remote internet.
  format=jpeg — JPEG-compressed bytes, ~5–20 KB/frame. The browser
                decodes via createImageBitmap. Bandwidth-friendly but
                introduces compression artifacts on pixel art.
"""

from __future__ import annotations

import asyncio
import json
import queue as _stdlib_queue
from io import BytesIO

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from PIL import Image

from retrokix.api.qos import QosState
from retrokix.input import button_from_str


_MIN_FPS, _MAX_FPS, _DEFAULT_FPS = 1, 60, 30
_MIN_Q, _MAX_Q, _DEFAULT_Q = 10, 95, 92
_DEFAULT_Q_FLOOR = 30
_VALID_FORMATS = ("raw", "jpeg")
_DEFAULT_FORMAT = "raw"


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/stream", response_class=HTMLResponse)
    def viewer() -> HTMLResponse:
        return HTMLResponse(_VIEWER_HTML)

    @router.websocket("/stream/audio/ws")
    async def audio_ws(websocket: WebSocket) -> None:
        """Stream raw PCM audio from the AudioBus to the browser.

        Format: signed 16-bit little-endian, 2 channels interleaved,
        32_768 Hz. Each WebSocket message is one libretro audio chunk
        (size varies by core but is on the order of milliseconds).

        Browsers use AudioWorklet for low-latency playback. See the
        worklet inlined in /stream.
        """
        await websocket.accept()
        bus = websocket.app.state.audio_bus
        q = bus.subscribe()
        websocket.app.state.ws_clients += 1
        try:
            while True:
                try:
                    chunk = await asyncio.to_thread(q.get, True, 1.0)
                except _stdlib_queue.Empty:
                    # No audio this window — keep waiting. Disconnects
                    # are detected the moment we try to send_bytes.
                    continue
                if not chunk:
                    continue
                await websocket.send_bytes(chunk)
        except (WebSocketDisconnect, RuntimeError):
            return
        finally:
            bus.unsubscribe(q)
            websocket.app.state.ws_clients = max(0, websocket.app.state.ws_clients - 1)

    @router.websocket("/stream/ws")
    async def stream_ws(
        websocket: WebSocket,
        fps: int = _DEFAULT_FPS,
        quality: int = _DEFAULT_Q,
        format: str = _DEFAULT_FORMAT,
        quality_floor: int = _DEFAULT_Q_FLOOR,
    ) -> None:
        await websocket.accept()
        websocket.app.state.ws_clients += 1
        rt = websocket.app.state.runtime
        fps = max(_MIN_FPS, min(_MAX_FPS, fps))
        quality = max(_MIN_Q, min(_MAX_Q, quality))
        quality_floor = max(_MIN_Q, min(_MAX_Q, quality_floor))
        fmt = format.lower() if isinstance(format, str) else _DEFAULT_FORMAT
        if fmt not in _VALID_FORMATS:
            fmt = _DEFAULT_FORMAT
        interval = 1.0 / fps
        loop = asyncio.get_event_loop()

        qos = QosState(
            initial_quality=quality,
            quality_floor=quality_floor,
            quality_ceiling=quality,
        )
        websocket.app.state.stream_qos = qos

        async def _receive_loop() -> None:
            """Parse text messages from the client.

            Two message types today:
              {"type":"buttons", "buttons":[...]}     — replace held set
              {"type":"fast_forward", "on": true}     — turbo on/off

            Bad payloads / unknown types / out-of-range values are
            dropped silently. Easier to debug client-side than to
            wire an error channel back."""
            app = websocket.app
            while True:
                msg = await websocket.receive_text()
                try:
                    parsed = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                t = parsed.get("type")
                if t == "buttons":
                    names = parsed.get("buttons", [])
                    if not isinstance(names, list):
                        continue
                    try:
                        buttons = {button_from_str(b) for b in names}
                    except ValueError:
                        continue
                    rt.set_buttons(buttons)
                elif t == "fast_forward":
                    app.state.fast_forward = bool(parsed.get("on", False))

        recv_task = asyncio.create_task(_receive_loop())
        send_task: "asyncio.Task | None" = None
        try:
            # First message: an info handshake so the browser can size
            # its canvas before frames arrive. Console-agnostic — works
            # for GBA 240x160, NES 256x240, anything libretro hands us.
            av = rt.system_av_info()
            base_w = av["base_width"] or rt.width or 240
            base_h = av["base_height"] or rt.height or 160
            aspect = av["aspect_ratio"] or (base_w / max(1, base_h))
            console_slug = getattr(rt, "console", None)
            await websocket.send_text(json.dumps({
                "type": "info",
                "width": int(base_w),
                "height": int(base_h),
                "aspect": float(aspect),
                "fps": float(av["fps"] or 60.0),
                "sample_rate": float(av["sample_rate"] or 0),
                "console": console_slug,
            }))

            # QoS — drop old frames + adaptive JPEG quality.
            # We hold ONE in-flight send_bytes task at a time. On each
            # tick, if the previous send is still running, we skip the
            # frame entirely (don't sample, don't encode). When the
            # send completes we sample the LATEST framebuffer — never
            # backlogged stale frames.
            #
            # The wrapped coroutine below records its own start/end
            # times inside the task. That matters for the EWMA: a
            # task that finished in 1 ms but whose `done()` we only
            # observed on the next 33 ms tick still reports a 1 ms
            # send_dur, so we don't ratchet quality down for nothing.

            async def _send_timed(payload: bytes) -> float:
                t_send_start = loop.time()
                await websocket.send_bytes(payload)
                return loop.time() - t_send_start

            # RGBA scratch buffer; reallocated if the framebuffer ever
            # resizes (rare but legal — some cores switch resolution
            # mid-game, e.g. SNES hi-res sprites).
            rgba_buf: "np.ndarray | None" = None
            while True:
                t0 = loop.time()

                if send_task is not None and send_task.done():
                    exc = send_task.exception()
                    if exc is not None:
                        raise exc
                    qos.record_send(send_task.result(), interval)
                    send_task = None

                if send_task is None:
                    fb = rt.framebuffer()
                    if fmt == "raw":
                        h, w = fb.shape[0], fb.shape[1]
                        if rgba_buf is None or rgba_buf.shape[:2] != (h, w):
                            rgba_buf = np.empty((h, w, 4), dtype=np.uint8)
                            rgba_buf[..., 3] = 0xFF
                        rgba_buf[..., :3] = fb
                        payload: bytes = rgba_buf.tobytes()
                    else:
                        buf = BytesIO()
                        Image.fromarray(fb).save(
                            buf, format="JPEG", quality=qos.quality,
                        )
                        payload = buf.getvalue()
                    send_task = asyncio.create_task(_send_timed(payload))
                else:
                    # Previous send still in flight — skip this frame.
                    qos.record_drop()

                elapsed = loop.time() - t0
                await asyncio.sleep(max(0.0, interval - elapsed))
        except WebSocketDisconnect:
            return
        except RuntimeError:
            # send_bytes after the peer closed.
            return
        finally:
            recv_task.cancel()
            try:
                await recv_task
            except (asyncio.CancelledError, WebSocketDisconnect):
                pass
            if send_task is not None and not send_task.done():
                send_task.cancel()
                try:
                    await send_task
                except (asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                    pass
            websocket.app.state.ws_clients = max(0, websocket.app.state.ws_clients - 1)

    return router


_VIEWER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>retrokix — stream</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Press+Start+2P&display=swap">
<style>
  :root {
    --bg: #0b0a14;
    --bg-1: #11101f;
    --bg-2: #1a1830;
    --border: #2a2849;
    --border-soft: #1f1d38;
    --text: #e9e9f4;
    --text-dim: #a4a4c8;
    --text-soft: #6e6c92;
    --accent: #a78bfa;
    --accent-deep: #7c3aed;
    --accent-hot: #f0abfc;
    --emerald: #34d399;
    --red: #fb7185;
    --bezel-light: #4c2882;
    --bezel-dark: #1f0f3d;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    background: radial-gradient(ellipse 80% 50% at 50% 0%,
                  rgba(124,58,237,0.15), transparent 60%),
                var(--bg);
    color: var(--text);
    font-family: "JetBrains Mono", Menlo, Consolas, monospace;
    min-height: 100vh;
    overscroll-behavior: none;
    touch-action: none;
    -webkit-user-select: none;
    user-select: none;
  }
  body {
    display: grid;
    grid-template-rows: auto 1fr auto;
  }
  header {
    padding: 0.85rem 1.25rem;
    border-bottom: 1px solid var(--border-soft);
    display: flex;
    align-items: center;
    gap: 1rem;
    background: rgba(11,10,20,0.7);
    backdrop-filter: blur(10px);
  }
  header h1 {
    margin: 0;
    font-size: 0.96rem;
    font-weight: 600;
    letter-spacing: 0.04em;
  }
  header h1 .dot { color: var(--accent); }
  header .hud {
    margin-left: auto;
    display: flex;
    gap: 1.4rem;
    font-size: 0.74rem;
    color: var(--text-dim);
  }
  header .hud span b { color: var(--text); font-weight: 600; }
  header .mode-badge {
    font-size: 0.7rem;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--accent);
    border: 1px solid rgba(167,139,250,0.35);
    background: rgba(167,139,250,0.08);
    border-radius: 999px;
    padding: 0.25rem 0.65rem;
  }
  .audio-toggle,
  .header-btn {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text-dim);
    border-radius: 999px;
    padding: 0.18rem 0.55rem;
    font-size: 0.86rem;
    cursor: pointer;
    transition: color 0.1s ease, border-color 0.1s ease, background 0.1s ease;
  }
  .header-btn:hover {
    color: var(--text);
    border-color: var(--accent);
    background: rgba(167,139,250,0.06);
  }
  .audio-toggle.is-on {
    color: var(--emerald);
    border-color: rgba(52,211,153,0.45);
  }
  .header-btn.is-open {
    color: var(--accent);
    border-color: rgba(167,139,250,0.5);
    background: rgba(167,139,250,0.10);
  }

  /* ============================================================
   * Overlay panels — saves + cheats. Slide down from the header.
   * Backdrop dims the page; clicking it closes.
   * ============================================================ */
  .overlay {
    position: fixed;
    inset: 0;
    background: rgba(11,10,20,0.55);
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    z-index: 50;
    display: none;
  }
  .overlay.is-open { display: block; }

  .panel {
    position: fixed;
    top: 56px;
    right: 1.25rem;
    width: min(420px, calc(100vw - 2.5rem));
    max-height: calc(100vh - 84px);
    background: var(--bg-1);
    border: 1px solid var(--border);
    border-radius: 14px;
    box-shadow: 0 30px 80px rgba(0,0,0,0.5);
    display: none;
    flex-direction: column;
    z-index: 51;
  }
  .panel.is-open { display: flex; }
  .panel__header {
    padding: 0.85rem 1.05rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 0.7rem;
  }
  .panel__title {
    margin: 0;
    font-size: 0.95rem;
    color: var(--text);
    font-weight: 600;
  }
  .panel__action {
    margin-left: auto;
    background: linear-gradient(135deg, #7c3aed 0%, #a78bfa 100%);
    color: #fff !important;
    border: 0;
    border-radius: 999px;
    padding: 0.32rem 0.85rem;
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    transition: filter 0.1s ease;
  }
  .panel__action:hover { filter: brightness(1.1); }
  .panel__close {
    background: transparent;
    border: 0;
    color: var(--text-soft);
    cursor: pointer;
    font-size: 1rem;
    line-height: 1;
    padding: 0.2rem 0.4rem;
    border-radius: 6px;
  }
  .panel__close:hover { color: var(--text); background: rgba(255,255,255,0.04); }

  .panel__body {
    overflow-y: auto;
    padding: 0.4rem 0.4rem 0.6rem;
  }
  .panel__empty {
    padding: 1.25rem;
    color: var(--text-soft);
    font-size: 0.86rem;
    text-align: center;
  }
  .panel__group-label {
    padding: 0.55rem 0.7rem 0.3rem;
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-soft);
  }

  .save-item, .cheat-item {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 0.7rem;
    width: 100%;
    padding: 0.55rem 0.7rem;
    background: transparent;
    border: 0;
    color: var(--text-dim);
    cursor: pointer;
    text-align: left;
    border-radius: 8px;
    transition: background 0.1s ease, color 0.1s ease;
    font: inherit;
    font-size: 0.84rem;
  }
  .save-item:hover, .cheat-item:hover {
    background: rgba(167,139,250,0.08);
    color: var(--text);
  }
  .save-item__kind {
    width: 1.4em;
    text-align: center;
  }
  .save-item__name {
    font-family: var(--gx-mono, "JetBrains Mono", monospace);
    color: var(--text);
  }
  .save-item__when {
    color: var(--text-soft);
    font-size: 0.76rem;
  }
  .cheat-item__icon {
    width: 1em;
    color: var(--text-soft);
  }
  .cheat-item__icon.is-active {
    color: var(--emerald);
  }
  .cheat-item__name {
    color: var(--text);
  }
  .cheat-item__code {
    font-family: var(--gx-mono, "JetBrains Mono", monospace);
    color: var(--text-soft);
    font-size: 0.72rem;
  }
  .cheat-search {
    width: 100%;
    background: var(--bg-2);
    border: 1px solid var(--border-soft);
    border-radius: 8px;
    color: var(--text);
    padding: 0.45rem 0.7rem;
    font: inherit;
    font-size: 0.85rem;
    margin-bottom: 0.4rem;
  }
  .cheat-search:focus {
    outline: 0;
    border-color: rgba(167,139,250,0.45);
  }

  .toast {
    position: fixed;
    bottom: 1.4rem;
    left: 50%;
    transform: translateX(-50%) translateY(8px);
    background: var(--bg-2);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 0.55rem 1rem;
    border-radius: 999px;
    font-size: 0.84rem;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease, transform 0.2s ease;
    z-index: 60;
  }
  .toast.is-visible {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }
  body[data-mode="controller"] header .mode-badge {
    color: var(--emerald);
    border-color: rgba(52,211,153,0.35);
    background: rgba(52,211,153,0.08);
  }
  #status-dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    margin-right: 0.4rem;
    background: var(--text-soft);
    box-shadow: 0 0 8px currentColor;
  }
  #status-dot.live { background: var(--emerald); }
  #status-dot.err  { background: var(--red); }
  main {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1.5rem 1rem;
  }
  footer {
    padding: 0.7rem 1.25rem;
    border-top: 1px solid var(--border-soft);
    color: var(--text-soft);
    font-size: 0.72rem;
    text-align: center;
  }
  footer code {
    color: var(--accent);
    background: rgba(167,139,250,0.08);
    border: 1px solid rgba(167,139,250,0.18);
    padding: 0.08em 0.36em;
    border-radius: 4px;
  }
  footer a { color: var(--text-dim); text-decoration: none; border-bottom: 1px dotted currentColor; }
  footer a:hover { color: var(--accent); }

  /* ============================================================
   * The GBA console — responsive dock layout.
   *
   * Portrait (default):
   *   shoulders L/R poke out the top edge
   *   screen
   *   GAME BOY ADVANCE label
   *   row of [D-pad] [Select/Start] [A/B]
   *
   * Landscape (min-aspect-ratio 5/4): the controls dock into the
   *   left/right columns so the screen sits in the middle. Shoulders
   *   stay anchored to the top corners. Buttons never overlap the
   *   screen — the screen column is a flex track that takes
   *   whatever space the auto-sized dock columns leave.
   * ============================================================ */
  .gba {
    position: relative;
    width: 100%;
    max-width: 1180px;
    padding: clamp(18px, 3vw, 30px) clamp(20px, 4vw, 38px);
    border-radius: 32px;
    background:
      radial-gradient(ellipse at 30% 18%, var(--bezel-light) 0%, transparent 65%),
      linear-gradient(165deg, #3b1f6b 0%, var(--bezel-dark) 100%);
    box-shadow:
      inset 0 2px 0 rgba(255,255,255,0.08),
      inset 0 -4px 0 rgba(0,0,0,0.4),
      0 30px 80px rgba(0,0,0,0.55),
      0 0 60px rgba(124,58,237,0.22);

    display: grid;
    grid-template-columns: 1fr;
    grid-template-areas:
      "shoulders"
      "screen"
      "label"
      "controls";
    gap: clamp(0.8rem, 2vw, 1.4rem);
    align-items: center;
    justify-items: center;
  }

  .gba__shoulders {
    grid-area: shoulders;
    position: relative;
    width: 100%;
    height: 0;
  }
  .gba__shoulder {
    position: absolute;
    top: -28px;
    width: clamp(72px, 14vw, 120px);
    height: 22px;
    border-radius: 8px 8px 4px 4px;
    background: linear-gradient(180deg, #14062a 0%, #2a153f 100%);
    border: 1px solid #1a0c2e;
    color: var(--text-dim);
    font-family: "Press Start 2P", monospace;
    font-size: 9px;
    letter-spacing: 0.1em;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: transform 0.06s ease, box-shadow 0.06s ease;
    box-shadow:
      inset 0 1px 0 rgba(255,255,255,0.06),
      0 2px 0 rgba(0,0,0,0.5);
  }
  .gba__shoulder--l { left: 4%; }
  .gba__shoulder--r { right: 4%; }
  .gba__shoulder.is-pressed {
    transform: translateY(2px);
    box-shadow: 0 0 0 rgba(0,0,0,0.5),
                inset 0 0 12px rgba(167,139,250,0.4);
    color: var(--accent-hot);
  }

  .gba__screen {
    grid-area: screen;
    position: relative;
    width: 100%;
    max-width: min(580px, calc(70vh * 1.5));
    aspect-ratio: 3 / 2;
    background: #0a0612;
    border-radius: 6px;
    box-shadow:
      inset 0 0 0 2px #1a0c2e,
      inset 0 0 0 6px #0a0612,
      inset 0 8px 28px rgba(0,0,0,0.8);
    overflow: hidden;
    justify-self: center;
  }
  .gba__screen canvas {
    display: block;
    width: 100%;
    height: 100%;
    image-rendering: pixelated;
  }
  .gba__screen::after {
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;
    background: repeating-linear-gradient(
      0deg, transparent 0 2px, rgba(0,0,0,0.18) 2px 3px
    );
    mix-blend-mode: multiply;
  }
  .gba__screen-glow {
    position: absolute;
    inset: 0;
    pointer-events: none;
    background:
      radial-gradient(ellipse at 50% 0%, rgba(255,255,255,0.08) 0%, transparent 60%),
      radial-gradient(ellipse at 50% 50%, transparent 60%, rgba(0,0,0,0.4) 100%);
  }
  .gba__label {
    grid-area: label;
    text-align: center;
    color: rgba(255,255,255,0.3);
    font-family: "Press Start 2P", monospace;
    font-size: 8px;
    letter-spacing: 0.18em;
  }

  /* ============================================================
   * Controls — visible only when mode=controller. In portrait
   * they sit on a row beneath the screen; in landscape they dock
   * into the left + right columns flanking the screen.
   * ============================================================ */
  body[data-mode="viewer"] .gba__controls { display: none; }
  .gba__controls {
    grid-area: controls;
    width: 100%;
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    grid-template-areas: "dpad meta abxy";
    align-items: center;
    gap: clamp(0.6rem, 2vw, 1.4rem);
  }
  .dpad-wrap, .abxy-wrap { display: contents; }

  /* Landscape: dock columns. We flip the entire .gba grid to a
   * 3-column shape with the screen as the flex middle, and let
   * display:contents on .gba__controls hoist the dpad/meta/abxy
   * children into the parent grid. */
  @media (min-aspect-ratio: 5/4) and (min-width: 760px) {
    .gba {
      grid-template-columns: minmax(180px, 1fr) minmax(360px, 3fr) minmax(180px, 1fr);
      grid-template-areas:
        "shoulders shoulders shoulders"
        "dpad      screen    abxy"
        ".         label     ."
        ".         meta      .";
      gap: clamp(0.8rem, 1.5vw, 1.4rem) clamp(1rem, 2vw, 2rem);
      align-items: center;
    }
    .gba__screen {
      max-width: min(620px, calc(75vh * 1.5));
      max-height: 75vh;
    }
    .gba__controls {
      display: contents;
    }
    .dpad {
      grid-area: dpad;
      justify-self: center;
    }
    .abxy {
      grid-area: abxy;
      justify-self: center;
    }
    .meta {
      grid-area: meta;
      justify-self: center;
    }
  }

  /* D-pad */
  .dpad {
    grid-area: dpad;
    position: relative;
    width: clamp(120px, 22vmin, 180px);
    aspect-ratio: 1;
    margin: 0 auto;
  }
  .dpad-btn {
    position: absolute;
    background: linear-gradient(180deg, #2a2849 0%, #14122a 100%);
    border: 1px solid #0a0816;
    color: var(--text);
    font-family: inherit;
    font-size: 1.4rem;
    line-height: 1;
    cursor: pointer;
    box-shadow:
      inset 0 1px 0 rgba(255,255,255,0.06),
      0 2px 0 #0a0816;
    transition: transform 0.06s ease, box-shadow 0.06s ease, background 0.1s ease;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
  }
  .dpad-btn.is-pressed {
    transform: translateY(2px);
    box-shadow: inset 0 0 12px rgba(167,139,250,0.5),
                0 0 0 #0a0816;
    background: linear-gradient(180deg, #1a1830 0%, #0a0816 100%);
    color: var(--accent-hot);
  }
  .dpad-up    { left: 33%; right: 33%; top: 0;    bottom: 67%; border-radius: 6px 6px 0 0; }
  .dpad-down  { left: 33%; right: 33%; top: 67%;  bottom: 0;   border-radius: 0 0 6px 6px; }
  .dpad-left  { left: 0;   right: 67%; top: 33%;  bottom: 33%; border-radius: 6px 0 0 6px; }
  .dpad-right { left: 67%; right: 0;   top: 33%;  bottom: 33%; border-radius: 0 6px 6px 0; }
  .dpad::before {
    content: "";
    position: absolute;
    inset: 33% 33%;
    background: linear-gradient(135deg, #14122a, #2a2849);
    border: 1px solid #0a0816;
    pointer-events: none;
  }

  /* A / B */
  .abxy {
    grid-area: abxy;
    position: relative;
    width: clamp(120px, 22vmin, 180px);
    height: clamp(110px, 20vmin, 160px);
    margin: 0 auto;
    transform: rotate(-18deg);
  }
  .ab-btn {
    position: absolute;
    width: clamp(56px, 10vmin, 84px);
    height: clamp(56px, 10vmin, 84px);
    border-radius: 50%;
    border: none;
    cursor: pointer;
    color: rgba(255,255,255,0.92);
    font-family: "Press Start 2P", monospace;
    font-size: 13px;
    background:
      radial-gradient(circle at 30% 25%, #ffaad8 0%, #f0abfc 35%, #a83b8a 100%);
    box-shadow:
      inset 0 -3px 0 rgba(0,0,0,0.35),
      inset 0 2px 0 rgba(255,255,255,0.35),
      0 4px 0 #2a153f;
    transition: transform 0.06s ease, box-shadow 0.06s ease;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .ab-btn.is-pressed {
    transform: translateY(3px);
    box-shadow:
      inset 0 -1px 0 rgba(0,0,0,0.35),
      inset 0 2px 0 rgba(255,255,255,0.25),
      0 0 0 #2a153f,
      0 0 20px rgba(240,171,252,0.55);
  }
  .ab-a { top: 5%;  right: 0; }
  .ab-b { top: 38%; right: 38%; }

  /* TURBO button — sits beneath A/B in the .abxy box (rotated with it).
   * Sends {"type":"fast_forward","on":...} over the WS instead of a
   * GBA button name. Visual: amber pill so it reads as a meta-control,
   * not a GBA face button. */
  .turbo-btn {
    position: absolute;
    bottom: -12%;
    left: -4%;
    transform: rotate(18deg);  /* unrotate against .abxy's parent rotate */
    border: 1px solid #1a0c2e;
    background:
      linear-gradient(180deg, #fbbf24 0%, #b45309 100%);
    color: #1a0c2e;
    font-family: "Press Start 2P", monospace;
    font-size: clamp(11px, 1.4vmin, 14px);
    letter-spacing: 0.16em;
    padding: 0.85em 1.5em;
    border-radius: 999px;
    cursor: pointer;
    box-shadow:
      inset 0 1px 0 rgba(255,255,255,0.4),
      0 4px 0 rgba(0,0,0,0.45);
    transition: transform 0.06s ease, box-shadow 0.06s ease,
                background 0.1s ease, filter 0.1s ease;
  }
  .turbo-btn.is-pressed {
    transform: rotate(18deg) translateY(3px);
    box-shadow: 0 0 0 rgba(0,0,0,0.45),
                inset 0 0 14px rgba(255,255,255,0.5),
                0 0 28px rgba(251,191,36,0.65);
    filter: brightness(1.18);
  }

  /* Start / Select pills (and Shoulder L/R for reachable layout). */
  .meta {
    grid-area: meta;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.65rem;
    padding: 0.4rem 0;
  }
  .meta-row {
    display: flex;
    gap: 0.85rem;
    align-items: center;
  }
  .pill-btn {
    border: 1px solid #0a0816;
    background: linear-gradient(180deg, #2a2849 0%, #14122a 100%);
    color: var(--text-dim);
    font-family: "Press Start 2P", monospace;
    font-size: 8px;
    letter-spacing: 0.14em;
    padding: 0.55em 1.2em;
    border-radius: 999px;
    cursor: pointer;
    box-shadow:
      inset 0 1px 0 rgba(255,255,255,0.06),
      0 2px 0 rgba(0,0,0,0.5);
    transition: transform 0.06s ease, box-shadow 0.06s ease, color 0.1s ease;
  }
  .pill-btn.is-pressed {
    transform: translateY(2px);
    box-shadow: 0 0 0 rgba(0,0,0,0.5),
                inset 0 0 10px rgba(167,139,250,0.4);
    color: var(--accent-hot);
  }

  /* NES has no L/R shoulder buttons. When the runtime tells us
   * console=nes the bezel hides the shoulders entirely. SNES has
   * L/R but the GBA-shaped bezel doesn't accurately model the SNES
   * face-button cross — for v1 we leave the GBA layout in place
   * and let users hit L/R/A/B as-is. */
  body[data-console="nes"] .gba__shoulder { display: none; }
  body[data-console="nes"] .gba__shoulders { height: 0; min-height: 0; }

  /* Very narrow / tall — give Select+Start their own row beneath
   * the screen so D-pad and A/B don't get squeezed. */
  @media (max-aspect-ratio: 5/4) and (max-width: 520px) {
    .gba__controls {
      grid-template-columns: 1fr 1fr;
      grid-template-areas:
        "dpad abxy"
        "meta meta";
      row-gap: 1rem;
    }
  }
</style>
</head>
<body data-mode="viewer">
<header>
  <h1>retrokix<span class="dot">·</span>stream</h1>
  <span class="mode-badge" id="mode-badge">VIEWER</span>
  <button class="header-btn" id="saves-toggle" type="button" title="Save states (Ctrl+S / Ctrl+L mirror)">💾 saves</button>
  <button class="header-btn" id="cheats-toggle" type="button" title="Cheat codes for this ROM">🃏 cheats</button>
  <button class="audio-toggle" id="audio-toggle" type="button" title="Toggle browser audio">🔇 audio</button>
  <div class="hud">
    <span><span id="status-dot"></span><span id="status">connecting…</span></span>
    <span>fps <b id="fps">0</b></span>
    <span>kb/frame <b id="size">0</b></span>
  </div>
</header>
<main>
  <div class="gba">
    <div class="gba__shoulders">
      <button class="gba__shoulder gba__shoulder--l gba-btn" data-button="L">L</button>
      <button class="gba__shoulder gba__shoulder--r gba-btn" data-button="R">R</button>
    </div>
    <div class="gba__screen">
      <canvas id="screen" width="240" height="160" aria-label="retrokix live frame"></canvas>
      <div class="gba__screen-glow"></div>
    </div>
    <div class="gba__label">GAME BOY ADVANCE</div>
    <div class="gba__controls" aria-hidden="false">
      <div class="dpad" role="group" aria-label="D-pad">
        <button class="dpad-btn dpad-up gba-btn"    data-button="UP">↑</button>
        <button class="dpad-btn dpad-down gba-btn"  data-button="DOWN">↓</button>
        <button class="dpad-btn dpad-left gba-btn"  data-button="LEFT">←</button>
        <button class="dpad-btn dpad-right gba-btn" data-button="RIGHT">→</button>
      </div>
      <div class="meta">
        <div class="meta-row">
          <button class="pill-btn gba-btn" data-button="SELECT">Select</button>
          <button class="pill-btn gba-btn" data-button="START">Start</button>
        </div>
      </div>
      <div class="abxy" role="group" aria-label="Action buttons">
        <button class="ab-btn ab-a gba-btn" data-button="A">A</button>
        <button class="ab-btn ab-b gba-btn" data-button="B">B</button>
        <button class="turbo-btn" id="turbo-btn" type="button" aria-pressed="false">Turbo</button>
      </div>
    </div>
  </div>
</main>
<div class="overlay" id="overlay"></div>
<section class="panel" id="saves-panel" aria-hidden="true">
  <header class="panel__header">
    <h2 class="panel__title">💾 Save states</h2>
    <button class="panel__action" id="saves-save-now" type="button">Save now</button>
    <button class="panel__close" data-close="saves-panel" type="button" aria-label="Close">✕</button>
  </header>
  <div class="panel__body" id="saves-body">
    <p class="panel__empty">loading…</p>
  </div>
</section>
<section class="panel" id="cheats-panel" aria-hidden="true">
  <header class="panel__header">
    <h2 class="panel__title">🃏 Cheats</h2>
    <button class="panel__close" data-close="cheats-panel" type="button" aria-label="Close">✕</button>
  </header>
  <div class="panel__body">
    <input class="cheat-search" id="cheats-search" type="search" placeholder="Filter cheats…" autocomplete="off">
    <div id="cheats-body">
      <p class="panel__empty">loading…</p>
    </div>
  </div>
</section>
<div class="toast" id="toast" role="status"></div>
<footer>
  WebSocket: <code id="ws-url">/stream/ws</code>
  &middot; <a href="?mode=viewer">viewer</a>
  &middot; <a href="?mode=controller">controller</a>
  &middot; <a href="?mode=controller&format=raw">raw</a>
  &middot; <a href="?mode=controller&format=jpeg">jpeg</a>
</footer>
<script>
(() => {
  const params = new URLSearchParams(location.search);
  const mode    = (params.get("mode") || "viewer").toLowerCase();
  const fps     = params.get("fps")     || "30";
  const quality = params.get("quality") || "92";
  const fmt     = (params.get("format") || "raw").toLowerCase() === "jpeg"
                    ? "jpeg" : "raw";
  const isController = mode === "controller";
  document.body.dataset.mode = isController ? "controller" : "viewer";
  document.getElementById("mode-badge").textContent = isController ? "CONTROLLER" : "VIEWER";

  const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
  const wsQs = fmt === "jpeg"
    ? `fps=${fps}&format=jpeg&quality=${quality}`
    : `fps=${fps}&format=raw`;
  const wsPath  = `/stream/ws?${wsQs}`;
  const url = `${wsProto}//${location.host}${wsPath}`;
  document.getElementById("ws-url").textContent = wsPath;

  const canvas = document.getElementById("screen");
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  const fpsEl  = document.getElementById("fps");
  const sizeEl = document.getElementById("size");
  const statusEl = document.getElementById("status");
  const statusDot = document.getElementById("status-dot");

  let ws = null;
  let frames = 0;
  let bytes = 0;
  let lastReport = performance.now();

  function setStatus(label, state) {
    statusEl.textContent = label;
    statusDot.classList.remove("live", "err");
    if (state) statusDot.classList.add(state);
  }

  // Console slug (gba/nes/…) sent in the info handshake. Drives the
  // L/R shoulder button visibility (NES has neither).
  let currentConsole = null;
  function applyRuntimeInfo(info) {
    if (info.width && info.height) {
      if (canvas.width !== info.width)  canvas.width  = info.width;
      if (canvas.height !== info.height) canvas.height = info.height;
      const screen = document.querySelector(".gba__screen");
      if (screen && info.aspect && Number.isFinite(info.aspect) && info.aspect > 0) {
        screen.style.aspectRatio = `${info.aspect}`;
      }
    }
    if (info.console && info.console !== currentConsole) {
      currentConsole = info.console;
      document.body.dataset.console = info.console;
    }
  }

  function connect() {
    setStatus("connecting…");
    ws = new WebSocket(url);
    // Raw frames arrive as ArrayBuffer so we can feed them directly
    // into ImageData/putImageData without a Blob roundtrip; JPEG
    // frames stay as Blob for createImageBitmap.
    ws.binaryType = fmt === "raw" ? "arraybuffer" : "blob";

    ws.addEventListener("open", () => {
      setStatus("live", "live");
      // On reconnect, sync the held set so the runtime stops
      // believing buttons from a dead client are still down.
      sendButtons();
    });
    ws.addEventListener("error", () => setStatus("error", "err"));
    ws.addEventListener("close", () => {
      setStatus("reconnecting…", "err");
      setTimeout(connect, 1000);
    });

    ws.addEventListener("message", async (evt) => {
      // Info handshake — server sends one text message before frames so
      // we can size the canvas to the running console (240x160 GBA,
      // 256x240 NES, …) before drawing the first frame.
      if (typeof evt.data === "string") {
        try {
          const info = JSON.parse(evt.data);
          if (info.type === "info") {
            applyRuntimeInfo(info);
          }
        } catch (_e) { /* ignore */ }
        return;
      }
      if (fmt === "raw") {
        const ab = evt.data;
        bytes += ab.byteLength;
        const arr = new Uint8ClampedArray(ab);
        if (arr.length === canvas.width * canvas.height * 4) {
          ctx.putImageData(new ImageData(arr, canvas.width, canvas.height), 0, 0);
        }
      } else {
        bytes += evt.data.size;
        try {
          const bmp = await createImageBitmap(evt.data);
          ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
          bmp.close();
        } catch (_e) { /* drop frame on decode race */ }
      }
      frames++;
      const now = performance.now();
      if (now - lastReport >= 1000) {
        fpsEl.textContent  = frames.toString();
        sizeEl.textContent = frames > 0 ? (bytes / frames / 1024).toFixed(1) : "0";
        frames = 0;
        bytes = 0;
        lastReport = now;
      }
    });
  }

  /* ---------- input ---------- */
  // Set of currently-held GBA button names. Mutations call sendButtons.
  const held = new Set();
  // Map pointerId → button name so multi-touch releases the right button.
  const pointerToButton = new Map();
  // Map keyboard code → button name.
  const keyToButton = {
    "ArrowUp":    "UP",    "ArrowDown":  "DOWN",
    "ArrowLeft":  "LEFT",  "ArrowRight": "RIGHT",
    "KeyX":       "A",     "KeyZ":       "B",
    "KeyA":       "L",     "KeyS":       "R",
    "Enter":      "START", "ShiftRight": "SELECT",
    "Backspace":  "SELECT",
  };
  const buttonNodes = {};
  for (const el of document.querySelectorAll(".gba-btn[data-button]")) {
    buttonNodes[el.dataset.button] = el;
  }

  function press(name) {
    if (!isController) return;
    if (held.has(name)) return;
    held.add(name);
    buttonNodes[name]?.classList.add("is-pressed");
    sendButtons();
  }
  function release(name) {
    if (!isController) return;
    if (!held.has(name)) return;
    held.delete(name);
    buttonNodes[name]?.classList.remove("is-pressed");
    sendButtons();
  }
  function sendButtons() {
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify({ type: "buttons", buttons: [...held] }));
    }
  }

  /* ---------- TURBO ---------- */
  function sendFastForward(on) {
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify({ type: "fast_forward", on: !!on }));
    }
  }

  if (isController) {
    const turbo = document.getElementById("turbo-btn");
    if (turbo) {
      const turboDown = (e) => {
        e.preventDefault();
        try { turbo.setPointerCapture(e.pointerId); } catch (_e) {}
        turbo.classList.add("is-pressed");
        turbo.setAttribute("aria-pressed", "true");
        sendFastForward(true);
      };
      const turboUp = (e) => {
        turbo.classList.remove("is-pressed");
        turbo.setAttribute("aria-pressed", "false");
        sendFastForward(false);
      };
      turbo.addEventListener("pointerdown", turboDown);
      turbo.addEventListener("pointerup", turboUp);
      turbo.addEventListener("pointercancel", turboUp);
      turbo.addEventListener("lostpointercapture", turboUp);
      turbo.addEventListener("contextmenu", (e) => e.preventDefault());
    }

    for (const el of Object.values(buttonNodes)) {
      const name = el.dataset.button;
      el.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        try { el.setPointerCapture(e.pointerId); } catch (_e) {}
        pointerToButton.set(e.pointerId, name);
        press(name);
      });
      const releaseFromPointer = (e) => {
        const btn = pointerToButton.get(e.pointerId);
        if (btn !== undefined) {
          pointerToButton.delete(e.pointerId);
          release(btn);
        }
      };
      el.addEventListener("pointerup", releaseFromPointer);
      el.addEventListener("pointercancel", releaseFromPointer);
      el.addEventListener("lostpointercapture", releaseFromPointer);
      el.addEventListener("contextmenu", (e) => e.preventDefault());
    }

    window.addEventListener("keydown", (e) => {
      const name = keyToButton[e.code];
      if (!name) return;
      e.preventDefault();
      press(name);
    });
    window.addEventListener("keyup", (e) => {
      const name = keyToButton[e.code];
      if (!name) return;
      e.preventDefault();
      release(name);
    });
    // If the tab loses focus, drop all keyboard-held buttons so the
    // emulator doesn't sit on a phantom 'right'.
    window.addEventListener("blur", () => {
      for (const name of [...held]) release(name);
      sendFastForward(false);
    });
  }

  /* ---------- audio ---------- */
  // Streams raw PCM s16le stereo @ 32768 Hz from /stream/audio/ws into
  // an AudioWorkletProcessor that owns a ring buffer. Auto-opens on
  // the first user click (autoplay policy); a 🔊/🔇 toggle in the
  // header lets the user mute without tearing the WS down.
  const AUDIO_SAMPLE_RATE = 32768;
  const audioBtn = document.getElementById("audio-toggle");
  let audioCtx = null;
  let audioNode = null;
  let audioWs = null;
  let audioOn = false;

  const WORKLET_SRC = `
    class GbaPCM extends AudioWorkletProcessor {
      constructor() {
        super();
        this.queue = []; // Float32Array chunks pending playback
        this.offset = 0; // sample index inside this.queue[0]
        this.port.onmessage = (e) => {
          if (e.data instanceof Float32Array) this.queue.push(e.data);
          else if (e.data === 'clear') { this.queue = []; this.offset = 0; }
        };
      }
      process(_inputs, outputs) {
        const out = outputs[0];
        const L = out[0]; const R = out[1] || out[0];
        const n = L.length;
        for (let i = 0; i < n; i++) {
          if (this.queue.length === 0) { L[i] = 0; R[i] = 0; continue; }
          const head = this.queue[0];
          L[i] = head[this.offset]; R[i] = head[this.offset + 1];
          this.offset += 2;
          if (this.offset >= head.length) { this.queue.shift(); this.offset = 0; }
        }
        return true;
      }
    }
    registerProcessor('gba-pcm', GbaPCM);
  `;

  async function audioStart() {
    if (audioOn) return;
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: AUDIO_SAMPLE_RATE,
        latencyHint: 'interactive',
      });
      const blob = new Blob([WORKLET_SRC], { type: 'application/javascript' });
      const blobUrl = URL.createObjectURL(blob);
      await audioCtx.audioWorklet.addModule(blobUrl);
      URL.revokeObjectURL(blobUrl);
      audioNode = new AudioWorkletNode(audioCtx, 'gba-pcm', {
        numberOfInputs: 0, outputChannelCount: [2],
      });
      audioNode.connect(audioCtx.destination);
    }
    if (audioCtx.state === 'suspended') await audioCtx.resume();
    if (!audioWs || audioWs.readyState > 1) {
      const audioUrl = `${wsProto}//${location.host}/stream/audio/ws`;
      audioWs = new WebSocket(audioUrl);
      audioWs.binaryType = 'arraybuffer';
      audioWs.addEventListener('message', (evt) => {
        if (!audioNode) return;
        const i16 = new Int16Array(evt.data);
        const f32 = new Float32Array(i16.length);
        for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
        audioNode.port.postMessage(f32);
      });
      audioWs.addEventListener('close', () => { if (audioOn) setTimeout(() => audioOn && audioStart(), 750); });
    }
    audioOn = true;
    audioBtn.textContent = '🔊 audio';
    audioBtn.classList.add('is-on');
  }

  function audioStop() {
    audioOn = false;
    if (audioWs) { try { audioWs.close(); } catch (_e) {} audioWs = null; }
    if (audioNode) audioNode.port.postMessage('clear');
    if (audioCtx && audioCtx.state === 'running') audioCtx.suspend();
    audioBtn.textContent = '🔇 audio';
    audioBtn.classList.remove('is-on');
  }

  audioBtn.addEventListener('click', () => {
    if (audioOn) audioStop(); else audioStart().catch(() => audioStop());
  });
  // Auto-enable on the first user gesture so iOS/Safari grant audio.
  const tryAutoStart = () => {
    audioStart().catch(() => {});
    window.removeEventListener('pointerdown', tryAutoStart, true);
    window.removeEventListener('keydown', tryAutoStart, true);
  };
  window.addEventListener('pointerdown', tryAutoStart, true);
  window.addEventListener('keydown', tryAutoStart, true);

  /* ---------- toast ---------- */
  const toastEl = document.getElementById('toast');
  let toastTimer = null;
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add('is-visible');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('is-visible'), 2200);
  }

  /* ---------- overlay panels ---------- */
  const overlay = document.getElementById('overlay');
  const savesBtn = document.getElementById('saves-toggle');
  const cheatsBtn = document.getElementById('cheats-toggle');
  const savesPanel = document.getElementById('saves-panel');
  const cheatsPanel = document.getElementById('cheats-panel');

  function openPanel(panel, btn) {
    closePanels();
    panel.classList.add('is-open');
    panel.setAttribute('aria-hidden', 'false');
    btn.classList.add('is-open');
    overlay.classList.add('is-open');
  }
  function closePanels() {
    for (const p of [savesPanel, cheatsPanel]) {
      p.classList.remove('is-open');
      p.setAttribute('aria-hidden', 'true');
    }
    savesBtn.classList.remove('is-open');
    cheatsBtn.classList.remove('is-open');
    overlay.classList.remove('is-open');
  }
  overlay.addEventListener('click', closePanels);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closePanels();
  });
  for (const el of document.querySelectorAll('[data-close]')) {
    el.addEventListener('click', closePanels);
  }

  /* ---------- saves panel ---------- */
  const RTF = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
  function relTime(iso) {
    const t = new Date(iso).getTime();
    const diff = (t - Date.now()) / 1000;  // seconds, negative = past
    const abs = Math.abs(diff);
    if (abs < 60) return RTF.format(Math.round(diff), 'second');
    if (abs < 3600) return RTF.format(Math.round(diff / 60), 'minute');
    if (abs < 86400) return RTF.format(Math.round(diff / 3600), 'hour');
    return RTF.format(Math.round(diff / 86400), 'day');
  }

  async function refreshSaves() {
    const body = document.getElementById('saves-body');
    try {
      const data = await (await fetch('/savestate/list')).json();
      const lines = [];
      if (data.running && data.running.length) {
        lines.push('<div class="panel__group-label">Running stream</div>');
        for (const s of data.running) {
          lines.push(`<button class="save-item" data-running="${s.name}">
            <span class="save-item__kind">📜</span>
            <span class="save-item__name">${s.name.replace(/^running-/, '').replace(/\\.state$/, '')}</span>
            <span class="save-item__when">${relTime(s.mtime)}</span>
          </button>`);
        }
      }
      if (data.slots && data.slots.length) {
        lines.push('<div class="panel__group-label">Numbered slots</div>');
        for (const s of data.slots) {
          lines.push(`<button class="save-item" data-slot="${s.slot}">
            <span class="save-item__kind">${s.slot}</span>
            <span class="save-item__name">Slot ${s.slot}</span>
            <span class="save-item__when">${relTime(s.mtime)}</span>
          </button>`);
        }
      }
      if (!lines.length) {
        body.innerHTML = '<p class="panel__empty">No saves yet. Press <b>Save now</b> or <kbd>Ctrl+S</kbd> in the SDL window.</p>';
        return;
      }
      body.innerHTML = lines.join('');
      for (const el of body.querySelectorAll('[data-running]')) {
        el.addEventListener('click', () => loadSave({ running: el.dataset.running }));
      }
      for (const el of body.querySelectorAll('[data-slot]')) {
        el.addEventListener('click', () => loadSave({ slot: Number(el.dataset.slot) }));
      }
    } catch (err) {
      body.innerHTML = `<p class="panel__empty">failed to list saves: ${err}</p>`;
    }
  }

  async function saveNow() {
    try {
      const r = await fetch('/savestate/save', { method: 'POST' });
      const d = await r.json();
      toast(`saved → ${d.name.replace(/^running-/, '').replace(/\\.state$/, '')}`);
      await refreshSaves();
    } catch (err) {
      toast(`save failed: ${err}`);
    }
  }

  async function loadSave(payload) {
    try {
      const r = await fetch('/savestate/load', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      toast(`loaded ← ${d.loaded}`);
      closePanels();
    } catch (err) {
      toast(`load failed: ${err}`);
    }
  }

  savesBtn.addEventListener('click', () => {
    if (savesPanel.classList.contains('is-open')) { closePanels(); return; }
    openPanel(savesPanel, savesBtn);
    refreshSaves();
  });
  document.getElementById('saves-save-now').addEventListener('click', saveNow);

  /* ---------- cheats panel ---------- */
  let cheatsCache = null;
  async function refreshCheats(filter) {
    const body = document.getElementById('cheats-body');
    try {
      if (cheatsCache === null) {
        const d = await (await fetch('/cheats')).json();
        cheatsCache = d.catalog || [];
      }
      const needle = (filter || '').trim().toLowerCase();
      const list = cheatsCache.filter(c =>
        !needle || c.name.toLowerCase().includes(needle) || c.slug.toLowerCase().includes(needle)
      );
      if (!list.length) {
        body.innerHTML = '<p class="panel__empty">No cheats catalogued for this ROM.</p>';
        return;
      }
      body.innerHTML = list.map(c => `
        <button class="cheat-item" data-slug="${c.slug}" data-active="${c.active}">
          <span class="cheat-item__icon ${c.active ? 'is-active' : ''}">${c.active ? '✓' : '○'}</span>
          <span><span class="cheat-item__name">${c.name}</span>
                <div class="cheat-item__code">${c.slug}</div></span>
          <span></span>
        </button>
      `).join('');
      for (const el of body.querySelectorAll('[data-slug]')) {
        el.addEventListener('click', () => toggleCheat(el.dataset.slug, el.dataset.active === 'true'));
      }
    } catch (err) {
      body.innerHTML = `<p class="panel__empty">failed to list cheats: ${err}</p>`;
    }
  }

  async function toggleCheat(slug, currentlyActive) {
    const action = currentlyActive ? 'disable' : 'enable';
    try {
      const r = await fetch(`/cheats/${encodeURIComponent(slug)}/${action}`, { method: 'POST' });
      if (!r.ok) throw new Error(await r.text());
      // Mutate cache in place so the UI updates without a round trip.
      const item = cheatsCache && cheatsCache.find(c => c.slug === slug);
      if (item) item.active = !currentlyActive;
      toast(`${currentlyActive ? 'disabled' : 'enabled'} ${slug}`);
      refreshCheats(document.getElementById('cheats-search').value);
    } catch (err) {
      toast(`cheat toggle failed: ${err}`);
    }
  }

  cheatsBtn.addEventListener('click', () => {
    if (cheatsPanel.classList.contains('is-open')) { closePanels(); return; }
    openPanel(cheatsPanel, cheatsBtn);
    refreshCheats('');
  });
  document.getElementById('cheats-search').addEventListener('input', (e) => {
    refreshCheats(e.target.value);
  });

  connect();
})();
</script>
</body>
</html>
"""
