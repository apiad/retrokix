# HTTP API reference

`gbax serve <rom>` exposes the running emulator as a FastAPI server, by
default at `http://127.0.0.1:8420`. The endpoints are deliberately small and
direct — `gbax` is a substrate; the controllers are the interesting part.

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

## Coming soon

- `GET/POST /savestate/<slot>` — slot dump/load over HTTP
- `GET /state`, `POST /actions/<name>` — per-game plugin layer (Pokémon Emerald first)

See the project README's roadmap.
