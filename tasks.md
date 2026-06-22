# retrokix — tasks

## In-flight

- [ ] **Wire the play-time TUI into `retrokix play`** — the TUI subsystem (shell, tab API, core tab, Pokédex tab, play-time, status snapshot) is built, tested, and pushed (commits `ac20808`, `a69db15`, `81fcbeb`). Remaining: invert `play_loop` threading (Textual on main, emulator+SDL on a worker), publish the status snapshot each frame, read `app.state.ws_clients` into it, and mount loaded plugins' tabs. Needs a display + interactive terminal to verify — can't be smoke-tested headlessly. Spec: [[2026-06-22-retrokix-tui-shell-and-pokedex-design]]. Smoke after: `retrokix play <emerald> --plugin retrokix.plugins.pokemon.pokedex`.

## Menu — low-cost / high-value

- [ ] **Pokémon Emerald plugin** (slice 6) — scene detection already empirically validated (u32-LE multi-address vote, 29/29). Wire the validated approach into `retrokix.plugins.emerald`. Closes the loop on the 2026-06-10 handoff. ~½ day. Refs: [[2026-06-10-gbax-plugin-design]], handoff report: `vault/+/agent_drafts/handoffs/report-2026-06-10-1254-retrokix-scene-detection.md`.
- [ ] **Screenshot gallery** — reuse the framebuffer→PNG infra from the savestate-thumbnail work. `POST /screenshot` writes to `~/.retrokix/screenshots/<rom_sha1>/<ts>.png`; new `/screenshots` page in the hub renders the gallery. F12 / button in the play UI. ~2–3 hours.
- [ ] **Box art / cover thumbnails in the hub library** — fetch from libretro-thumbnails (or similar public repo) per ROM, cache locally, show on library tiles. Visual upgrade matching the per-save thumbnail polish. ~3–4 hours.
- [ ] **Per-ROM volume** — volume slider in the web UI, persisted alongside speed/fullscreen/scale. Volume infra is new (SDL plays at full vol today); ~2-3 hours.
- [ ] **User scripts** (slice 7, YAML) — declarative hooks for AI/scripted play. ~1 day. Spec: [[2026-06-09-gbax-design]].
- [ ] **Recording/replay** (slice 8) — `recording/{initial.state, inputs.jsonl, divergence.jsonl}` + `retrokix replay`. ~1–2 days. Spec: [[2026-06-09-gbax-design]].

## Parked

- [ ] **Multiplayer / link cable** — research done 2026-06-19. Realistic 1-week feature post a half-day build spike. mGBA's libretro core needs two patches (re-enable threading + export a few SIO/lockstep symbols) before we can attach a lockstep driver from cffi. NES/SNES is a *different* feature (couch multiplayer, one shared emulator + multi-port WS clients) and gets its own design later. Full design: [[2026-06-19-retrokix-multiplayer-design]].

## Done

- [x] **Play-time TUI subsystem + Pokédex tab (slices 1+2)** — 2026-06-22, commits `ac20808` / `a69db15` / `81fcbeb`. New `@p.tab(...)` plugin contribution API; `retrokix.tui` shell (`RetrokixTUI`), core tab (ASCII banner + game/play-time/API status + log pane), play-time accumulator, lock-guarded status snapshot; Pokédex plugin + pure `pokedex_model` (search by name/`#id`/`type:`, full stat/matchup/evolution/moveset detail) over bundled data. 71 tests; ruff+mypy clean; headless screenshots verified. Renamed `play --no-sdl` → `--headless`. Caught/seen overlay and the `play_loop` wiring deferred (see In-flight). Spec: [[2026-06-22-retrokix-tui-shell-and-pokedex-design]].
- [x] **Per-ROM persistent settings** — 2026-06-19, commit `75d0749`. Speed multiplier, fullscreen state, window scale, last-used slot remembered per `rom_sha1` across launches via `~/.retrokix/settings/<sha1>.json` (atomic writes). `retrokix play` falls back to persisted values when `--scale` / `--fullscreen` aren't passed. New `GET/PATCH /settings` API; existing `POST /speed` and SDL F11 also persist now. Volume deferred — no playback-volume infra exists yet.
- [x] **[Handoff 2026-06-10 12:23 — empirically validate scene detection for Pokémon Emerald (pHash + memory patterns)](../../vault/+/agent_drafts/handoffs/handoff-2026-06-10-1223-retrokix-scene-detection-experiments.md)** — done. Report: [report-2026-06-10-1254-retrokix-scene-detection](../../vault/+/agent_drafts/handoffs/report-2026-06-10-1254-retrokix-scene-detection.md). Memory-vote at u32-LE scores 29/29 (100%) across two sessions; pHash 85%. Recommendation: u32-LE multi-address majority vote with overworld-zero (display-buffer) filter as primary; pHash framebuffer-template fallback as secondary; plugin override for game-specific canonical bytes as tertiary.
- [x] **PNG thumbnail sidecar for save states + web load thumbnails** — 2026-06-19, commit `55fdaa2`. Every save (slot/running/persist) writes a PNG of the current framebuffer next to the `.state`; `/savestate/list` exposes a `thumb` URL; new `GET /savestate/thumb` serves it; web saves panel renders thumbnails next to each entry.
