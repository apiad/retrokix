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
