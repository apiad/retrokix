# retrokix — Retro consoles you can drive.

**Bring your keyboard, your gamepad, and your AI. They all work together.**

[![PyPI](https://img.shields.io/pypi/v/retrokix.svg?logo=pypi&logoColor=white)](https://pypi.org/project/retrokix/)
[![Python](https://img.shields.io/pypi/pyversions/retrokix.svg?logo=python&logoColor=white)](https://pypi.org/project/retrokix/)
[![CI](https://github.com/apiad/retrokix/actions/workflows/ci.yml/badge.svg)](https://github.com/apiad/retrokix/actions/workflows/ci.yml)
[![License: MPL-2.0](https://img.shields.io/badge/License-MPL%202.0-1d2d44.svg)](https://www.mozilla.org/MPL/2.0/)
![Platform](https://img.shields.io/badge/Linux-only-555555?logo=linux&logoColor=white)

---

**retrokix is an emulator you can talk to.** It plays Game Boy, Game
Boy Color, Game Boy Advance, NES, and Super Nintendo games in a window
with sound and a keyboard — and in the same session, it exposes the
framebuffer, memory bus, and input as an HTTP API any coding agent can
reach. Use it to speedrun Pokémon Emerald with Claude Code looking over
your shoulder, or to test a neurosymbolic policy against 17,000+
hand-crafted GB + GBC + GBA + NES + SNES environments where the level
designers were genre masters. Same emulator, same session, same API.
Whether you're the player or the algorithm, you're in the loop together.

## Three commands

```
$ pip install retrokix
$ retrokix download "pokemon emerald"
$ retrokix play emerald
```

Pokémon Emerald, in a window, with sound. The wheel ships a prebuilt
`mgba_libretro.so`; no cmake, no apt-get, no `$RETROKIX_CORE_PATH`.

## The game hub

```
$ retrokix serve
retrokix hub on http://127.0.0.1:8420
```

Open the URL: a fame-ranked grid of every owned ROM plus the top 24
unowned titles per console. Click an owned tile → it opens in a new
tab, playing. Click an unowned tile → it downloads from the bundled
archive.org mirror with a live progress bar, then opens in a new tab.
Type in the search box: every keystroke filters across all **17,000+
ROMs** in the bundled No-Intro index. The hub spawns one
`retrokix play --no-sdl` subprocess per launched game on its own
port (libretro core crash kills one tab, not the hub) and reaps
children with no active viewers after 60 seconds idle.

## The cooperative loop

Launch retrokix with both the keyboard surface and the HTTP API:

```
$ retrokix play emerald --listen --plugin retrokix.plugins.emerald_party
retrokix HTTP API listening on http://127.0.0.1:8420
  plugin route: GET /plugins/emerald_party/party
  plugin route: GET /plugins/emerald_party/slot/{idx}
```

Open another terminal — yours, or your coding agent's:

```bash
$ curl -s localhost:8420/plugins/emerald_party/party | jq '.slots[0]'
{ "species": 280, "level": 11, "hp": 33, "max_hp": 33,
  "exp": 853, "friendship": 113 }
```

The plugin decoded Torchic's encrypted party slot for you. Want to
know which menu the player is in right now? Take a screenshot in one
atomic round trip:

```bash
$ curl -s -X POST localhost:8420/action \
    -H 'content-type: application/json' \
    -d '{"steps":[{"screenshot": true}]}' \
  | jq -r '.screenshots[0]' | base64 -d > /tmp/now.png
```

Now you, or the agent, can look at `/tmp/now.png` and decide what to
do. The agent presses a button by sending the next action. The human
can keep playing — both inputs combine via set-union, neither blocks
the other.

That's the loop. The agent watches, thinks, sometimes nudges. You
keep your hand on the keyboard. Together you write the next plugin,
discover the next memory address, build the next algorithm.

## What you get

- **17,000+ ROMs** across GB + GBC + GBA + NES + SNES in a
  fuzzy-searchable bundled No-Intro index, ranked by Wikipedia
  12-month pageviews with a 0–5 star column in `retrokix browse`.
  `retrokix download` pulls from the public archive.org mirror.
- **One HTTP API** exposing the framebuffer, full memory bus, input,
  cheat codes, save states, and an atomic `/action` for multi-step
  agent plans.
- **Plugins** that publish their own endpoints under
  `/plugins/<name>/...`. The agent can write plugins for itself.
- **State tracker** — supervised memory inference. Learn game memory
  by labeling, not by reading per-game wikis.
- **Macros, save states, cheat codes** for the player who just wants
  to play. ~6,700 cheat codes vendored from libretro-database; no
  network at runtime.
- **GPU shaders** (`crt-lottes`, custom WGSL) when you want pretty.
- **Browser stream** — `retrokix play --listen` then open
  `http://localhost:8420/stream` in any browser. Pristine raw RGBA
  frames over WebSocket plus a separate audio WebSocket for live
  PCM. Add `?mode=controller` for an on-screen GBA-bezel with D-pad
  + A/B + L/R + Select/Start + TURBO, dock-layout that flips between
  portrait and landscape. Play from a phone, a laptop, or any window
  in between. Pass `--no-sdl` to skip the SDL window entirely — the
  browser tab becomes the console.
- **Game hub** — `retrokix serve` boots a small FastAPI app that
  serves a fame-ranked tile grid of your owned library plus the top
  24 unowned per console, with full-library search across all
  14,000+ bundled titles. Click to launch (new tab); click to
  download then launch. One subprocess per active game, idle reaper
  cleans up after itself. Same visual language as `/stream`.
- One `pip install`, one MPL-2.0 license, Linux x86_64 today.

## Discovery toolkit

The AI-research / collaboration surface. Each entry links to its own
docs/ page.

- [**HTTP API**](docs/api.md) — `/frame`, `/buttons`, `/memory`,
  `/step`, `/action` (atomic multi-step), `/capture_state` (record
  labeled snapshots), `/stream` + `/stream/ws` (live browser viewer
  with optional on-screen controller), `/plugins/<name>/...`
  (per-plugin namespaces), `/plugins` (active plugin listing).
- [**Plugins**](docs/plugins.md) — Python files that hook the play
  loop AND publish HTTP routes. The bundled `retrokix.plugins.emerald_party`
  is the canonical example: a [cookbook page](docs/cookbook/emerald_party.md)
  walks through how it was built.
- [**State tracker**](docs/state-tracker.md) — capture / compile /
  refine flow. Label what's true (`hp=22, scene=overworld`); retrokix
  intersects labels across captures and infers where each value
  lives.
- **In-process Controller** ([automation.md](docs/automation.md)) —
  the headless-script counterpart to plugins. Same scripting power
  without an HTTP round-trip.

## The play surface

For the human-first reader. Each entry links to its details.

- **Play window** — SDL with sound, keyboard, save states. Hotkeys
  are documented in [docs/cli.md](docs/cli.md). Headlines: `Ctrl+1..9`
  saves a slot, `Shift+1..9` loads, `Left-Shift` is 8× fast-forward,
  `F12` screenshots.
- **Controllers** — plug in any USB or Bluetooth pad (XInput,
  DualShock/DualSense, 8BitDo, Steam Controller, generic clones —
  SDL's GameController DB recognises them all). Multiple pads + the
  keyboard + the HTTP API combine via set-union. Hot-plug works.
  Layout in [docs/cli.md#gamepad](docs/cli.md).
- **Browser play** — `retrokix play <rom> --no-sdl` boots the runtime
  headless and pops a browser tab to a GBA-bezel viewer with
  on-screen controls. Touch / pointer drives the D-pad + A/B + L/R
  + Select/Start + TURBO; keyboard shortcuts mirror the SDL play
  loop's defaults (arrows + X / Z / A / S / Enter); audio streams
  live over WebSocket and plays through an AudioWorklet in the page.
- **Cheats** — `retrokix cheats <rom>` lists; `retrokix pin <rom> F1
  max-money` binds; `F1`-`F9` toggle in-game. Pins persist per ROM.
- **Macros** — record a button sequence with `Ctrl+R`, bind to any
  letter / digit / F-key, replay anywhere in-game.
- **Shaders** — `retrokix play <rom> --renderer=wgpu --shader=crt-lottes`
  via the optional `[gpu]` extra. Full guide in [docs/shaders.md](docs/shaders.md).
- **Save state slots** survive restarts. Per-ROM, in `~/.retrokix/saves/<rom-sha1>/`.

## Architecture

```mermaid
flowchart TB
    subgraph clients[" "]
        direction LR
        kbd([Keyboard])
        http([HTTP client<br/>script · LLM · shell])
        browser([Browser tab])
    end

    subgraph cli["retrokix CLI (Typer)"]
        play["retrokix play"]
        serve["retrokix serve<br/>(hub)"]
        other["search · download · state · macro · pin · …"]
    end

    sdl["SDL renderer<br/>window + audio + input"]
    api["FastAPI server<br/>/frame /buttons /memory /step<br/>/action /capture_state /plugins/…<br/>/stream + /healthz"]
    hub["Hub app<br/>/ landing · /api/search · /api/library<br/>/games/launch · /downloads/{id}/events<br/>+ idle reaper"]
    children["one child play --no-sdl<br/>per active game"]
    rt["EmulatorRuntime<br/>step · framebuffer · memory · save slots<br/>thread-safe via RLock"]
    plugins["Plugins<br/>Python @on_* handlers + @p.route()"]
    lr["LibretroCore<br/>~300 LOC cffi shim"]
    so["mgba_libretro.so · fceumm_libretro.so · snes9x_libretro.so"]

    kbd --> sdl
    http --> api
    browser --> hub
    play --> sdl
    play -.--> api
    serve --> hub
    hub --> children
    children --> api
    sdl --> rt
    api --> rt
    plugins --> rt
    plugins --> api
    rt --> lr
    lr --> so

    classDef ext fill:#eef,stroke:#33a,stroke-width:1px;
    classDef core fill:#fef9c3,stroke:#a16207,stroke-width:1px;
    class kbd,http,browser ext;
    class so core;
```

- `EmulatorRuntime` is thread-safe via an `RLock`. `/action` and
  `/capture_state` hold the lock for their full duration; the SDL
  play loop blocks for the few ms each action takes, then resumes.
- The SDL window, the FastAPI server, and plugin HTTP routes are
  independent clients of the runtime. They don't know about each
  other beyond the lock.
- `LibretroCore` is a ~300-line cffi wrapper around the libretro ABI.
  Swapping in another libretro core (vba-next, gpsp) is mostly a
  one-line config change.

## Install

```
pip install retrokix                # default install
pip install retrokix[gpu]           # adds wgpu renderer + CRT-Lottes
```

One command on Linux x86_64. Other platforms fall back to the sdist
and need `$RETROKIX_CORE_PATH` set. Full coverage in
[docs/installing.md](docs/installing.md).

## Status

- **Stable.** v1.3.0. Works on Linux x86_64. macOS / Windows / ARM
  are PR-welcome.
- **Multi-console.** GBA / GB / GBC via mGBA (the same bundled core
  plays all three), NES via FCEUmm, SNES via snes9x. The runtime
  picks a core from the ROM extension; `retrokix browse` shows a
  per-row console badge and merges every library.
- **MPL-2.0.** Same license as the underlying mGBA core. The bundled
  FCEUmm core is GPLv2 (see `cores/LICENSE.FCEUmm`) and the bundled
  snes9x core is under its own permissive non-commercial terms
  (see `cores/LICENSE.snes9x`).
- **No ROMs bundled.** `retrokix download` pulls from the public No-Intro
  mirror at archive.org. Use it for games you own; respect your
  local laws.

## Roadmap

| Status | Slice |
| ------ | ----- |
| ⏳ | Predicate filters (`@on_state_change("hp", below=20)`) + `ctx.wait` sync API |
| ⏳ | HTTP `/state` — computed read of every tag in the compiled state map |
| ⏳ | `GET/POST /savestate/<slot>` over HTTP |
| ⏳ | xBRZ + multi-pass CRT shaders, shader hot-reload, parameter UI |
| ⏳ | macOS / Windows / aarch64 wheels |
| ⏳ | YAML user scripts — `Ctrl+H` runs a sequence |

Past releases: see [GitHub Releases](https://github.com/apiad/retrokix/releases).

## Credits

- **[mGBA](https://github.com/mgba-emu/mgba)** by endrift — the GBA
  emulator core doing the actual heavy lifting. MPL-2.0.
- **[FCEUmm](https://github.com/libretro/libretro-fceumm)** — the NES
  core we ship for `.nes` ROMs. GPLv2.
- **[No-Intro](https://no-intro.org)** — the canonical ROM-naming and
  SHA-1 reference for both consoles.
- **archive.org** — hosts the No-Intro snapshot we point at by default.
- **[libretro-database](https://github.com/libretro/libretro-database)** —
  the cheat-code corpus we vendor.
