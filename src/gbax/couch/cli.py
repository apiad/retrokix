"""`gbax couch ...` CLI — broker, send, listen, whoami, room-code.

Lets you exercise the bus end-to-end across two terminals without
the SDL play loop in the picture yet. The plugin-integration slice
that lands next uses the same CouchHandle these commands sit on.

  gbax couch broker
    Binds ~/.gbax/couch/default.sock and forwards events between
    connected peers in the same room until SIGINT.

  gbax couch listen --receives couch.gift.consumable.tool [--room CODE]
    Connects as your persistent identity, prints every event it
    receives in `--room` (or 'default'), one per line.

  gbax couch send --to PEER_ID --event TYPE --payload JSON [--room CODE]
    Fires one event, disconnects. Sender identity comes from
    ~/.gbax/identity.json by default.

  gbax couch whoami
    Print your persistent peer identity.

  gbax couch room-code
    Generate a fresh three-word room code. Pass it to friends
    along with `--room CODE`.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path

import typer

from gbax.couch.handle import BrokerHandle, CouchHandle
from gbax.couch.identity import load_or_generate as load_identity
from gbax.couch.naming import (
    DEFAULT_ROOM,
    is_valid_room_code,
    new_room_code,
    normalize_room_code,
)
from gbax.couch.session import Event

app = typer.Typer(help="Couch — peer-to-peer plugin events.", no_args_is_help=True)


DEFAULT_SOCK = Path.home() / ".gbax" / "couch" / "default.sock"


def _resolve(sock: str | None) -> Path:
    return Path(sock) if sock else DEFAULT_SOCK


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def _resolve_room(raw: str | None) -> str:
    if not raw:
        return DEFAULT_ROOM
    code = normalize_room_code(raw)
    if not is_valid_room_code(code):
        raise typer.BadParameter(
            f"invalid room code {raw!r} — use letters/digits/hyphens, e.g. 'quick-amber-otter'"
        )
    return code


# ---------- broker ----------

@app.command()
def broker(
    sock: str = typer.Option(None, "--sock", help=f"Unix socket path (default {DEFAULT_SOCK})."),
) -> None:
    """Run a couch broker until Ctrl+C. Serves every room on this socket."""
    sock_path = _resolve(sock)
    _ensure_dir(sock_path)
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
    receives: list[str] = typer.Option(
        ..., "--receives", "-r",
        help="Event type(s) to subscribe to. Repeat for multiple.",
    ),
    peer_id: str = typer.Option(None, "--peer-id", help="Override identity (default: ~/.gbax/identity.json)."),
    name: str = typer.Option(None, "--name", help="Display name (defaults to identity)."),
    room: str = typer.Option(None, "--room", help=f"Room code (default '{DEFAULT_ROOM}')."),
    sock: str = typer.Option(None, "--sock", help=f"Unix socket path (default {DEFAULT_SOCK})."),
) -> None:
    """Connect as a peer and print every matching event to stdout."""
    identity = load_identity()
    handle = CouchHandle(
        peer_id=peer_id or identity.id,
        name=name or identity.name,
        emits=[],
        receives=list(receives),
        room=_resolve_room(room),
    )
    sock_path = _resolve(sock)
    try:
        handle.connect_unix(str(sock_path))
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        typer.echo(f"couch listen: no broker at {sock_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"couch: {handle.peer_id} listening on {sock_path}  "
        f"room={handle.room}  ({len(handle.peers())} peer(s))"
    )
    for r in receives:
        typer.echo(f"  receives: {r}")

    def _on(_h: CouchHandle, e: Event) -> None:
        line = json.dumps({"from": e.sender, "event": e.event, "payload": e.payload})
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
    event: str = typer.Option(..., "--event", help="Event type — e.g. couch.gift.consumable.tool."),
    payload: str = typer.Option("{}", "--payload", help="JSON payload."),
    to: str = typer.Option(None, "--to", help="Target peer_id; omit to broadcast."),
    peer_id: str = typer.Option(None, "--peer-id", help="Override identity (default: ~/.gbax/identity.json)."),
    name: str = typer.Option(None, "--name", help="Display name (defaults to identity)."),
    room: str = typer.Option(None, "--room", help=f"Room code (default '{DEFAULT_ROOM}')."),
    sock: str = typer.Option(None, "--sock", help=f"Unix socket path (default {DEFAULT_SOCK})."),
) -> None:
    """Connect as a one-shot peer, fire one event, disconnect."""
    try:
        payload_obj = json.loads(payload)
    except json.JSONDecodeError as exc:
        typer.echo(f"couch send: --payload isn't valid JSON: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    identity = load_identity()
    handle = CouchHandle(
        peer_id=peer_id or identity.id,
        name=name or identity.name,
        emits=[event],
        receives=[],
        room=_resolve_room(room),
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

    # Grace period so the broker definitely sees the frame before tear-down.
    time.sleep(0.05)
    handle.close()
    target = to if to else "broadcast"
    typer.echo(f"couch send: {event} → {target}  (room={handle.room})")


# ---------- whoami ----------

@app.command()
def whoami() -> None:
    """Print your persistent peer identity (creating one on first run)."""
    identity = load_identity()
    typer.echo(f"id:         {identity.id}")
    typer.echo(f"name:       {identity.name}")
    typer.echo(f"created_at: {identity.created_at}")


# ---------- room-code ----------

@app.command("room-code")
def room_code() -> None:
    """Generate a fresh three-word room code. Share it with friends."""
    typer.echo(new_room_code())
