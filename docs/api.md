# HTTP API reference

`gbax` exposes the running emulator as a FastAPI server. Two ways to
reach it:

```bash
gbax serve emerald                          # API only, no window
gbax play emerald --listen                  # API + SDL window (cooperative loop)
```

Both modes serve the same endpoints. The default bind is
`127.0.0.1:8420`; override with `--port` (on `serve`) or `--listen-host`
/ `--listen-port` (on `play`).

The endpoints are deliberately small and direct — `gbax` is a
substrate; the controllers are the interesting part.

## Modes: step vs free

`gbax` runs in one of two modes at any time:

| Mode | Behavior                                                                                                  |
| ---- | --------------------------------------------------------------------------------------------------------- |
| step | Emulator is **paused**. It advances only on explicit `POST /step?frames=N`. Deterministic, controller-paced. |
| free | Emulator runs at wall-clock 60 fps in a background thread (× `speed_multiplier`). `POST /step` is rejected.  |

`serve` starts in `step` by default — that's what makes AI controllers viable.
A slow controller (LLM, RL agent) holds the game still while it thinks.

`play` starts in `free` — humans want continuous motion.

## Control plane

### `GET /mode`

```
$ curl -s localhost:8420/mode
{"mode":"step"}
```

### `POST /mode`

```
$ curl -s -X POST localhost:8420/mode -H 'content-type: application/json' \
    -d '{"mode":"free"}'
{"mode":"free"}
```

Switching to `free` starts the background ticker; switching to `step` stops it.

### `POST /step?frames=N`

Advance the emulator by `N` frames. `409` in free mode.

```
$ curl -s -X POST 'localhost:8420/step?frames=4'
{"frame_count":4}
```

### `GET /speed`

```
$ curl -s localhost:8420/speed
{"multiplier":1.0}
```

### `POST /speed`

Set the free-run multiplier. `1.0` = real-time; higher = turbo.

```
$ curl -s -X POST localhost:8420/speed -H 'content-type: application/json' \
    -d '{"multiplier":4.0}'
{"multiplier":4.0}
```

### `GET /frame_count`

```
$ curl -s localhost:8420/frame_count
{"frame_count":120}
```

## Framebuffer

### `GET /frame` (PNG)

Default. Returns a 240×160 RGB PNG.

```
$ curl -s localhost:8420/frame -o frame.png
$ file frame.png
frame.png: PNG image data, 240 x 160, 8-bit/color RGB, non-interlaced
```

### `GET /frame?fmt=raw`

Returns raw RGB888 — `240 × 160 × 3 = 115200` bytes. Faster for
high-frequency consumers (RL training, video pipelines).

```
$ curl -s 'localhost:8420/frame?fmt=raw' | wc -c
115200
```

## Live stream

A WebSocket pushes frames continuously; an HTML viewer page bundles
the canvas + optional on-screen controller. Both routes share the
same query params.

### `GET /stream`

Self-contained viewer page — dark GBA-bezel styling, status / fps /
KB-per-frame HUD, auto-reconnect. Opens its own WebSocket against
`/stream/ws` with the same query params it received.

Modes:

- `?mode=viewer` (default) — just the framebuffer.
- `?mode=controller` — adds a responsive on-screen pad (D-pad +
  A/B + L/R shoulders + Select/Start). Touch / pointer events drive
  it; keyboard shortcuts (arrows / X / Z / A / S / Enter /
  RShift / Backspace) match the SDL play loop defaults. The layout
  docks the buttons to corners in portrait and to the sides in
  landscape so they never overlap the screen.

```
$ gbax play emerald --listen
# then open http://localhost:8420/stream
# or  http://localhost:8420/stream?mode=controller
```

### `WS /stream/ws`

Bidirectional WebSocket. Server → client pushes binary frames at
the requested fps. Client → server can replace the runtime's
held-button set in lockstep with the SDL keyboard / USB gamepad /
couch, so a phone in `?mode=controller` becomes another input
source that combines via set-union.

Query params:

| Param     | Default | Range / values     | Meaning                          |
| --------- | ------- | ------------------ | -------------------------------- |
| `fps`     | `30`    | `1..60`            | Target frame rate.               |
| `format`  | `raw`   | `raw \| jpeg`      | Frame encoding (see below).      |
| `quality` | `92`    | `10..95`           | JPEG quality (when `format=jpeg`). |
| `mode`    | `viewer`| `viewer \| controller` | Used by the HTML viewer; the WS itself is symmetric. |

Out-of-range values are clamped; unknown `format=` falls back to
`raw`.

#### Wire format

- **`format=raw` (default)** — RGBA8888 bytes, row-major,
  `240 × 160 × 4 = 153,600` bytes per frame. Lossless, pixel-exact.
  Browser decodes via `ImageData` + `putImageData` — no JPEG
  decode, no compression artifacts.
  Bandwidth: **~4.5 MB/s @ 30 fps**. Fine on localhost / LAN.
- **`format=jpeg`** — JPEG-encoded bytes, ~5–20 KB per frame at
  the default `quality=92`. Browser decodes via `createImageBitmap`.
  Bandwidth: **~150–600 KB/s @ 30 fps**. Use when streaming over
  a constrained connection.

#### Sending input

Client → server text frames carry the currently-held button set:

```json
{"type": "buttons", "buttons": ["UP", "A"]}
```

Each message **replaces** the previous held set, identical to
`POST /buttons`. Empty array releases all. Unknown button names and
malformed JSON are dropped silently — the connection stays alive,
no error frames.

#### Quick examples

Watch from a second screen:
```
http://<gbax-host>:8420/stream
```

Play from your phone in the same WiFi:
```
http://<gbax-host>:8420/stream?mode=controller
```

Save bandwidth on a remote link:
```
http://<gbax-host>:8420/stream?mode=controller&format=jpeg&fps=20
```

Drive the WebSocket directly from your own JS:
```js
const ws = new WebSocket(`ws://${host}:8420/stream/ws?format=raw&fps=30`);
ws.binaryType = "arraybuffer";
ws.onmessage = e => {
  const data = new Uint8ClampedArray(e.data);
  ctx.putImageData(new ImageData(data, 240, 160), 0, 0);
};
ws.send(JSON.stringify({type: "buttons", buttons: ["RIGHT"]}));
```

## Buttons

### `GET /buttons`

Currently held buttons (lowercase names).

```
$ curl -s localhost:8420/buttons
{"buttons":["a","right"]}
```

### `POST /buttons`

Replace the held set. Pass an empty list to release everything.

```
$ curl -s -X POST localhost:8420/buttons -H 'content-type: application/json' \
    -d '{"buttons":["a","right"]}'
{"buttons":["a","right"]}
```

Valid names: `a`, `b`, `l`, `r`, `select`, `start`, `up`, `down`, `left`, `right`
(case-insensitive). Unknown names → `400`.

## Memory

The address space is the **GBA bus** — every libretro memory descriptor mGBA
exposes, mapped to its real GBA address. Key regions:

| Region       | Start        | Size    | Notes                       |
| ------------ | ------------ | ------- | --------------------------- |
| EWRAM        | `0x02000000` | 256 KB  | Most game state lives here  |
| IWRAM        | `0x03000000` | 32 KB   | Stack, hot variables        |
| Palette RAM  | `0x05000000` | 1 KB    |                             |
| VRAM         | `0x06000000` | 96 KB   | Tile / bitmap data          |
| OAM          | `0x07000000` | 1 KB    | Sprite attribute table      |
| I/O          | `0x04000000` | 1 KB    | Hardware registers          |
| ROM          | `0x08000000` | up to 32 MB | Read-only (write returns 400) |
| Cartridge SRAM | `0x0E000000` | 128 KB | Save file region            |

### `GET /memory?addr=…&len=…&fmt=hex|base64`

```
$ curl -s 'localhost:8420/memory?addr=33554432&len=4'
{"addr":33554432,"len":4,"data":"deadbeef"}
```

Max read length is 65536 bytes per request.

### `POST /memory`

Write raw bytes (as hex). `width` is informational — it's used to validate the
hex payload length but bytes are written in order regardless.

```
$ curl -s -X POST localhost:8420/memory -H 'content-type: application/json' \
    -d '{"addr": 33554432, "data": "deadbeef", "width": 4}'
{"addr":33554432,"written":4}
```

ROM regions reject writes (`400` with "is in a CONST region").

## Cheats

The libretro-database GBA cheat catalog ships in the wheel; ~6700 named
codes across 512 games. Slugs are URL-safe lowercase-kebab versions of the
cheat names (e.g. `Max Money` → `max-money`).

### `GET /cheats`

```
$ curl -s localhost:8420/cheats | jq '.catalog[0]'
{
  "slug": "1-hit-kill",
  "name": "1-Hit Kill",
  "code": "...",
  "active": false
}
```

### `GET /cheats/active`

Just the currently-active subset.

### `POST /cheats/<slug>/enable`

```
$ curl -s -X POST localhost:8420/cheats/max-money/enable
{"slug":"max-money","name":"Max Money","active":true}
```

### `POST /cheats/<slug>/disable`

```
$ curl -s -X POST localhost:8420/cheats/max-money/disable
{"slug":"max-money","name":"Max Money","active":false}
```

### `POST /cheats/custom`

Inject an ad-hoc code not in the catalog. No validation — crashing the
emulator with a bad code is your problem.

```
$ curl -s -X POST localhost:8420/cheats/custom \
    -H 'content-type: application/json' \
    -d '{"name": "My Hack", "code": "DEADBEEF+0001"}'
{"slug":"my-hack","name":"My Hack","code":"DEADBEEF+0001","active":true}
```

### `DELETE /cheats`

Clear all active cheats.

## Atomic actions

### `POST /action`

Run a sequence of (set buttons, advance frames, screenshot, read
memory) as one atomic operation. The runtime lock is held for the
entire action, so the SDL play loop blocks for the duration — no
real-time slop interleaves between your "press" and "screenshot."

Each step is a dict with any combination of these keys, applied in
order within the step:

- `hold`: list of button names to hold during the next frames
- `release`: `true` to release all buttons (same as `hold: []`)
- `frames`: advance N frames (capped at 3600)
- `screenshot`: `true` to capture the current framebuffer as a PNG
- `read_memory`: list of `{addr, len}` to read

```bash
curl -X POST localhost:8420/action -H 'content-type: application/json' -d '{
  "steps": [
    {"hold": ["down"], "frames": 48},
    {"release": true, "frames": 8},
    {
      "screenshot": true,
      "read_memory": [
        {"addr": "0x020240ac", "len": 1},
        {"addr": "0x02023892", "len": 1}
      ]
    }
  ]
}'
```

Response:

```json
{
  "frames_advanced": 56,
  "frame_count_before": 199847,
  "frame_count": 199903,
  "sdl_frames_inserted": 0,
  "screenshots": ["iVBORw0KGgo..."],
  "memory_reads": [
    {"addr": "0x20240ac", "len": 1, "hex": "10", "u8": 16},
    {"addr": "0x2023892", "len": 1, "hex": "06", "u8": 6}
  ]
}
```

`sdl_frames_inserted: 0` confirms atomicity. Screenshots are base64
PNG; multiple `screenshot: true` steps in one action append in order.

## State tracker

### `POST /capture_state`

Equivalent of the in-game `Ctrl+F` hotkey: records a 30-frame
sparse-filtered memory capture and saves it with your labels. Holds
the runtime lock during the 30-frame window so the snapshot is
internally consistent.

```bash
curl -X POST localhost:8420/capture_state -H 'content-type: application/json' -d '{
  "labels": {"scene": "overworld", "hp": 22, "level": 6},
  "n_frames": 30
}'
```

Response:

```json
{
  "path": "/home/you/.gbax/states/<sha1>/captures/2026-06-10T14-21-40.dump",
  "stable_bytes": 291421,
  "n_frames": 30,
  "labels": {"scene": "overworld", "hp": 22, "level": 6},
  "captured_at": "2026-06-10T14:21:40.690691+00:00"
}
```

Run `gbax state compile <rom>` offline to merge new captures into
the compiled inference. See [state-tracker.md](state-tracker.md).

## Plugins

### `GET /plugins`

Lists active plugins and the routes they expose.

```json
{
  "plugins": [
    {
      "name": "emerald_party",
      "path": "/path/to/gbax/plugins/emerald_party.py",
      "routes": [
        {"path": "/plugins/emerald_party/party", "methods": ["GET"]},
        {"path": "/plugins/emerald_party/slot/{idx}", "methods": ["GET"]}
      ]
    }
  ]
}
```

### `/plugins/<name>/<route>`

Each plugin's `@p.route()`-decorated handlers get mounted at
`/plugins/<name>/<route>`. Method, path params, and return shape are
the plugin's call. See [plugins.md](plugins.md) for how to register
routes; see [cookbook/emerald_party.md](cookbook/emerald_party.md) for
a worked example.

Like `/action`, plugin routes are invoked while holding the runtime
lock — the handler sees a consistent runtime snapshot.

## Coming soon

- `GET/POST /savestate/<slot>` — slot dump/load over HTTP
- `GET /state` — computed read of every tag in the compiled state map

See the project README's roadmap.
