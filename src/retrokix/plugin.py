"""Play-time plugin system: decorator-registered handlers + ctx surface.

A plugin file constructs a single `Plugin` instance via `retrokix.plugin()`,
attaches handlers with decorators, and is loaded by `retrokix play
--plugin <path>`. Handlers run inline on the SDL play loop's main
thread and receive a `PluginContext` (ctx) exposing state reads,
state writes, button injection, and logging.
"""
from __future__ import annotations

import struct
from typing import Any, Callable, Iterable, Mapping


class Plugin:
    """Decorator-registered handler container. One instance per plugin file."""

    def __init__(self) -> None:
        self.setup_handlers: list[Callable] = []
        self.teardown_handlers: list[Callable] = []
        # frame_handlers: list of (handler, every_n_frames)
        self.frame_handlers: list[tuple[Callable, int]] = []
        # state_change_handlers: dict[tag, list[(handler, to_value_or_None)]]
        self.state_change_handlers: dict[str, list[tuple[Callable, Any]]] = {}
        # key_handlers: dict[slot, list[handler]]
        self.key_handlers: dict[str, list[Callable]] = {}
        # http_routes: list of (path, methods, handler) tuples; mounted under
        # /plugins/<plugin_name>/ when the play loop's --listen flag is set.
        self.http_routes: list[tuple[str, list[str], Callable]] = []
        # scene_resolvers: callables taking a runtime and returning a scene
        # name string OR None to fall through. Invoked as Strategy A (highest
        # priority) by the StateReader before memory-vote / pHash.
        self.scene_resolvers: list[Callable] = []
        # Couch — peer-to-peer plugin events. See retrokix.couch.
        # `couch_emits` — every event type this plugin may send. Calls to
        # `ctx.couch.send(event=…)` whose event is not in this set are
        # refused by the CouchHandle.
        # `couch_event_handlers` — event type → list of (ctx, peer, payload)
        # handlers, fired on the SDL play-loop thread (NOT the asyncio
        # thread), so plugin code can touch the runtime safely.
        self.couch_emits: list[str] = []
        self.couch_event_handlers: dict[str, list[Callable]] = {}

    def on_setup(self, fn: Callable) -> Callable:
        self.setup_handlers.append(fn)
        return fn

    def on_teardown(self, fn: Callable) -> Callable:
        self.teardown_handlers.append(fn)
        return fn

    def on_frame(self, fn_or_every=None, *, every: int = 1):
        """Usable as ``@p.on_frame`` OR ``@p.on_frame(every=N)``."""
        if callable(fn_or_every):
            self.frame_handlers.append((fn_or_every, 1))
            return fn_or_every

        every_n = every if fn_or_every is None else fn_or_every

        def decorator(fn: Callable) -> Callable:
            self.frame_handlers.append((fn, every_n))
            return fn

        return decorator

    def on_state_change(self, tag: str, *, to: Any = None) -> Callable:
        """Usable as ``@p.on_state_change(tag)`` or ``@p.on_state_change(tag, to=value)``."""
        def decorator(fn: Callable) -> Callable:
            self.state_change_handlers.setdefault(tag, []).append((fn, to))
            return fn
        return decorator

    def scene_resolver(self, fn: Callable) -> Callable:
        """Register a callable that returns the current scene name or None.

        Signature: ``fn(runtime) -> str | None``. The runtime is the live
        EmulatorRuntime; read memory directly via ``runtime.read_memory()``,
        ``runtime.read_u32()``, etc. Return ``None`` to fall through to the
        next strategy (memory vote, then pHash).
        """
        self.scene_resolvers.append(fn)
        return fn

    def route(self, path: str, methods: list[str] | None = None) -> Callable:
        """Register an HTTP route mounted under ``/plugins/<name>/`` when --listen is on.

        Handler signature: ``fn(ctx, **path_params)``. The path may use
        FastAPI ``{param}`` syntax. The handler returns any JSON-able dict.
        """
        method_list = [m.upper() for m in (methods or ["GET"])]

        def decorator(fn: Callable) -> Callable:
            self.http_routes.append((path, method_list, fn))
            return fn

        return decorator

    def on_key(self, key: str) -> Callable:
        """Usable as ``@p.on_key("M")``. Key is normalized to canonical slot form."""
        from retrokix.macros import normalize_slot
        slot = normalize_slot(key)
        if slot is None:
            raise ValueError(
                f"invalid key slot {key!r}; must be A-Z, 0-9, F1-F9, "
                "SPACE, RETURN, or BACKSPACE"
            )

        def decorator(fn: Callable) -> Callable:
            self.key_handlers.setdefault(slot, []).append(fn)
            return fn

        return decorator

    def emit_couch(self, *event_types: str) -> None:
        """Declare event types this plugin will emit. Required before
        ``ctx.couch.send(event=…)`` will accept them."""
        for et in event_types:
            if not isinstance(et, str) or not et:
                raise ValueError(f"event type must be a non-empty string: {et!r}")
            if et not in self.couch_emits:
                self.couch_emits.append(et)

    def on_couch_event(self, event_type: str) -> Callable:
        """Register a receive handler for one couch event type.

        Handler signature: ``fn(ctx, peer, payload)`` — runs on the
        SDL play-loop thread, NOT the asyncio bus thread. Safe to touch
        the runtime / write memory.
        """
        if not isinstance(event_type, str) or not event_type:
            raise ValueError(f"event_type must be a non-empty string: {event_type!r}")

        def decorator(fn: Callable) -> Callable:
            self.couch_event_handlers.setdefault(event_type, []).append(fn)
            return fn

        return decorator

    @property
    def couch_receives(self) -> list[str]:
        return list(self.couch_event_handlers.keys())


_WIDTH_TO_BYTES = {"u8": 1, "u16_le": 2, "u32_le": 4}
_WIDTH_MAX = {"u8": 0xFF, "u16_le": 0xFFFF, "u32_le": 0xFFFFFFFF}


def _encode_value(value: int, width: str) -> bytes:
    if width == "u8":
        return bytes([value])
    if width == "u16_le":
        return struct.pack("<H", value)
    if width == "u32_le":
        return struct.pack("<I", value)
    raise ValueError(f"unknown width: {width!r}")


class PluginContext:
    """Per-plugin context passed to every handler.

    Snapshot-style `state` dict (refreshed between handler invocations),
    `set` / `press` write APIs that respect the compiled state map and
    the macro infrastructure, plus `log` and `runtime` escape hatch.
    """

    def __init__(
        self,
        runtime,
        state_reader,
        compiled_tags: Mapping[str, dict],
        *,
        log_fn=None,
    ) -> None:
        self.runtime = runtime
        self._reader = state_reader
        self._compiled = dict(compiled_tags)
        self._log_fn = log_fn if log_fn is not None else print
        self._state_snapshot: dict[str, int | str] = {}
        # ctx.couch is set by the play loop after a CouchHandle has been
        # connected. Plugins that declared neither couch_emits nor
        # couch_event_handlers see ctx.couch == None.
        self.couch = None  # type: ignore[var-annotated]

    @property
    def frame_count(self) -> int:
        return self.runtime.frame_count

    @property
    def state(self) -> dict[str, int | str]:
        return self._state_snapshot

    def refresh_state(self) -> None:
        """Re-read tag values from the runtime. Called by the dispatcher."""
        self._state_snapshot = self._reader.read_all()

    def set(self, tag: str, value: int) -> None:
        """Write a numeric tag via the compiled state map."""
        if tag not in self._compiled:
            raise KeyError(f"{tag} not in compiled.json")
        info = self._compiled[tag]
        if info.get("kind") != "numeric":
            raise ValueError(f"categorical writes not supported for {tag!r}")
        width = info["width"]
        if not 0 <= value <= _WIDTH_MAX[width]:
            raise ValueError(f"value {value} overflows {width} for tag {tag!r}")
        addr = int(info["addr"], 16)
        data = _encode_value(value, width)
        self.runtime.write_memory(addr, data)

    def press(self, buttons: Iterable, frames: int = 1) -> None:
        """Schedule a button hold for ``frames`` frames, then release.

        Buttons may be ``Button`` enum members or string names
        (case-insensitive). Fire-and-forget: routes through the
        runtime's ``play_macro`` so plugin + player + macros all
        combine via set-union.
        """
        from datetime import datetime, timezone

        from retrokix.input import Button, button_from_str
        from retrokix.macros import Macro

        button_set: set[Button] = set()
        for b in buttons:
            if isinstance(b, Button):
                button_set.add(b)
            else:
                button_set.add(button_from_str(str(b)))

        macro = Macro(
            slot="",
            name="ctx.press",
            rom_sha1=getattr(self.runtime, "rom_sha1", ""),
            rom_name=str(getattr(self.runtime, "rom_path", "")),
            recorded_at=datetime.now(timezone.utc),
            total_frames=frames,
            events=[(0, frozenset(button_set)), (frames, frozenset())],
        )
        try:
            self.runtime.play_macro(macro)
        except RuntimeError as exc:
            print(f"warning: ctx.press dropped: {exc}")

    def log(self, msg: str) -> None:
        self._log_fn(str(msg))


def load_plugin(path_or_module) -> Plugin:
    """Load a plugin and return its sole ``Plugin`` instance.

    Accepts either a filesystem path (``/tmp/myplugin.py``) or a dotted
    module name (``retrokix.plugins.emerald_party``). Resolution order: if the
    argument exists as a file, treat as path; otherwise try dotted import.

    Raises:
        RuntimeError: if the file defines zero or more than one Plugin instances.
        SyntaxError: if the file fails to parse.
    """
    import importlib
    import importlib.util
    from pathlib import Path

    arg = str(path_or_module)
    p = Path(arg)
    if not p.exists() and "." in arg and "/" not in arg and "\\" not in arg:
        # Looks like a dotted module name and no such file exists — import it.
        module = importlib.import_module(arg)
        instances = [v for v in vars(module).values() if isinstance(v, Plugin)]
        if len(instances) != 1:
            raise RuntimeError(
                f"plugin module {arg!r} must define exactly one retrokix.plugin() instance; "
                f"found {len(instances)}"
            )
        return instances[0]

    spec = importlib.util.spec_from_file_location(f"_retrokix_plugin_{p.stem}", p)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load plugin spec for {p}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    instances = [v for v in vars(module).values() if isinstance(v, Plugin)]
    if len(instances) != 1:
        raise RuntimeError(
            f"plugin file {p.name} must create exactly one retrokix.plugin() instance; "
            f"found {len(instances)}"
        )
    return instances[0]


def plugin() -> Plugin:
    """Construct a fresh Plugin instance.

    Convention: a plugin file does::

        import retrokix
        p = retrokix.plugin()
        @p.on_setup
        def setup(ctx): ...
    """
    return Plugin()
