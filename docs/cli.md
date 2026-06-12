# CLI reference

`gbax --help` lists every command. This page covers what each one does in
practice.

## `gbax search <query>`

Search the bundled No-Intro index for ROMs matching `<query>`. Fuzzy match —
every whitespace-separated token must appear (case-insensitive) in the
filename.

```
$ gbax search "metroid"
    1. Metroid - Zero Mission (USA).zip  (4.0 MB)
    2. Metroid Fusion (USA, Australia).zip  (5.5 MB)
    …
```

Flags:
- `--refresh` — force-fetch the latest metadata from archive.org instead of
  using the bundled snapshot. Rare; the snapshot is frozen.

## `gbax download <query>`

Fuzzy-match against the index, pick the best result (preferring USA/World >
Europe > the rest), download the ZIP, extract the inner `.gba`, save to
`~/.gbax/roms/`.

```
$ gbax download "pokemon emerald"
match: Pokemon - Emerald Version (USA, Europe).zip
  size: 6.7 MB
  downloading… 100%  (6.7/6.7 MB)
saved: /home/<you>/.gbax/roms/Pokemon - Emerald Version (USA, Europe).gba
```

Flags:
- `--region USA|Europe|Japan|World` — override the auto-pick.
- `--dest <dir>` — save somewhere other than `~/.gbax/roms/`.
- `--refresh` — same as `search --refresh`.

## `gbax browse [<query>]`

Interactive ROM browser — search-as-you-type, ↑/↓ to navigate, Enter
to download. Pure-TUI complement to `search` + `download`; those
stay agent-friendly, this one is for humans.

Empty search box shows a curated list of ~100 famous GBA hits so
you land on something recognizable instead of "007 — Everything or
Nothing" alphabetical. Any keystroke replaces that with live fuzzy
matches against the full 3,555-entry index (capped at the top 100).

```
$ gbax browse zelda

┌─ gbax browse ──────────────────────────────────────────┐
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
- type — live filter (same fuzzy semantics as `gbax search`)
- `↑` / `↓` — navigate the result list
- `PgUp` / `PgDn` — jump 10 rows
- `Enter` — download the highlighted entry
- `Esc` — clear the search box; press again to quit
- `Ctrl+Q` / `Ctrl+C` — quit

Flags:
- `<query>` (positional, optional) — pre-fills the search input so
  `gbax browse zelda` opens already filtered.
- `--refresh` — same as `search --refresh`.

Use `gbax browse` when you don't remember the exact No-Intro name
or when several regional variants exist and you want to eyeball the
list. For scripts and agents, prefer `gbax search` (machine-readable
output) and `gbax download` (one-shot, no terminal).

## `gbax list-roms`

Show ROMs in `~/.gbax/roms/` with size and SHA-1 prefix.

```
$ gbax list-roms
  Pokemon - Emerald Version (USA, Europe).gba  (16.0 MB)  sha1:f3ae088181
```

## `gbax play <rom>`

Boot the ROM in a SDL window with keyboard input and audio.

`<rom>` is either a path to a `.gba` file or a fuzzy query against the local
library — `gbax play emerald` resolves to
`~/.gbax/roms/Pokemon - Emerald Version (USA, Europe).gba`.

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
| Screenshot   | `F12` — saves to `~/.gbax/screenshots/` |
| Toggle cheat | `F1` … `F9` — toggle the Nth active cheat |

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
| `--renderer={sdl,wgpu}` | `sdl` | renderer backend (`wgpu` needs `gbax[gpu]`) |
| `--shader NAME` | `linear` | initial shader (linear/nearest/crt-lottes) |
| `--user-shader PATH` | none | register a custom WGSL fragment shader |
| `--cheats SLUGS` | none | comma-separated cheat slugs to enable at boot |
| `--core PATH` | bundled | override the libretro core .so |


Save state slots are written immediately to
`~/.gbax/saves/<rom-sha1>/slot-N.state` and hydrate automatically on next
boot of the same ROM.

Flags:
- `--scale N` — window upscale factor. Default 3 (720×480).
- `--core <path>` — path to a libretro core `.so`. Default looks at
  `GBAX_CORE_PATH` env, then `tests/cores/mgba_libretro.so` for in-repo use.
- `--cheats slug1,slug2,…` — enable cheats at boot (slugs from `gbax cheats <rom>`).

## `gbax cheats <rom>`

List the catalogued cheats (libretro-database) for the given ROM, with their
slugs (for use with `--cheats` and the API).

```
$ gbax cheats emerald | head -3
  1-hit-kill                           1-Hit Kill
  max-money                            Max Money
  walk-through-walls-l-r               Walk Through Walls [Press L+R]
```

## `gbax pin <rom> <key> <slug>` / `gbax unpin` / `gbax pins`

Bind a cheat to an F-key for a specific ROM. Persists to
`~/.gbax/pins/<rom-sha1>.json` and applies in `gbax play` automatically on
the next boot.

```
$ gbax pin emerald F1 max-money
pinned F1 → max-money  (/home/<you>/.gbax/pins/f3ae08...json)

$ gbax pins emerald
  F1  →  max-money

$ gbax unpin emerald F1
unpinned F1
```

In `play`, pinned F-keys toggle the specific cheat (autoloading it from the
catalog if needed). Unpinned F-keys fall back to "toggle the Nth currently
active cheat" — handy if you just `--cheats foo,bar` without setting pins.

## `gbax serve <rom>`

Same boot, but no window. Exposes a FastAPI controller API on
`127.0.0.1:8420`. Default mode is `step` — the emulator is paused until a
controller posts `/step?frames=N`.

```
$ gbax serve emerald
gbax serving Pokemon - Emerald Version (USA, Europe).gba on http://127.0.0.1:8420
  mode=step  rom_sha1=f3ae088181bf583e55daf962a92bb46f4f1d07b7
  endpoints: /mode /step /speed /frame /buttons /memory /frame_count
```

Flags:
- `--host`, `--port` — defaults `127.0.0.1:8420`.
- `--free-run` — start in free-run mode (60 fps wall-clock) instead of step.
- `--core <path>` — same as `play`.

See [`api.md`](api.md) for the full endpoint surface.

## `gbax version`

Prints the package version.

## `gbax scenario create / list / validate`

See [`automation.md`](automation.md).

## `gbax train`

```
gbax train --rom <rom> --scenario <name|path> --player <cmd> [--output dir/]
```

Single-run StepDriver — emulator waits for the player on each frame, no
wall-clock deadline. Prints the result to stdout; writes `result.json`
if `--output` is given.

## `gbax tournament`

```
gbax tournament --rom <rom> --scenario <name|path> --player <cmd> --player <cmd> [...]
                [--lag-forfeit N] [--slack-ms N] [--output dir/] [--show] [--record]
```

Sequential 60 fps real-time bracket — each player faces the scenario in
turn. Prints a leaderboard at the end; writes `results.json` if
`--output` is given.

`--show` and `--record` are reserved for follow-up slices (SDL window
during tournament, deterministic input recording).
