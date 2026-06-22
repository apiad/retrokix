# CLI reference

`retrokix --help` lists every command. This page covers what each one does in
practice.

## `retrokix search <query>`

Search the bundled No-Intro index for ROMs matching `<query>`. Fuzzy match —
every whitespace-separated token must appear (case-insensitive) in the
filename.

```
$ retrokix search "metroid"
    1. Metroid - Zero Mission (USA).zip  (4.0 MB)
    2. Metroid Fusion (USA, Australia).zip  (5.5 MB)
    …
```

Flags:
- `--refresh` — force-fetch the latest metadata from archive.org instead of
  using the bundled snapshot. Rare; the snapshot is frozen.

## `retrokix download <query>`

Fuzzy-match against the index, pick the best result (preferring USA/World >
Europe > the rest), download the ZIP, extract the inner `.gba`, save to
`~/.retrokix/roms/`.

```
$ retrokix download "pokemon emerald"
match: Pokemon - Emerald Version (USA, Europe).zip
  size: 6.7 MB
  downloading… 100%  (6.7/6.7 MB)
saved: /home/<you>/.retrokix/roms/Pokemon - Emerald Version (USA, Europe).gba
```

Flags:
- `--region USA|Europe|Japan|World` — override the auto-pick.
- `--dest <dir>` — save somewhere other than `~/.retrokix/roms/`.
- `--refresh` — same as `search --refresh`.

## `retrokix browse [<query>]`

Interactive ROM browser — search-as-you-type, ↑/↓ to navigate, Enter
to download. Pure-TUI complement to `search` + `download`; those
stay agent-friendly, this one is for humans.

Empty search box shows a curated list of ~100 famous GBA hits so
you land on something recognizable instead of "007 — Everything or
Nothing" alphabetical. Any keystroke replaces that with live fuzzy
matches against the full 3,555-entry index (capped at the top 100).

ROMs already in `~/.retrokix/roms/` show a green `●` marker on the
left so you can tell at a glance what's downloaded. The marker
updates immediately after a download finishes.

Regional/version variants of the same title collapse into one row
with a `(+N)` badge for the extra count. Enter on a single-variant
row downloads it directly; Enter on a multi-variant row opens a
modal listing every variant (USA/World first, then Europe, then
Japan/other) where Enter picks one and Esc backs out.

```
$ retrokix browse zelda

┌─ retrokix browse ──────────────────────────────────────────┐
│ search ROMs — type any tokens, e.g. 'zelda minish'     │
│ > zelda                                                │
├────────────────────────────────────────────────────────┤
│ ▌ Legend of Zelda, The - The Minish Cap (USA)   8.0 MB │
│   Legend of Zelda, The - The Minish Cap (Europe) 8.0 MB │
│   Legend of Zelda, The - A Link to the Past Four … MB │
│   …                                                    │
├────────────────────────────────────────────────────────┤
│ 12 matches · total 92.4 MB                             │
└────────────────────────────────────────────────────────┘
  enter download · esc clear/quit · ctrl+q quit
```

Keymap:
- type — live filter (same fuzzy semantics as `retrokix search`)
- `↑` / `↓` — navigate the result list
- `PgUp` / `PgDn` — jump 10 rows
- `Enter` — download the highlighted entry
- `Esc` — clear the search box; press again to quit
- `Ctrl+Q` / `Ctrl+C` — quit

Flags:
- `<query>` (positional, optional) — pre-fills the search input so
  `retrokix browse zelda` opens already filtered.
- `--refresh` — same as `search --refresh`.

Use `retrokix browse` when you don't remember the exact No-Intro name
or when several regional variants exist and you want to eyeball the
list. For scripts and agents, prefer `retrokix search` (machine-readable
output) and `retrokix download` (one-shot, no terminal).

## `retrokix list-roms`

Show ROMs in `~/.retrokix/roms/` with size and SHA-1 prefix.

```
$ retrokix list-roms
  Pokemon - Emerald Version (USA, Europe).gba  (16.0 MB)  sha1:f3ae088181
```

## `retrokix play <rom>`

Boot the ROM in a SDL window with keyboard input and audio.

`<rom>` is either a path to a `.gba` file or a fuzzy query against the local
library — `retrokix play emerald` resolves to
`~/.retrokix/roms/Pokemon - Emerald Version (USA, Europe).gba`.

### Keymap

| Action       | Key                                |
| ------------ | ---------------------------------- |
| D-pad        | Arrow keys                         |
| A            | `X`                                |
| B            | `Z`                                |
| L            | `A`                                |
| R            | `S`                                |
| Start        | `Enter`                            |
| Select       | `Right-Shift`                      |
| Save slot N  | `Ctrl+1` … `Ctrl+9`                |
| Load slot N  | `Shift+1` … `Shift+9`              |
| Fast-forward | `Left-Shift` (hold) — 8×           |
| Macro record | `Ctrl+R` — toggle (see macros doc) |
| State capture | `Ctrl+F` — labeled state snapshot |
| Filter cycle | `F10` — cycle upscale shader       |
| Fullscreen   | `F11` — toggle borderless desktop  |
| Screenshot   | `F12` — saves to `~/.retrokix/screenshots/` |
| Toggle cheat | `F1` … `F9` — toggle the Nth active cheat |
| Save slot    | `Ctrl+1` … `Ctrl+9` — write to numbered slot |
| Load slot    | `Shift+1` … `Shift+9` — load from numbered slot |
| Running save | `Ctrl+S` — append a new timestamped save to this ROM's running stream (never overwrites). Lives in `~/.retrokix/saves/<sha1>/running/`. |
| Load latest  | `Ctrl+L` — load the newest running save for this ROM. |

### Gamepad

Plug in a USB or Bluetooth controller and it Just Works — SDL2's
GameController DB recognises most XInput, DualShock/DualSense,
8BitDo, Steam Controller, and generic clone pads. Multiple pads
combine via set-union (couch co-op for free). Hot-plug supported.

| GBA | Pad |
| --- | --- |
| A | A (south face button) |
| B | B (east face button) |
| L | Left shoulder (L1/LB) |
| R | Right shoulder (R1/RB) |
| START | Start |
| SELECT | Back / Select / Share |
| D-pad | D-pad or left analog stick (25% deadzone) |
| Fast-forward | Left trigger (LT/L2) — held |

X / Y face buttons, right stick, right trigger, and guide are
intentionally unbound — reserved for plugin hotkeys via the
`on_key` decorator with synthetic slot names: `PAD_X`, `PAD_Y`,
`PAD_L1`, `PAD_R1`, `PAD_START`, `PAD_SELECT`, `PAD_DPAD_UP`, etc.

### Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--scale N` | `3` | window scale factor (windowed mode only) |
| `--fullscreen`, `-f` | off | start in borderless-desktop fullscreen |
| `--listen` | off | run the HTTP API alongside the SDL window |
| `--listen-host` | `127.0.0.1` | HTTP bind host (implies `--listen`) |
| `--listen-port` | `8420` | HTTP bind port (implies `--listen`) |
| `--watch-state` | off | live Rich panel of tagged state values |
| `--plugin PATH` | none | load a Python plugin (file path OR module name) |
| `--renderer={sdl,wgpu}` | `sdl` | renderer backend (`wgpu` needs `retrokix[gpu]`) |
| `--shader NAME` | `linear` | initial shader (linear/nearest/crt-lottes) |
| `--user-shader PATH` | none | register a custom WGSL fragment shader |
| `--cheats SLUGS` | none | comma-separated cheat slugs to enable at boot |
| `--core PATH` | bundled | override the libretro core .so |
| `--load PATH` | none | load this save state file at boot (after the ROM is mounted) |
| `--headless` | off | skip the SDL window — runs headless, auto-opens `/stream?mode=controller` |
| `--couch-room CODE` | `default` | couch room code (`retrokix couch room-code` to mint one) |


Save state slots are written immediately to
`~/.retrokix/saves/<rom-sha1>/slot-N.state` and hydrate automatically on next
boot of the same ROM.

`Ctrl+S` saves to a separate **running stream** at
`~/.retrokix/saves/<rom-sha1>/running/running-<utc>.state` — each press
appends a new file, nothing is ever overwritten. `Ctrl+L` always
reloads the newest one for the current ROM. Use `--load <path>` to
boot from any specific state file (running save, slot, or hand-rolled).

Flags:
- `--scale N` — window upscale factor. Default 3 (720×480).
- `--core <path>` — path to a libretro core `.so`. Default looks at
  `RETROKIX_CORE_PATH` env, then `tests/cores/mgba_libretro.so` for in-repo use.
- `--cheats slug1,slug2,…` — enable cheats at boot (slugs from `retrokix cheats <rom>`).

## `retrokix cheats <rom>`

List the catalogued cheats (libretro-database) for the given ROM, with their
slugs (for use with `--cheats` and the API).

```
$ retrokix cheats emerald | head -3
  1-hit-kill                           1-Hit Kill
  max-money                            Max Money
  walk-through-walls-l-r               Walk Through Walls [Press L+R]
```

## `retrokix pin <rom> <key> <slug>` / `retrokix unpin` / `retrokix pins`

Bind a cheat to an F-key for a specific ROM. Persists to
`~/.retrokix/pins/<rom-sha1>.json` and applies in `retrokix play` automatically on
the next boot.

```
$ retrokix pin emerald F1 max-money
pinned F1 → max-money  (/home/<you>/.retrokix/pins/f3ae08...json)

$ retrokix pins emerald
  F1  →  max-money

$ retrokix unpin emerald F1
unpinned F1
```

In `play`, pinned F-keys toggle the specific cheat (autoloading it from the
catalog if needed). Unpinned F-keys fall back to "toggle the Nth currently
active cheat" — handy if you just `--cheats foo,bar` without setting pins.

## `retrokix serve`

Boots the **game hub** — a small FastAPI app that serves a fame-ranked
tile grid of your owned library plus the top 24 unowned titles per
console, with full-library search across all 14,000+ bundled No-Intro
titles. Click a tile to launch in a new browser tab.

```
$ retrokix serve
retrokix hub on http://127.0.0.1:8420
  endpoints: /  /api/library  /api/games  /games/launch  /play/{game_id}
```

The hub does NOT host emulator runtimes itself. Each launched game
runs as its own subprocess — essentially `retrokix play --headless` on
a kernel-allocated port — so a libretro core crash kills one tab,
not the hub.

Endpoints:

- `GET /` — landing page (fame-ranked grid + search box).
- `GET /api/library` — JSON: owned ROMs + top-24-per-console showcase.
- `GET /api/games` — JSON: currently spawned child processes.
- `GET /api/search?q=…` — JSON: fame-ranked search across the full library.
- `GET /api/search.html?q=…` — pre-rendered HTML fragment (used by the
  landing's debounced search input).
- `POST /games/launch` — `{rom_path}` → spawns child, returns
  `{game_id, url}`.
- `POST /games/download` — `{rom_name, console}` → starts a download
  job, returns `{job_id, events_url}`.
- `GET /downloads/{job_id}/events` — Server-Sent Events stream with
  `progress` + `ready` (or `failed`) terminal events. On `ready`,
  the payload carries the play URL — one round-trip from the client.
- `GET /play/{game_id}` — 302 redirect to the child's
  `/stream?mode=controller`.

The hub also runs an `IdleReaper` thread: every 30 s it polls each
child's `/healthz` endpoint for the live count of open `/stream` and
`/stream/audio` WebSockets. Children younger than 20 s are skipped
(initial-load grace). Children with zero viewers for at least 60 s
straight get SIGTERMed and removed from the registry.

Flags:

- `--host`, `--port` — defaults `127.0.0.1:8420`.
- `--roms-dir <path>` — override `~/.retrokix/roms/` as the library root.
- `--open-browser` / `--no-open-browser` — auto-open the landing page
  at start (default: open).

### What changed in v1.1

`retrokix serve` used to take a ROM argument and boot a single-game
FastAPI controller — but that mode added nothing over
`retrokix play --headless` (which already boots the same FastAPI app
*and* opens the browser tab). The flag was scrapped in favour of the
hub. If you want the old per-game-API behaviour, use:

```
$ retrokix play <rom> --headless --no-open-browser
```

See [`api.md`](api.md) for the per-child endpoint surface (`/frame`,
`/buttons`, `/memory`, `/step`, `/action`, `/capture_state`,
`/plugins/...`).

## `retrokix version`

Prints the package version.

## `retrokix scenario create / list / validate`

See [`automation.md`](automation.md).

## `retrokix train`

```
retrokix train --rom <rom> --scenario <name|path> --player <cmd> [--output dir/]
```

Single-run StepDriver — emulator waits for the player on each frame, no
wall-clock deadline. Prints the result to stdout; writes `result.json`
if `--output` is given.

## `retrokix tournament`

```
retrokix tournament --rom <rom> --scenario <name|path> --player <cmd> --player <cmd> [...]
                [--lag-forfeit N] [--slack-ms N] [--output dir/] [--show] [--record]
```

Sequential 60 fps real-time bracket — each player faces the scenario in
turn. Prints a leaderboard at the end; writes `results.json` if
`--output` is given.

`--show` and `--record` are reserved for follow-up slices (SDL window
during tournament, deterministic input recording).
