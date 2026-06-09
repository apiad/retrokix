import typer

app = typer.Typer(help="gbax — hacker-first GBA emulator")


@app.command()
def version() -> None:
    """Print version and exit."""
    from gbax import __version__
    typer.echo(f"gbax {__version__}")
