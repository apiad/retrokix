"""`gbax couch ...` CLI subcommands — broker, send, listen.

Lets you exercise the bus end-to-end across two terminals without
the SDL play loop in the picture yet. The plugin-integration slice
that lands next uses the same CouchHandle these commands sit on.

  gbax couch broker
    Binds ~/.gbax/couch/default.sock and forwards events between
    connected peers until SIGINT.

  gbax couch listen --peer-id bob --receives couch.gift.consumable.tool
    Connects as `bob`, prints every event it receives, one per line.

  gbax couch send --peer-id alice --to bob \
                  --event couch.gift.consumable.tool \
                  --payload '{"tier":3,"count":1}'
    Connects briefly as `alice`, fires one event, disconnects.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path

import typer

from gbax.couch.handle import BrokerHandle, CouchHandle
from gbax.couch.session import Event

app = typer.Typer(help="Couch — peer-to-peer plugin events.", no_args_is_help=True)


DEFAULT_SOCK = Path.home() / ".gbax" / "couch" / "default.sock"


def _resolve(sock: str | None) -> Path:
    return Path(sock) if sock else DEFAULT_SOCK


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


# ---------- broker ----------

@app.command()
def broker(
    sock: str = typer.Option(None, "--sock", help=f"Unix socket path (default {DEFAULT_SOCK})."),
) -> None:
    """Run a couch broker until Ctrl+C."""
    sock_path = _resolve(sock)
    _ensure_dir(sock_path)
    # If something stale lives at this path, remove it — asyncio.start_unix_server
    # otherwise raises EADDRINUSE.
    if sock_path.exists() and sock_path.is_socket():
        sock_path.unlink()

    handle = BrokerHandle()
    try:
        handle.serve_unix(str(sock_path))
    except OSError as exc:
        typer.echo(f"couch broker: bind failed at {sock_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"couch broker listening on {sock_path}  (Ctrl+C to stop)")

    stop = False

    def _stop(_signum, _frame) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        while not stop:
            time.sleep(0.1)
    finally:
        handle.close()
        if sock_path.exists() and sock_path.is_socket():
            try:
                sock_path.unlink()
            except OSError:
                pass
        typer.echo("couch broker stopped.")


# ---------- listen ----------

@app.command()
def listen(
    peer_id: str = typer.Option(..., "--peer-id", help="Identifier for this listener on the bus."),
    receives: list[str] = typer.Option(
        ..., "--receives", "-r",
        help="Event type(s) to subscribe to. Repeat for multiple.",
    ),
    name: str = typer.Option(None, "--name", help="Display name (defaults to --peer-id)."),
    sock: str = typer.Option(None, "--sock", help=f"Unix socket path (default {DEFAULT_SOCK})."),
) -> None:
    """Connect as a peer and print every matching event to stdout."""
    handle = CouchHandle(
        peer_id=peer_id,
        name=name or peer_id,
        emits=[],
        receives=list(receives),
    )
    sock_path = _resolve(sock)
    try:
        handle.connect_unix(str(sock_path))
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        typer.echo(f"couch listen: no broker at {sock_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"couch: {peer_id} listening on {sock_path}  ({len(handle.peers())} peer(s))")
    for r in receives:
        typer.echo(f"  receives: {r}")

    def _on(_h: CouchHandle, e: Event) -> None:
        line = json.dumps({"from": e.sender, "event": e.event, "payload": e.payload})
        # Print + flush so pipes downstream see lines immediately.
        typer.echo(line)
        sys.stdout.flush()

    for r in receives:
        handle.on(r, _on)

    stop = False
    def _stop(_signum, _frame) -> None:
        nonlocal stop
        stop = True
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        while not stop:
            time.sleep(0.1)
    finally:
        handle.close()


# ---------- send ----------

@app.command()
def send(
    peer_id: str = typer.Option(..., "--peer-id", help="Identifier for the sender (a short-lived 'guest' is fine)."),
    event: str = typer.Option(..., "--event", help="Event type — e.g. couch.gift.consumable.tool."),
    payload: str = typer.Option("{}", "--payload", help="JSON payload."),
    to: str = typer.Option(None, "--to", help="Target peer_id; omit to broadcast."),
    name: str = typer.Option(None, "--name", help="Display name (defaults to --peer-id)."),
    sock: str = typer.Option(None, "--sock", help=f"Unix socket path (default {DEFAULT_SOCK})."),
) -> None:
    """Connect as a one-shot peer, fire one event, disconnect."""
    try:
        payload_obj = json.loads(payload)
    except json.JSONDecodeError as exc:
        typer.echo(f"couch send: --payload isn't valid JSON: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    handle = CouchHandle(
        peer_id=peer_id,
        name=name or peer_id,
        emits=[event],
        receives=[],
    )
    sock_path = _resolve(sock)
    try:
        handle.connect_unix(str(sock_path))
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        typer.echo(f"couch send: no broker at {sock_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        handle.send(to=to, event=event, payload=payload_obj)
    except ValueError as exc:
        typer.echo(f"couch send: {exc}", err=True)
        handle.close()
        raise typer.Exit(code=1) from exc

    # Tiny grace period so the broker definitely sees the frame before
    # we tear the socket down.
    time.sleep(0.05)
    handle.close()
    target = to if to else "broadcast"
    typer.echo(f"couch send: {event} → {target}")
