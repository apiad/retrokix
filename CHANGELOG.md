# Changelog

All notable changes to this project are documented here. Format: Keep a Changelog.

## [Unreleased]

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
