from pathlib import Path

import typer

app = typer.Typer(help="gbax — hacker-first GBA emulator", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print version and exit."""
    from gbax import __version__
    typer.echo(f"gbax {__version__}")


@app.command()
def search(
    query: str = typer.Argument(..., help="Fuzzy match — all tokens must appear in the ROM name."),
    refresh: bool = typer.Option(False, "--refresh", help="Force-fetch the latest metadata from archive.org (default uses bundled snapshot)."),
) -> None:
    """Search the configured ROM archive (currently archive.org's No-Intro GBA mirror)."""
    from gbax.library import RomLibrary

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
    roms_dir: Path | None = typer.Option(None, "--dest", help="Where to save the .gba (default ~/.gbax/roms/)."),
    refresh: bool = typer.Option(False, "--refresh", help="Force-fetch the latest metadata from archive.org."),
) -> None:
    """Download a ROM. Auto-picks the best match; prints the final .gba path."""
    from gbax.library import RomLibrary

    lib = RomLibrary(roms_dir=roms_dir, refresh=refresh) if roms_dir else RomLibrary(refresh=refresh)
    matches = lib.search(query)
    if not matches:
        typer.echo(f"no matches for {query!r}")
        raise typer.Exit(code=1)

    # Prefer the region the user asked for, else USA, else first match.
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
        typer.echo("  (use a more specific query or --region to override)")
    else:
        typer.echo(f"match: {chosen.name}")
    typer.echo(f"  size: {chosen.size / 1_048_576:.1f} MB")

    path = lib.download(chosen)
    typer.echo(f"saved: {path}")


@app.command()
def cheats(
    rom: str = typer.Argument(..., help="Path to a .gba, or a fuzzy query against ~/.gbax/roms/."),
) -> None:
    """List cheats catalogued (libretro-database) for the given ROM."""
    from gbax.cheats import cheats_for_rom
    from gbax.library import resolve_rom

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

    from gbax.library import resolve_rom

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
    slug: str = typer.Argument(..., help="Cheat slug from `gbax cheats <rom>`."),
) -> None:
    """Pin a cheat to a hotkey for the given ROM. Persists to ~/.gbax/pins/<sha1>.json."""
    from gbax import pins as pins_module
    from gbax.cheats import Cheat, cheats_for_rom

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
    from gbax import pins as pins_module

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
    from gbax import pins as pins_module

    _, sha1 = _resolve_rom_sha1(rom)
    current = pins_module.load(sha1)
    if not current:
        typer.echo("no pins")
        return
    for key in sorted(current):
        typer.echo(f"  {key}  →  {current[key]}")


@app.command()
def list_roms() -> None:
    """List ROMs in ~/.gbax/roms/."""
    from gbax.library import list_local_roms, sha1

    roms = list_local_roms()
    if not roms:
        typer.echo("no ROMs in ~/.gbax/roms/")
        return
    for p in roms:
        typer.echo(f"  {p.name}  ({p.stat().st_size / 1_048_576:.1f} MB)  sha1:{sha1(p)[:10]}")


@app.command()
def play(
    rom: str = typer.Argument(..., help="Path to a .gba, or a fuzzy query against ~/.gbax/roms/."),
    scale: int = typer.Option(3, "--scale", help="Window scale factor."),
    core_path: Path | None = typer.Option(None, "--core", help="Path to libretro core .so."),
    cheats: str | None = typer.Option(None, "--cheats", help="Comma-separated cheat slugs to enable at boot."),
) -> None:
    """Boot ROM in free-run mode with an SDL window."""
    from gbax.library import resolve_rom
    from gbax.render import play_loop
    from gbax.runtime import EmulatorRuntime, Mode

    try:
        rom_path = resolve_rom(rom)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    runtime = EmulatorRuntime(rom_path, core_path=core_path, mode=Mode.FREE)
    if cheats:
        for slug in [s.strip() for s in cheats.split(",") if s.strip()]:
            try:
                c = runtime.enable_cheat(slug)
                typer.echo(f"cheat ON: {c.name}")
            except KeyError as exc:
                typer.echo(f"warning: {exc}", err=True)
    try:
        play_loop(runtime, scale=scale)
    finally:
        runtime.close()


@app.command()
def serve(
    rom: str = typer.Argument(..., help="Path to a .gba, or a fuzzy query against ~/.gbax/roms/."),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8420, "--port"),
    free_run: bool = typer.Option(False, "--free-run", help="Start in free-run mode instead of step."),
    core_path: Path | None = typer.Option(None, "--core", help="Path to libretro core .so."),
) -> None:
    """Boot ROM and serve a FastAPI controller API."""
    import uvicorn

    from gbax.api.server import create_app
    from gbax.library import resolve_rom
    from gbax.runtime import EmulatorRuntime, Mode

    try:
        rom_path = resolve_rom(rom)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    mode = Mode.FREE if free_run else Mode.STEP
    runtime = EmulatorRuntime(rom_path, core_path=core_path, mode=mode)

    if mode == Mode.FREE:
        runtime.start_free_run_ticker()

    application = create_app(runtime)
    typer.echo(f"gbax serving {rom_path.name} on http://{host}:{port}")
    typer.echo(f"  mode={runtime.mode.value}  rom_sha1={runtime.rom_sha1}")
    typer.echo("  endpoints: /mode /step /speed /frame /buttons /memory /frame_count")
    try:
        uvicorn.run(application, host=host, port=port, log_level="warning")
    finally:
        runtime.close()


scenario_app = typer.Typer(help="Manage scenarios for `gbax train` / `gbax tournament`.")
app.add_typer(scenario_app, name="scenario")


_SCENARIO_TEMPLATE = '''"""Auto-scaffolded by `gbax scenario create`. Fill in the TODOs."""

from gbax.scenario import Scenario
from gbax.controller import Controller


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
    rom: str = typer.Argument(..., help="Path to a .gba or fuzzy query against ~/.gbax/roms/."),
    name: str = typer.Option("default", "--name", help="Scenario slug (kebab-case)."),
    out_dir: Path | None = typer.Option(None, "--out", help="Where to write (default ~/.gbax/scenarios/)."),
) -> None:
    """Scaffold a scenario file for the given ROM."""
    import hashlib

    from gbax.library import resolve_rom

    try:
        rom_path = resolve_rom(rom)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    slug = _slugify(name)
    rom_slug = _slugify(rom_path.stem)
    class_name = _classify(name)
    rom_sha1 = hashlib.sha1(rom_path.read_bytes()).hexdigest()

    target_dir = Path(out_dir) if out_dir else (Path.home() / ".gbax" / "scenarios")
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
    """List installed scenarios (bundled + ~/.gbax/scenarios/)."""
    from gbax.scenario import list_installed_scenarios

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
    from gbax.scenario import (
        ScenarioValidationError,
        instantiate_scenario,
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"_gbax_validate_{path.stem}", path)
    if spec is None or spec.loader is None:
        typer.echo(f"could not import {path}", err=True)
        raise typer.Exit(code=1)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        typer.echo(f"import error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    from gbax.scenario import Scenario

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

    from gbax.driver import StepDriver
    from gbax.library import resolve_rom
    from gbax.scenario import resolve_scenario

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

    from gbax.driver import RealtimeDriver
    from gbax.library import resolve_rom
    from gbax.scenario import resolve_scenario

    if record:
        typer.echo("warning: --record is a v1 stub; recording lands in a later slice", err=True)
    if show:
        typer.echo("warning: --show wiring lands when SDL render is hooked to RealtimeDriver", err=True)

    try:
        rom_path = resolve_rom(rom)
    except (FileNotFoundError, RuntimeError) as exc:
        typer.echo(str(exc), err=True); raise typer.Exit(code=1) from exc

    try:
        scenario_cls = resolve_scenario(scenario)
    except Exception as exc:
        typer.echo(str(exc), err=True); raise typer.Exit(code=1) from exc

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
