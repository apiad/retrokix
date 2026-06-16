"""Persistent peer identity for the couch.

A retrokix user gets one identity, generated once on first use and stored
at ~/.retrokix/identity.json. Identity carries:

  - `id`   : a random 16-byte hex token — what other peers see and
             address in mailboxes. Stable across sessions, machines if
             you copy the file, friend groups across years.
  - `name` : a display name (defaults to $USER).
  - `created_at` : ISO-8601 timestamp, purely informational.

We intentionally use a random token, not Ed25519, for the first slice.
Signing isn't useful until we add anti-grief or end-to-end encryption
on a remote relay; both are later concerns. When that day comes the
keypair can replace `id` without changing the wire shape on the bus.
"""

from __future__ import annotations

import getpass
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path.home() / ".retrokix" / "identity.json"
ID_BYTES = 16  # 16 hex chars per byte → 32-char IDs.


@dataclass
class Identity:
    id: str
    name: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> "Identity":
        return cls(id=d["id"], name=d["name"], created_at=d["created_at"])


def _new_identity(name: str | None = None) -> Identity:
    return Identity(
        id=secrets.token_hex(ID_BYTES),
        name=name or getpass.getuser(),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def load_or_generate(path: Path | str = DEFAULT_PATH) -> Identity:
    """Read the identity file if it exists; otherwise generate one,
    write it (0o600), and return it.

    Atomic write: create a temp file in the same directory and rename
    in place so a crash mid-write can't leave a half-written identity.
    """
    p = Path(path)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            return Identity.from_dict(data)
        except (json.JSONDecodeError, KeyError, OSError):
            # Corrupted identity file — back it up and regenerate.
            backup = p.with_suffix(p.suffix + ".broken")
            try:
                p.rename(backup)
            except OSError:
                pass
    p.parent.mkdir(parents=True, exist_ok=True)
    identity = _new_identity()
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(identity.to_dict(), indent=2))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(p)
    return identity
