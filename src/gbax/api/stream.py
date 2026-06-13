"""/stream — live framebuffer over WebSocket + a self-contained HTML viewer.

Two routes:

  GET  /stream         — HTML page with a canvas + a few lines of JS that
                         opens the WebSocket below and draws each frame.
  WS   /stream/ws      — pushes JPEG-encoded framebuffer bytes at the
                         requested fps (default 30, max 60). Each WS
                         message is a single binary JPEG blob.

Query params on the WS:
  fps      — target frame rate (1..60, default 30)
  quality  — JPEG quality (10..95, default 75)

Bandwidth math: 240×160 RGB → JPEG q75 is ~10–20 KB/frame → ~300–600
KB/s at 30 fps. Fine over LAN, fine over the open internet.

Backpressure: we sleep to honour `fps`, but if the client can't keep
up the WS send_bytes call may block. We never queue; a slow client
just slows the producer naturally. No goal of jitter-free 60fps —
this is a scope-streaming feature, not a recording pipeline.
"""

from __future__ import annotations

import asyncio
from io import BytesIO

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from PIL import Image


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

    return router


_VIEWER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>gbax — stream</title>
<style>
  :root {
    --bg: #0b0a14;
    --bg-1: #11101f;
    --border: #2a2849;
    --text: #e9e9f4;
    --text-dim: #a4a4c8;
    --text-soft: #6e6c92;
    --accent: #a78bfa;
    --emerald: #34d399;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    background: radial-gradient(ellipse 80% 50% at 50% 0%,
                  rgba(124,58,237,0.15), transparent 60%),
                var(--bg);
    color: var(--text);
    font-family: "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace;
    min-height: 100vh;
    display: grid;
    grid-template-rows: auto 1fr auto;
  }
  header {
    padding: 1rem 1.25rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 1rem;
  }
  header h1 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    color: var(--text);
  }
  header h1 .dot { color: var(--accent); }
  header .hud {
    margin-left: auto;
    display: flex;
    gap: 1.5rem;
    font-size: 0.78rem;
    color: var(--text-dim);
  }
  header .hud span b {
    color: var(--text);
    font-weight: 600;
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
  #status-dot.err  { background: #fb7185; }
  main {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
  }
  .frame {
    position: relative;
    background: #000;
    border: 1px solid var(--border);
    border-radius: 14px;
    box-shadow: 0 30px 80px rgba(0,0,0,0.55),
                inset 0 0 0 6px #0a0612,
                0 0 60px rgba(124, 58, 237, 0.2);
    padding: 18px;
  }
  canvas {
    display: block;
    width: min(85vmin, 960px);
    aspect-ratio: 3 / 2;
    background: #0a0612;
    image-rendering: pixelated;
    border-radius: 4px;
  }
  /* Subtle CRT scanlines, same look as the landing page. */
  .frame::after {
    content: "";
    position: absolute;
    inset: 18px;
    border-radius: 4px;
    pointer-events: none;
    background: repeating-linear-gradient(
      0deg, transparent 0 2px, rgba(0,0,0,0.15) 2px 3px
    );
    mix-blend-mode: multiply;
  }
  footer {
    padding: 0.75rem 1.25rem;
    border-top: 1px solid var(--border);
    color: var(--text-soft);
    font-size: 0.75rem;
    text-align: center;
  }
  footer code {
    color: var(--accent);
    background: rgba(167,139,250,0.08);
    border: 1px solid rgba(167,139,250,0.18);
    padding: 0.08em 0.36em;
    border-radius: 4px;
  }
</style>
</head>
<body>
<header>
  <h1>gbax<span class="dot">·</span>stream</h1>
  <div class="hud">
    <span><span id="status-dot"></span><span id="status">connecting…</span></span>
    <span>fps <b id="fps">0</b></span>
    <span>kb/frame <b id="size">0</b></span>
  </div>
</header>
<main>
  <div class="frame">
    <canvas id="screen" width="240" height="160" aria-label="gbax live frame"></canvas>
  </div>
</main>
<footer>
  WebSocket: <code>/stream/ws?fps=30&amp;quality=75</code>
</footer>
<script>
(() => {
  const params = new URLSearchParams(location.search);
  const fps     = params.get("fps")     || "30";
  const quality = params.get("quality") || "75";
  const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${wsProto}//${location.host}/stream/ws?fps=${fps}&quality=${quality}`;

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

    ws.addEventListener("open", () => setStatus("live", "live"));
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
      } catch (_e) {
        // Decode race on tab background — drop the frame and continue.
      }
      frames++;
      const now = performance.now();
      if (now - lastReport >= 1000) {
        fpsEl.textContent  = frames.toString();
        sizeEl.textContent = frames > 0
          ? (bytes / frames / 1024).toFixed(1)
          : "0";
        frames = 0;
        bytes = 0;
        lastReport = now;
      }
    });
  }
  connect();
})();
</script>
</body>
</html>
"""
