import sys
from pathlib import Path

import typer

app = typer.Typer(help="retrokix — hacker-first GBA emulator", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print version and exit."""
    from retrokix import __version__
    typer.echo(f"retrokix {__version__}")


@app.command()
def search(
    query: str = typer.Argument(..., help="Fuzzy match — all tokens must appear in the ROM name."),
    refresh: bool = typer.Option(False, "--refresh", help="Force-fetch the latest metadata from archive.org (default uses bundled snapshot)."),
) -> None:
    """Search the configured ROM archive (currently archive.org's No-Intro GBA mirror)."""
    from retrokix.library import RomLibrary

    matches = RomLibrary(refresh=refresh).search(query)
    if not matches:
        typer.echo(f"no matches for {query!r}")
        raise typer.Exit(code=1)
    for i, e in enumerate(matches, 1):
        size_mb = e.size / 1_048_576
        typer.echo(f"  {i:3d}. {e.name}  ({size_mb:.1f} MB)")


@app.command()
def download(
    query: str = typer.Argument(..., help="Fuzzy match — all tokens must appear in the ROM name."),
    region: str | None = typer.Option(None, "--region", help="Prefer USA|Europe|Japan|World when multiple match."),
    console: str | None = typer.Option(None, "--console", help="Constrain to one console (gba|nes|…). Use when a query matches games across consoles."),
    roms_dir: Path | None = typer.Option(None, "--dest", help="Where to save the ROM (default ~/.retrokix/roms/)."),
    refresh: bool = typer.Option(False, "--refresh", help="Force-fetch the latest metadata from archive.org."),
) -> None:
    """Download a ROM. Auto-picks the best match within a single console;
    prompts when matches span multiple consoles."""
    from retrokix.library import CONSOLES, RomLibrary

    if console is not None and console not in CONSOLES:
        typer.echo(f"--console {console!r}: choices are {', '.join(sorted(CONSOLES))}", err=True)
        raise typer.Exit(code=1)

    kwargs: dict = {"refresh": refresh}
    if roms_dir is not None:
        kwargs["roms_dir"] = roms_dir
    if console is not None:
        kwargs["console"] = console
    lib = RomLibrary(**kwargs)

    matches = lib.search(query)
    if not matches:
        typer.echo(f"no matches for {query!r}")
        raise typer.Exit(code=1)

    # Cross-console ambiguity → ask which console (unless user already
    # specified via --console). Without a TTY, fail with a hint rather
    # than guess.
    consoles_hit = sorted({m.console for m in matches})
    if len(consoles_hit) > 1:
        if not sys.stdin.isatty():
            typer.echo(
                f"matches span multiple consoles ({', '.join(consoles_hit)}); "
                f"rerun with --console <slug>",
                err=True,
            )
            raise typer.Exit(code=1)
        typer.echo(f"{len(matches)} matches across {len(consoles_hit)} consoles:")
        for i, slug in enumerate(consoles_hit, 1):
            n = sum(1 for m in matches if m.console == slug)
            typer.echo(f"  [{i}] {CONSOLES[slug].label:30s}  {n} match{'es' if n != 1 else ''}")
        try:
            pick = input("pick console number: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise typer.Exit(code=1) from None
        try:
            idx = int(pick)
            if not 1 <= idx <= len(consoles_hit):
                raise ValueError
        except ValueError:
            typer.echo(f"invalid choice {pick!r}", err=True)
            raise typer.Exit(code=1) from None
        chosen_slug = consoles_hit[idx - 1]
        matches = [m for m in matches if m.console == chosen_slug]

    # Within one console: prefer the region the user asked for, else
    # USA, else first match.
    def _score(entry) -> int:
        name = entry.name.lower()
        if region and region.lower() in name:
            return 0
        if "(usa" in name or "(world" in name:
            return 1
        if "(europe" in name:
            return 2
        return 3

    matches.sort(key=_score)
    chosen = matches[0]

    if len(matches) > 1:
        typer.echo(f"{len(matches)} matches; picked: {chosen.name}")
        typer.echo("  (use a more specific query, --region, or --console to override)")
    else:
        typer.echo(f"match: {chosen.name}  [{chosen.console}]")
    typer.echo(f"  size: {chosen.size / 1_048_576:.1f} MB")

    path = lib.download(chosen)
    typer.echo(f"saved: {path}")


@app.command()
def browse(
    query: str = typer.Argument("", help="Optional initial filter — same fuzzy semantics as `retrokix search`."),
    console: str | None = typer.Option(None, "--console", help="Constrain to one console (gba|nes|snes|gb|gbc). Default: every bundled console at once."),
    refresh: bool = typer.Option(False, "--refresh", help="Force-fetch the latest metadata from archive.org."),
) -> None:
    """Interactive ROM browser. Search-as-you-type, arrows to navigate,
    Enter to play (or download then play if you don't own it yet)."""
    import os
    import sys
    from retrokix.browse import run
    from retrokix.library import CONSOLES, RomLibrary

    if console is not None and console not in CONSOLES:
        typer.echo(f"--console {console!r}: choices are {', '.join(sorted(CONSOLES))}", err=True)
        raise typer.Exit(code=1)

    kwargs: dict = {"refresh": refresh}
    if console is not None:
        kwargs["console"] = console
    lib = RomLibrary(**kwargs)
    picked = run(lib=lib, initial_query=query)
    if picked is None:
        raise typer.Exit(code=0)
    # Re-exec into `retrokix play <path>` so the SDL window inherits the
    # terminal cleanly. argv[0] is the current entry-point binary; we
    # invoke it via -m to be robust to console-script paths.
    os.execvp(sys.executable, [sys.executable, "-m", "retrokix", "play", str(picked)])


@app.command()
def cheats(
    rom: str = typer.Argument(..., help="Path to a .gba, or a fuzzy query against ~/.retrokix/roms/."),
) -> None:
    """List cheats catalogued (libretro-database) for the given ROM."""
    from retrokix.cheats import cheats_for_rom
    from retrokix.library import resolve_rom

    try:
        rom_path = resolve_rom(rom)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    catalog = cheats_for_rom(rom_path.name)
    if not catalog:
        typer.echo(f"no cheats catalogued for {rom_path.name}")
        raise typer.Exit(code=1)
    for c in catalog:
        typer.echo(f"  {c.slug():35s}  {c.name}")


def _resolve_rom_sha1(rom: str) -> tuple[Path, str]:
    """Resolve a ROM query to (path, sha1) without booting the emulator."""
    import hashlib

    from retrokix.library import resolve_rom

    try:
        path = resolve_rom(rom)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    return path, hashlib.sha1(path.read_bytes()).hexdigest()


@app.command()
def pin(
    rom: str = typer.Argument(..., help="ROM path or fuzzy query."),
    key: str = typer.Argument(..., help="Hotkey to pin (F1..F9)."),
    slug: str = typer.Argument(..., help="Cheat slug from `retrokix cheats <rom>`."),
) -> None:
    """Pin a cheat to a hotkey for the given ROM. Persists to ~/.retrokix/pins/<sha1>.json."""
    from retrokix import pins as pins_module
    from retrokix.cheats import Cheat, cheats_for_rom

    rom_path, sha1 = _resolve_rom_sha1(rom)
    catalog = cheats_for_rom(rom_path.name)
    if catalog and not any(Cheat(c.name, c.code).slug() == slug for c in catalog):
        typer.echo(f"warning: {slug!r} is not in the catalog for {rom_path.name}", err=True)

    try:
        path = pins_module.set_pin(sha1, key.upper(), slug)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"pinned {key.upper()} → {slug}  ({path})")


@app.command()
def unpin(
    rom: str = typer.Argument(..., help="ROM path or fuzzy query."),
    key: str = typer.Argument(..., help="Hotkey to clear (F1..F9)."),
) -> None:
    """Clear the hotkey pin for the given ROM."""
    from retrokix import pins as pins_module

    _, sha1 = _resolve_rom_sha1(rom)
    try:
        pins_module.unset_pin(sha1, key.upper())
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"unpinned {key.upper()}")


@app.command()
def pins(
    rom: str = typer.Argument(..., help="ROM path or fuzzy query."),
) -> None:
    """List hotkey pins for the given ROM."""
    from retrokix import pins as pins_module

    _, sha1 = _resolve_rom_sha1(rom)
    current = pins_module.load(sha1)
    if not current:
        typer.echo("no pins")
        return
    for key in sorted(current):
        typer.echo(f"  {key}  →  {current[key]}")


macro_app = typer.Typer(help="Manage recorded input macros.")
app.add_typer(macro_app, name="macro")


from retrokix.couch.cli import app as couch_app  # noqa: E402
app.add_typer(couch_app, name="couch")


@app.command()
def macros(
    rom: str = typer.Argument(..., help="ROM path or fuzzy query."),
) -> None:
    """List recorded macros for the given ROM."""
    from retrokix import macros as macros_module

    _, sha1 = _resolve_rom_sha1(rom)
    listed = macros_module.list_for_rom(sha1)
    if not listed:
        typer.echo("(no macros)")
        return
    for m in listed:
        name = m.name or "(unnamed)"
        typer.echo(
            f"  {m.slot}  →  {name}  "
            f"({m.total_frames} frames, recorded {m.recorded_at:%Y-%m-%d %H:%M})"
        )


@macro_app.command("delete")
def macro_delete(
    rom: str = typer.Argument(..., help="ROM path or fuzzy query."),
    slot: str = typer.Argument(..., help="Slot to delete (F1..F9)."),
) -> None:
    """Delete a recorded macro."""
    from retrokix import macros as macros_module

    _, sha1 = _resolve_rom_sha1(rom)
    slot_upper = slot.upper()
    existing = macros_module.load(sha1, slot_upper)
    if existing is None:
        typer.echo(f"no macro at {slot_upper}", err=True)
        raise typer.Exit(code=1)
    macros_module.delete(sha1, slot_upper)
    label = existing.name or "(unnamed)"
    typer.echo(f"deleted {slot_upper} ({label}).")


state_app = typer.Typer(help="Manage labeled memory captures and inferred state.")
app.add_typer(state_app, name="state")


@state_app.command("compile")
def state_compile(
    rom: str = typer.Argument(..., help="ROM path or fuzzy query."),
) -> None:
    """Run supervised address inference over captured snapshots."""
    from retrokix.state.compile import compile_for_rom

    _, sha1 = _resolve_rom_sha1(rom)
    out = compile_for_rom(sha1)
    typer.echo(f"compiled → {out}")


@state_app.command("list")
def state_list(
    rom: str = typer.Argument(..., help="ROM path or fuzzy query."),
) -> None:
    """Show captures + inferred tags for the given ROM."""
    import json as _json
    from retrokix.state.storage import captures_dir_for_rom, compiled_path_for_rom

    _, sha1 = _resolve_rom_sha1(rom)
    cap_dir = captures_dir_for_rom(sha1)
    n_caps = len(list(cap_dir.glob("*.dump"))) if cap_dir.exists() else 0
    typer.echo(f"captures: {n_caps}")
    compiled = compiled_path_for_rom(sha1)
    if not compiled.exists():
        typer.echo("not compiled — run `retrokix state compile <rom>`")
        return
    payload = _json.loads(compiled.read_text())
    tags = payload.get("tags", {})
    if not tags:
        typer.echo("no tags inferred")
        return
    for tag in sorted(tags):
        info = tags[tag]
        if info["kind"] == "numeric":
            typer.echo(f"  {tag}  {info['kind']:<11}  {info['addr']}  ({info['width']})")
        else:
            n_vals = len(info.get("values", {}))
            typer.echo(f"  {tag}  {info['kind']:<11}  {info['addr']}  ({n_vals} values)")


@state_app.command("ambiguous")
def state_ambiguous(
    rom: str = typer.Argument(..., help="ROM path or fuzzy query."),
) -> None:
    """Show tags where >1 address matched — add captures to disambiguate."""
    import json as _json
    from retrokix.state.storage import compiled_path_for_rom

    _, sha1 = _resolve_rom_sha1(rom)
    compiled = compiled_path_for_rom(sha1)
    if not compiled.exists():
        typer.echo("not compiled — run `retrokix state compile <rom>`", err=True)
        raise typer.Exit(code=1)
    payload = _json.loads(compiled.read_text())
    ambig = payload.get("ambiguous", {})
    if not ambig:
        typer.echo("(no ambiguous tags)")
        return
    for tag in sorted(ambig):
        typer.echo(f"  {tag}:")
        for cand in ambig[tag]:
            typer.echo(f"    {cand['addr']} ({cand['width']})")


@app.command()
def list_roms() -> None:
    """List ROMs in ~/.retrokix/roms/."""
    from retrokix.library import list_local_roms, sha1

    roms = list_local_roms()
    if not roms:
        typer.echo("no ROMs in ~/.retrokix/roms/")
        return
    for p in roms:
        typer.echo(f"  {p.name}  ({p.stat().st_size / 1_048_576:.1f} MB)  sha1:{sha1(p)[:10]}")


@app.command()
def art(
    console: str | None = typer.Option(None, "--console", help="Limit to one console (gba|nes|…). Default: all owned consoles."),
    force: bool = typer.Option(False, "--force", help="Re-fetch even if cached art is already on disk."),
) -> None:
    """Backfill libretro-thumbnails art (snap / boxart / title) for every
    ROM in ~/.retrokix/roms/. Safe to re-run — only fetches what's missing
    unless --force is passed. Future downloads grab their own art
    automatically; this command is for ROMs already on disk."""
    from retrokix.art import KINDS, fetch_art_for_rom
    from retrokix.library import CONSOLES, console_for_path, list_local_roms

    if console is not None and console not in CONSOLES:
        typer.echo(f"--console {console!r}: choices are {', '.join(sorted(CONSOLES))}", err=True)
        raise typer.Exit(code=1)

    roms = list_local_roms()
    if console is not None:
        roms = [p for p in roms if console_for_path(p) == console]
    if not roms:
        typer.echo("no local ROMs match")
        return

    totals: dict[str, int] = {"hit": 0, "cached": 0, "missing": 0, "error": 0, "unknown_console": 0}
    for i, p in enumerate(roms, 1):
        result = fetch_art_for_rom(p, force=force)
        labels = " ".join(f"{k}:{result.get(k, '?')}" for k in KINDS)
        typer.echo(f"  [{i}/{len(roms)}] {p.name:<55.55s}  {labels}")
        for status in result.values():
            totals[status] = totals.get(status, 0) + 1

    summary = ", ".join(f"{k}={v}" for k, v in totals.items() if v)
    typer.echo(f"\nDone. {summary}.")


@app.command()
def play(
    rom: str = typer.Argument(..., help="Path to a .gba, or a fuzzy query against ~/.retrokix/roms/."),
    scale: int | None = typer.Option(None, "--scale", help="Window scale factor (windowed mode only). Default: last-used scale for this ROM (3 if never set)."),
    fullscreen: bool | None = typer.Option(None, "--fullscreen/--no-fullscreen", "-f", help="Start in borderless-desktop fullscreen. Default: last-used state for this ROM. F11 toggles at runtime."),
    watch_state: bool = typer.Option(False, "--watch-state", help="Show a live Rich panel with state values from compiled.json (if present)."),
    plugin_path: Path | None = typer.Option(None, "--plugin", help="Path to a Python plugin file (creates a retrokix.plugin() instance)."),
    renderer: str = typer.Option("sdl", "--renderer", help="Renderer backend: sdl (default) or wgpu (needs retrokix[gpu])."),
    shader: str = typer.Option("linear", "--shader", help="Initial shader name (e.g. linear, nearest, crt-lottes, xbrz)."),
    user_shader: Path | None = typer.Option(None, "--user-shader", help="Path to a WGSL file to register as the 'user' shader (wgpu only)."),
    listen: bool = typer.Option(False, "--listen", help="Run the retrokix HTTP API alongside the SDL window (default 127.0.0.1:8420)."),
    listen_host: str = typer.Option("127.0.0.1", "--listen-host", help="HTTP API bind host. Implies --listen."),
    listen_port: int = typer.Option(8420, "--listen-port", help="HTTP API bind port. Implies --listen."),
    core_path: Path | None = typer.Option(None, "--core", help="Path to libretro core .so."),
    cheats: str | None = typer.Option(None, "--cheats", help="Comma-separated cheat slugs to enable at boot."),
    couch_room: str | None = typer.Option(None, "--couch-room", help="Couch room code to join (default 'default'). Generate one with `retrokix couch room-code`."),
    headless: bool = typer.Option(False, "--headless", help="Skip both the SDL window and the terminal TUI — run headless and play in a browser tab. Implies --listen and auto-opens http://127.0.0.1:<port>/stream?mode=controller."),
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser", help="With --headless, auto-open the viewer URL in the default browser. The hub spawns children with --no-open-browser; humans almost always want the default."),
    load: Path | None = typer.Option(None, "--load", help="Load this save state file at boot (after the ROM is mounted). Use this for one-shot resumes; Ctrl+L during play always reloads the latest running save."),
) -> None:
    """Boot ROM in free-run mode with an SDL window."""
    from retrokix.library import resolve_rom
    from retrokix.render import play_loop
    from retrokix.runtime import EmulatorRuntime, Mode

    try:
        rom_path = resolve_rom(rom)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    runtime = EmulatorRuntime(rom_path, core_path=core_path, mode=Mode.FREE)
    # Resolve per-ROM persisted defaults for scale / fullscreen when the
    # user didn't pass an explicit flag. Persist whatever the user did
    # pass so the next launch remembers it.
    s = runtime.settings
    if scale is None:
        scale = s.window_scale
    if fullscreen is None:
        fullscreen = s.fullscreen
    runtime._persist_setting(window_scale=scale, fullscreen=fullscreen)
    if load is not None:
        if not load.exists():
            typer.echo(f"--load: file not found at {load}", err=True)
            runtime.close()
            raise typer.Exit(code=1)
        try:
            runtime.load_state_from_file(load)
        except (OSError, RuntimeError) as exc:
            typer.echo(f"--load: failed to read {load}: {exc}", err=True)
            runtime.close()
            raise typer.Exit(code=1) from exc
        typer.echo(f"loaded ← {load}")
    if cheats:
        for slug in [s.strip() for s in cheats.split(",") if s.strip()]:
            try:
                c = runtime.enable_cheat(slug)
                typer.echo(f"cheat ON: {c.name}")
            except KeyError as exc:
                typer.echo(f"warning: {exc}", err=True)
    try:
        if headless:
            from retrokix.api.headless import run_headless
            run_headless(
                runtime,
                host=listen_host,
                port=listen_port,
                open_browser=open_browser,
            )
            return

        # --listen-host / --listen-port imply --listen.
        listen_enabled = listen or listen_host != "127.0.0.1" or listen_port != 8420
        play_loop(
            runtime,
            scale=scale,
            fullscreen=fullscreen,
            watch_state=watch_state,
            plugin_path=plugin_path,
            renderer_kind=renderer,
            initial_shader=shader,
            user_shader_path=user_shader,
            listen=listen_enabled,
            listen_host=listen_host,
            listen_port=listen_port,
            couch_room=couch_room,
        )
    finally:
        runtime.close()


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Hub bind host."),
    port: int = typer.Option(8420, "--port", help="Hub bind port."),
    roms_dir: Path | None = typer.Option(None, "--roms-dir", help="Override ~/.retrokix/roms/ as the library root."),
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser", help="Auto-open the hub landing page in the default browser at start."),
) -> None:
    """Run the retrokix hub — landing page, fame-ranked game grid, per-game tabs.

    The hub itself is a small FastAPI app. Each launched game runs as its
    own subprocess (`retrokix play --headless`) on an allocated port; the
    hub redirects the new browser tab to that child's /stream endpoint.
    """
    import uvicorn
    import webbrowser

    from retrokix.hub.reaper import IdleReaper
    from retrokix.hub.server import create_hub_app

    application = create_hub_app(host=host, roms_dir=roms_dir)
    reaper = IdleReaper(application.state.hub)
    reaper.start()

    typer.echo(f"retrokix hub on http://{host}:{port}")
    typer.echo("  endpoints: /  /api/library  /api/games  /games/launch  /play/{game_id}")

    if open_browser:
        try:
            webbrowser.open(f"http://{host}:{port}/", new=2)
        except Exception:
            pass

    try:
        uvicorn.run(application, host=host, port=port, log_level="warning")
    finally:
        reaper.stop()
        application.state.hub.shutdown_all()


scenario_app = typer.Typer(help="Manage scenarios for `retrokix train` / `retrokix tournament`.")
app.add_typer(scenario_app, name="scenario")


_SCENARIO_TEMPLATE = '''"""Auto-scaffolded by `retrokix scenario create`. Fill in the TODOs."""

from retrokix.scenario import Scenario
from retrokix.controller import Controller


class {class_name}(Scenario):
    name = "{slug}"
    rom_sha1 = "{rom_sha1}"
    decision_period = 1
    max_frames = 60 * 60 * 3                    # 3 minutes at 60 fps

    def setup(self, ctl: Controller) -> None:
        # TODO: drive past the title screen / menu / save load until the
        # player is in control. Use ctl.press / ctl.wait / ctl.read_*.
        return None

    def observe(self, ctl: Controller, frame: int) -> dict:
        # TODO: decode useful game state from memory.
        return {{"frame": frame}}

    def score(self, ctl: Controller, frame: int) -> dict:
        # TODO: compute score + structured result. Higher score = better.
        return {{"score": -float(frame), "frame": frame}}

    def done(self, ctl: Controller, frame: int) -> bool:
        # TODO: end-of-match predicate.
        return False
'''


def _slugify(text: str) -> str:
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s or "scenario"


def _classify(text: str) -> str:
    import re
    parts = re.split(r"[^a-zA-Z0-9]+", text)
    return "".join(p.capitalize() for p in parts if p) or "Scenario"


@scenario_app.command("create")
def scenario_create(
    rom: str = typer.Argument(..., help="Path to a .gba or fuzzy query against ~/.retrokix/roms/."),
    name: str = typer.Option("default", "--name", help="Scenario slug (kebab-case)."),
    out_dir: Path | None = typer.Option(None, "--out", help="Where to write (default ~/.retrokix/scenarios/)."),
) -> None:
    """Scaffold a scenario file for the given ROM."""
    import hashlib

    from retrokix.library import resolve_rom

    try:
        rom_path = resolve_rom(rom)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    slug = _slugify(name)
    rom_slug = _slugify(rom_path.stem)
    class_name = _classify(name)
    rom_sha1 = hashlib.sha1(rom_path.read_bytes()).hexdigest()

    target_dir = Path(out_dir) if out_dir else (Path.home() / ".retrokix" / "scenarios")
    target_dir.mkdir(parents=True, exist_ok=True)
    out_file = target_dir / f"{rom_slug}__{slug}.py"
    if out_file.exists():
        typer.echo(f"refusing to overwrite {out_file}", err=True)
        raise typer.Exit(code=1)

    out_file.write_text(_SCENARIO_TEMPLATE.format(
        class_name=class_name, slug=slug, rom_sha1=rom_sha1,
    ))
    typer.echo(f"wrote {out_file}")


@scenario_app.command("list")
def scenario_list() -> None:
    """List installed scenarios (bundled + ~/.retrokix/scenarios/)."""
    from retrokix.scenario import list_installed_scenarios

    entries = list_installed_scenarios()
    if not entries:
        typer.echo("no scenarios installed")
        return
    for e in entries:
        typer.echo(f"  {e['name']:35s}  {e['class']:25s}  {e['file']}")


@scenario_app.command("validate")
def scenario_validate(
    path: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Load a scenario file, instantiate its classes, report success/failure."""
    from retrokix.scenario import (
        ScenarioValidationError,
        instantiate_scenario,
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"_retrokix_validate_{path.stem}", path)
    if spec is None or spec.loader is None:
        typer.echo(f"could not import {path}", err=True)
        raise typer.Exit(code=1)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        typer.echo(f"import error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    from retrokix.scenario import Scenario

    found = False
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, Scenario) and obj is not Scenario:
            found = True
            try:
                instantiate_scenario(obj)
                typer.echo(f"  OK    {obj.__name__}  (name={obj.name})")
            except ScenarioValidationError as exc:
                typer.echo(f"  FAIL  {obj.__name__}  ({exc})", err=True)
                raise typer.Exit(code=1) from exc

    if not found:
        typer.echo(f"no Scenario subclasses found in {path}", err=True)
        raise typer.Exit(code=1)


@app.command()
def train(
    rom: str = typer.Option(..., "--rom", help="Path or fuzzy query for the ROM."),
    scenario: str = typer.Option(..., "--scenario", help="Scenario name or path[:ClassName]."),
    player: str = typer.Option(..., "--player", help="Shell command to spawn the player."),
    core_path: Path | None = typer.Option(None, "--core", help="Libretro core .so."),
    output: Path | None = typer.Option(None, "--output", help="Directory for result.json."),
) -> None:
    """Run a single, untimed match against the given scenario."""
    import json

    from retrokix.driver import StepDriver
    from retrokix.library import resolve_rom
    from retrokix.scenario import resolve_scenario

    try:
        rom_path = resolve_rom(rom)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    try:
        scenario_cls = resolve_scenario(scenario)
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    driver = StepDriver(rom_path=rom_path, scenario_cls=scenario_cls, core_path=core_path)
    label = scenario_cls.__name__
    outcome = driver.run_match(player_cmd=player, player_label=label)

    typer.echo(f"[{outcome.reason}] frame={outcome.frame_count} "
               f"score={outcome.result.get('score')} "
               f"({outcome.wall_clock_seconds:.2f}s wall)")
    if output:
        output.mkdir(parents=True, exist_ok=True)
        (output / "result.json").write_text(json.dumps({
            "player_label":   outcome.player_label,
            "player_name":    outcome.player_name,
            "result":         outcome.result,
            "reason":         outcome.reason,
            "frame_count":    outcome.frame_count,
            "lag_misses":     outcome.lag_misses,
            "wall_clock_s":   outcome.wall_clock_seconds,
            "notes":          outcome.notes,
        }, indent=2))
        typer.echo(f"wrote {output / 'result.json'}")


@app.command()
def tournament(
    rom: str = typer.Option(..., "--rom", help="Path or fuzzy query for the ROM."),
    scenario: str = typer.Option(..., "--scenario", help="Scenario name or path[:ClassName]."),
    player: list[str] = typer.Option(..., "--player", help="Player command; repeat for more bots."),
    core_path: Path | None = typer.Option(None, "--core", help="Libretro core .so."),
    output: Path | None = typer.Option(None, "--output", help="Directory for results.json."),
    lag_forfeit: int = typer.Option(60, "--lag-forfeit"),
    slack_ms: int = typer.Option(1, "--slack-ms"),
    show: bool = typer.Option(False, "--show", help="Open SDL window for the current match."),
    record: bool = typer.Option(False, "--record", help="Stubbed — slice 8 will wire this up."),
) -> None:
    """Run a real-time tournament. One match per --player, sequential."""
    import json

    from retrokix.driver import RealtimeDriver
    from retrokix.library import resolve_rom
    from retrokix.scenario import resolve_scenario

    if record:
        typer.echo("warning: --record is a v1 stub; recording lands in a later slice", err=True)
    if show:
        typer.echo("warning: --show wiring lands when SDL render is hooked to RealtimeDriver", err=True)

    try:
        rom_path = resolve_rom(rom)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    try:
        scenario_cls = resolve_scenario(scenario)
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    driver = RealtimeDriver(
        rom_path=rom_path,
        scenario_cls=scenario_cls,
        core_path=core_path,
        lag_forfeit=lag_forfeit,
        slack_s=slack_ms / 1000.0,
    )

    outcomes = []
    for i, cmd in enumerate(player, 1):
        label = cmd.split()[0]
        typer.echo(f"[match {i}/{len(player)}] {label}")
        outcome = driver.run_match(player_cmd=cmd, player_label=label)
        typer.echo(f"  → {outcome.reason}  score={outcome.result.get('score')}  "
                   f"frame={outcome.frame_count}  lag={outcome.lag_misses}")
        outcomes.append(outcome)

    ranked = sorted(outcomes, key=lambda o: o.result.get("score", 0.0), reverse=True)

    typer.echo("")
    typer.echo("Leaderboard")
    typer.echo("─" * 70)
    typer.echo(f"{'rank':<5}{'player':<25}{'score':<12}{'frame':<8}{'reason':<10}")
    typer.echo("─" * 70)
    for rank, o in enumerate(ranked, 1):
        typer.echo(
            f"{rank:<5}{o.player_label:<25}{o.result.get('score', 0.0):<12.2f}"
            f"{o.frame_count:<8}{o.reason:<10}"
        )

    if output:
        output.mkdir(parents=True, exist_ok=True)
        results_doc = {
            "scenario": scenario_cls.name,
            "matches": [
                {
                    "player_label":   o.player_label,
                    "player_name":    o.player_name,
                    "result":         o.result,
                    "reason":         o.reason,
                    "frame_count":    o.frame_count,
                    "lag_misses":     o.lag_misses,
                    "wall_clock_s":   o.wall_clock_seconds,
                    "notes":          o.notes,
                }
                for o in outcomes
            ],
            "leaderboard": [
                {
                    "rank":   rank,
                    "player": o.player_label,
                    "score":  o.result.get("score"),
                    "reason": o.reason,
                }
                for rank, o in enumerate(ranked, 1)
            ],
        }
        (output / "results.json").write_text(json.dumps(results_doc, indent=2))
        typer.echo(f"wrote {output / 'results.json'}")
