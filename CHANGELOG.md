# Changelog

All notable changes to this project are documented here. Format: Keep a Changelog.

## [Unreleased]

## [v1.3.2] - 2026-06-19

### Features
- (savestate): PNG thumbnail sidecar next to every save. Each `.state`
  (slot, running, persist) writes a sibling `.png` from the current
  framebuffer. `/savestate/list` exposes a `thumb` URL per entry; new
  `GET /savestate/thumb?slot=N|running=<name>` serves the image. The
  web saves panel now renders the thumbnail next to each save so
  loading is a visual pick. Best-effort: a thumb failure never breaks
  the save itself.
- (art): per-ROM box / snap / title art fetched from
  libretro-thumbnails. New `retrokix.art` module caches PNGs under
  `~/.retrokix/art/<console>/<title>/`. Auto-fetched in the background
  on every successful ROM download (never blocks or breaks the
  download). New `retrokix art [--console X] [--force]` CLI backfills
  ROMs already on disk. New `GET /art?path=<rom>&kind=snap|boxart|title`
  in the hub; library tiles render the snap (with snap → boxart → title
  fallback) when available. Each `ConsoleInfo` now carries a
  `libretro_thumbnails_repo` field.

### Data
- (fame): completed Wikipedia-pageviews fame for Game Boy + Game Boy
  Color — the last two consoles missing from the bundled snapshot. GB:
  1427/1427 catalog groups, 388 articles resolved (Tetris, Pac-Man,
  Street Fighter II, Zelda Link's Awakening, Lemmings at the top).
  GBC: 1425/1425, 380 resolved (GTA, DKC, GTA2, Perfect Dark, Pokémon
  Crystal at the top). All five consoles now ship with 100% catalog
  coverage in `wikipedia_fame.json`.

## [v1.3.1] - 2026-06-17

### Fixes
- (library): accept either `.gb` or `.gbc` inside any GB-family archive.
  Pokemon Yellow lives in the No-Intro_GBC mirror (CGB+SGB enhanced) but
  the packed binary is `.gb` because Yellow also runs on the original
  Game Boy. The extract step previously filtered on the entry's console
  extension only and rejected the archive with "no member with extension
  in ('.gbc',) found inside …". Regression covered in
  `tests/test_library_extract.py`.

## [v1.3.0] - 2026-06-17

Game Boy + Game Boy Color as 4th and 5th consoles. The bundled mGBA
core (`valid_extensions = "gba|gb|gbc|sgb"`) already plays both, so
the wiring was extending `CONSOLES`, teaching the downloader about
`.7z` archives (No-Intro's GB/GBC mirror ships per-game .7z, not the
.zip the other consoles use), and adding the two new sections to the
hub. Bundled catalog jumps from **14,166** ROM variants to **~17,993**
across five consoles.

### Features
- (consoles): GB + GBC via the bundled mGBA core. 1,896 GB + 1,931
  GBC titles, fame-rankable and downloadable from archive.org's
  `No-Intro_GB` / `No-Intro_GBC` mirrors.
- (library): `.7z` archive extraction via `py7zr` (new pure-Python
  dep, ~200 KB). `_extract_first_rom` handles both `.zip` and `.7z`
  shapes; raw ROM downloads still work as before.
- (cheats): GB + GBC bundles compiled from libretro-database — 11,770
  GB cheats across 1,087 ROMs, 7,373 GBC cheats across 786 ROMs.
- (hub): GB + GBC sections appear in the landing grid with their own
  console chips. Search reaches every new title; download → play →
  reaper all work generically.

### Pending
- (data/fame): Wikipedia 12-month pageviews for GB + GBC titles are
  still computing at release time (~3 hr for ~2,800 title groups).
  Until that lands as a patch commit, GB/GBC titles render with 0
  stars and sort alphabetically within their section. Existing
  GBA/NES/SNES fame data is unaffected.

## [v1.2.0] - 2026-06-17

Stream QoS — the browser stays in sync with the runtime even on a
slow link. The `/stream/ws` send loop now holds at most one
`send_bytes` in flight per connection: if a tick fires while the
previous send is still pending, the frame is dropped entirely
(no sample, no encode). When the send completes, the next tick
reads the **latest** framebuffer, never a queued stale one. For
`format=jpeg`, an EWMA of `send_dur / interval` drives quality
adaptively between `quality_floor` (new, default 30) and `quality`
(now the ceiling).

### Features
- (stream): drop-old-frames send loop — single in-flight send per
  WS, dropped tick when busy. Clients never see backlogged stale
  frames.
- (stream): adaptive JPEG quality between configured floor and
  ceiling via send-duration EWMA. Quality steps down 5 above an
  80 % interval-utilisation ratio, recovers below 40 %.
- (stream): new query param `quality_floor` (default 30) on
  `WS /stream/ws`. `quality` is now the ceiling.
- (api): `/healthz` reports `stream_qos` = `{sent, dropped, quality,
  ratio_ewma, last_send_ms}` for any in-flight stream WS — useful
  for the hub reaper and external observers.

### Other
- (lint): drop unused `GBA_{WIDTH,HEIGHT}` imports from
  `render/sdl.py`. Whole-tree `ruff check src/ tests/` is now clean.
- docs/api.md `WS /stream/ws` section documents the new
  `quality_floor` param and the QoS callout.

## [v1.1.0] - 2026-06-16

The game-hub release. `retrokix serve` is now a self-served library
browser instead of a single-game API: open `localhost:8420`, see a
fame-ranked grid of every owned ROM plus the top 24 unowned per
console, type to search across all 14,000+ bundled titles, click to
play or download-then-play in a new tab. Each launched game runs as
its own subprocess (`retrokix play --no-sdl`) on a kernel-allocated
port, isolated from the hub. An idle reaper cleans up children with
no active viewers after 60 seconds. Same visual language as `/stream`.

### Features
- (hub): `retrokix serve` boots a multi-game hub — landing page,
  game grid, per-game tab subprocess fan-out, idle reaper. New
  modules under `retrokix/hub/`.
- (hub): full-library search across the entire No-Intro index
  (~8,700 distinct titles / 14,000+ variants) — debounced 140 ms,
  pre-rendered HTML fragment from `/api/search.html`, owned-first.
- (hub): download & play for unowned ROMs via Server-Sent Events
  progress stream; auto-launch on completion.
- (hub): idle reaper polls each child's `/healthz` every 30 s,
  SIGTERMs children with zero WS viewers for 60 s past a 20 s grace.
- (play): `--open-browser` / `--no-open-browser` flag on `play
  --no-sdl` (default: open). The hub spawns children with
  `--no-open-browser` so each tab doesn't pop its own window.
- (api): `/healthz` endpoint on every play app, reporting live
  WebSocket-viewer count + uptime.

### Breaking changes

- `retrokix serve <rom>` no longer exists. The old per-game API
  server duplicated `retrokix play --no-sdl` with worse defaults
  and was scrapped. If you relied on it, use
  `retrokix play <rom> --no-sdl --no-open-browser` — same FastAPI
  app, browser-tab-as-console.

### Other

- README: dedicated "Game hub" section, architecture diagram
  updated to show hub → child subprocess fan-out, status bumped
  Alpha → Stable.
- docs/cli.md: full rewrite of the `serve` section.

## [v1.0.0] - 2026-06-16

First stable release. The architecture has settled: libretro cffi binding,
single `EmulatorRuntime`, SDL renderer + FastAPI surface, multi-console
(GBA + NES + SNES) with per-console framebuffer sizing. Rename from `gbax`
landed; browser, landing showcase, and downloader are in shape.

### Features
- (landing): mix top 4 GBA + 3 NES + 3 SNES in rotating showcase
- (browse): Enter plays if owned, else downloads + plays — with progress bar

### Fixes
- (browse): replace ProgressBar widget with text bar in status line
- (browse): progress bar wasn't appearing — CSS class collision
- (runtime): size framebuffer + SDL window per-console (was hardcoded GBA)
- (build): patch FCEUmm MAX_CORE_OPTIONS to 64 (upstream overflow)
- (sdl): initialize `app = None` before the --listen branch

### Other
- (ux/browse): visible "launching" confirmation on owned-ROM Enter
- (data/landing): refresh top-100 ticker with SNES titles
- (data/fame): extend snapshot with SNES groups
