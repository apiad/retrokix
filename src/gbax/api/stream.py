"""/stream — live framebuffer over WebSocket + a self-contained HTML viewer.

Two routes:

  GET  /stream             — HTML viewer with the gbax-stylish GBA
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
  quality  — JPEG quality (10..95, default 75)

Bandwidth math: 240×160 RGB → JPEG q75 is ~5–15 KB/frame → ~150–450
KB/s at 30 fps.
"""

from __future__ import annotations

import asyncio
import json
from io import BytesIO

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from PIL import Image

from gbax.input import button_from_str


_MIN_FPS, _MAX_FPS, _DEFAULT_FPS = 1, 60, 30
_MIN_Q, _MAX_Q, _DEFAULT_Q = 10, 95, 75


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/stream", response_class=HTMLResponse)
    def viewer() -> HTMLResponse:
        return HTMLResponse(_VIEWER_HTML)

    @router.websocket("/stream/ws")
    async def stream_ws(
        websocket: WebSocket,
        fps: int = _DEFAULT_FPS,
        quality: int = _DEFAULT_Q,
    ) -> None:
        await websocket.accept()
        rt = websocket.app.state.runtime
        fps = max(_MIN_FPS, min(_MAX_FPS, fps))
        quality = max(_MIN_Q, min(_MAX_Q, quality))
        interval = 1.0 / fps
        loop = asyncio.get_event_loop()

        async def _receive_loop() -> None:
            """Parse `{"type":"buttons","buttons":[...]}` text messages
            from the client and replace the runtime's held set. Bad
            payloads are dropped silently — easier to debug client-side
            than to wire an error channel back."""
            while True:
                msg = await websocket.receive_text()
                try:
                    parsed = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                if parsed.get("type") != "buttons":
                    continue
                names = parsed.get("buttons", [])
                if not isinstance(names, list):
                    continue
                try:
                    buttons = {button_from_str(b) for b in names}
                except ValueError:
                    continue
                rt.set_buttons(buttons)

        recv_task = asyncio.create_task(_receive_loop())
        try:
            while True:
                t0 = loop.time()
                fb = rt.framebuffer()
                buf = BytesIO()
                Image.fromarray(fb).save(buf, format="JPEG", quality=quality)
                await websocket.send_bytes(buf.getvalue())
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

    return router


_VIEWER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>gbax — stream</title>
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
  <h1>gbax<span class="dot">·</span>stream</h1>
  <span class="mode-badge" id="mode-badge">VIEWER</span>
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
      <canvas id="screen" width="240" height="160" aria-label="gbax live frame"></canvas>
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
      </div>
    </div>
  </div>
</main>
<footer>
  WebSocket: <code id="ws-url">/stream/ws</code>
  &middot; <a href="?mode=viewer">viewer</a>
  &middot; <a href="?mode=controller">controller</a>
</footer>
<script>
(() => {
  const params = new URLSearchParams(location.search);
  const mode    = (params.get("mode") || "viewer").toLowerCase();
  const fps     = params.get("fps")     || "30";
  const quality = params.get("quality") || "75";
  const isController = mode === "controller";
  document.body.dataset.mode = isController ? "controller" : "viewer";
  document.getElementById("mode-badge").textContent = isController ? "CONTROLLER" : "VIEWER";

  const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
  const wsPath  = `/stream/ws?fps=${fps}&quality=${quality}`;
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

  function connect() {
    setStatus("connecting…");
    ws = new WebSocket(url);
    ws.binaryType = "blob";

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
      bytes += evt.data.size;
      try {
        const bmp = await createImageBitmap(evt.data);
        ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
        bmp.close();
      } catch (_e) { /* drop frame on decode race */ }
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

  if (isController) {
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
    });
  }

  connect();
})();
</script>
</body>
</html>
"""
