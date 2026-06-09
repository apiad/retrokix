from pathlib import Path

import typer

app = typer.Typer(help="gbax — hacker-first GBA emulator", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print version and exit."""
    from gbax import __version__
    typer.echo(f"gbax {__version__}")


@app.command()
def play(
    rom: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    scale: int = typer.Option(3, "--scale", help="Window scale factor."),
    core_path: Path | None = typer.Option(None, "--core", help="Path to libretro core .so."),
) -> None:
    """Boot ROM in free-run mode with an SDL window."""
    from gbax.render import play_loop
    from gbax.runtime import EmulatorRuntime, Mode

    runtime = EmulatorRuntime(rom, core_path=core_path, mode=Mode.FREE)
    try:
        play_loop(runtime, scale=scale)
    finally:
        runtime.close()


@app.command()
def serve(
    rom: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8420, "--port"),
    free_run: bool = typer.Option(False, "--free-run", help="Start in free-run mode instead of step."),
    core_path: Path | None = typer.Option(None, "--core", help="Path to libretro core .so."),
) -> None:
    """Boot ROM and serve a FastAPI controller API."""
    import uvicorn

    from gbax.api.server import create_app
    from gbax.runtime import EmulatorRuntime, Mode

    mode = Mode.FREE if free_run else Mode.STEP
    runtime = EmulatorRuntime(rom, core_path=core_path, mode=mode)

    if mode == Mode.FREE:
        runtime.start_free_run_ticker()

    application = create_app(runtime)
    typer.echo(f"gbax serving {rom.name} on http://{host}:{port}")
    typer.echo(f"  mode={runtime.mode.value}  rom_sha1={runtime.rom_sha1}")
    typer.echo("  endpoints: /mode /step /speed /frame /buttons /memory /frame_count")
    try:
        uvicorn.run(application, host=host, port=port, log_level="warning")
    finally:
        runtime.close()
