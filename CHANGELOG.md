# Changelog

All notable changes to this project are documented here. Format: Keep a Changelog.

## [Unreleased]

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
