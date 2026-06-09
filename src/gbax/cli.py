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
