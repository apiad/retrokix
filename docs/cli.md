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
| Fast-forward | `Tab` (hold) — 8×                  |
| Screenshot   | `F12` — saves to `~/.gbax/screenshots/` |
| Toggle cheat | `F1` … `F9` — toggle the Nth active cheat |

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
