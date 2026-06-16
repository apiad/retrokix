# Plugins

A plugin is a single Python file that hooks into a running `retrokix play`
session. Reads state, writes memory, injects buttons, reacts to key
presses, runs on every frame. Can also publish its own HTTP routes
under `/plugins/<name>/...` for an agent to call.

The complement to `retrokix.Controller` (the in-process API for headless
scripts): same scripting power, but live alongside a player at the
keyboard.

## Quick start

```python
# my_plugin.py
import retrokix
p = retrokix.plugin()

@p.on_setup
def setup(ctx):
    ctx.log("plugin loaded")

@p.on_key("M")
def add_money(ctx):
    ctx.set("money", 999_999)
    ctx.log("money: 999,999")

@p.on_frame(every=60)
def heartbeat(ctx):
    ctx.log(f"frame {ctx.frame_count}")
```

```bash
retrokix play emerald --plugin my_plugin.py
```

## Loading

`--plugin` accepts either a file path or a dotted module name:

```bash
retrokix play emerald --plugin ./my_plugin.py
retrokix play emerald --plugin /tmp/heal_low_hp.py
retrokix play emerald --plugin retrokix.plugins.emerald_party     # bundled
retrokix play emerald --plugin my_packages.gbax_plugins.boss  # pip-installed
```

Resolution order: if the argument exists as a file, treat as a path.
Otherwise try a dotted module import.

## Decorators

| Decorator | Fires |
|---|---|
| `@p.on_setup` | once at plugin load |
| `@p.on_teardown` | once when retrokix shuts down |
| `@p.on_frame` | every frame |
| `@p.on_frame(every=N)` | every Nth frame |
| `@p.on_state_change(tag)` | when a tagged state value changes |
| `@p.on_state_change(tag, to=value)` | when it transitions to a specific value |
| `@p.on_key(key)` | bare key press; same slot universe as macros |
| `@p.route(path)` | exposes an HTTP endpoint under `/plugins/<name>/<path>` |
| `@p.route(path, methods=["POST"])` | with explicit methods |
| `@p.scene_resolver` | overrides scene inference; `fn(runtime) -> str \| None` |

## The `ctx` object

Passed to every handler:

| Attribute / method | What it does |
|---|---|
| `ctx.state["hp"]` | read tagged state (snapshot per frame, from `compiled.json`) |
| `ctx.state.get(tag, default)` | safe access |
| `ctx.runtime` | full `EmulatorRuntime` escape hatch |
| `ctx.frame_count` | current frame count |
| `ctx.set("money", 999_999)` | write the inferred address at the compiled width |
| `ctx.press(["a", "down"], frames=2)` | schedule synthetic input |
| `ctx.log(msg)` | one-line stdout that coexists with `--watch-state` |

## HTTP routes from plugins

When `--listen` is also passed, each plugin can register routes via
`@p.route(path)`. They get mounted under `/plugins/<name>/<path>`,
where `<name>` is the plugin file's stem.

```python
@p.route("/party")
def http_party(ctx):
    """GET /plugins/emerald_party/party"""
    return {"slots": [read_slot(ctx.runtime, i) for i in range(6)]}

@p.route("/slot/{idx}")
def http_slot(ctx, idx: int):
    """GET /plugins/emerald_party/slot/0"""
    from fastapi import HTTPException
    if idx < 0 or idx >= 6:
        raise HTTPException(400, f"out of range: {idx}")
    return read_slot(ctx.runtime, idx)
```

Path parameters in `{}` syntax are extracted by FastAPI and passed as
kwargs to the handler. The `ctx` argument is injected automatically;
FastAPI doesn't see it in the route signature.

`/plugins` (with no plugin name) lists active plugins and their
routes:

```bash
$ curl localhost:8420/plugins | jq
{
  "plugins": [
    {
      "name": "emerald_party",
      "path": "/path/to/retrokix/plugins/emerald_party.py",
      "routes": [
        {"path": "/plugins/emerald_party/party", "methods": ["GET"]},
        {"path": "/plugins/emerald_party/slot/{idx}", "methods": ["GET"]}
      ]
    }
  ]
}
```

## Atomic semantics

Plugin HTTP routes are invoked while retrokix holds the runtime lock. The
SDL play loop blocks until the route returns. This means:

- The handler sees a consistent runtime snapshot — no frames advance
  between the first and last `ctx.runtime.read_memory()` call.
- Audio glitches briefly if the handler takes more than ~10ms.
- Keep route handlers fast; for heavy compute (ML inference, file
  scanning), spawn your own thread in `on_setup` and have the route
  read from a cache the thread updates.

## Threading model

Handlers run inline on the SDL main thread. Long-running handlers
freeze audio + render. Errors in handlers print a traceback but don't
kill the plugin — subsequent handlers and the SDL loop continue.

## Bundled plugins

| Module | Game | Provides |
|---|---|---|
| `retrokix.plugins.emerald_party` | Pokémon Emerald | live party panel, `/party` and `/slot/{idx}` HTTP routes, decodes encrypted substructures |

More to come. PRs welcome — see `retrokix.plugins.emerald_party` for the
canonical pattern.

## Scene resolvers

The state tracker classifies string-labelled tags ("scenes") via a
three-strategy classifier: plugin resolver → memory-pattern vote →
pHash framebuffer template (see
[state-tracker.md](state-tracker.md) for the algorithm).

A plugin can register a resolver that runs first. If it returns a
non-None string, that wins — memory voting and pHash matching are
skipped for that frame. If it returns None, the classifier falls
through to the next strategy.

```python
@p.scene_resolver
def resolve_scene(runtime):
    """Pokémon Emerald: read gMain.callback1 (4 bytes at 0x03003eb4)."""
    cb = int.from_bytes(runtime.read_memory(0x03003eb4, 4), "little")
    return {
        0x080046a5: "overworld",
        0x080b4aed: "battle",
        0x080a1f31: "start_menu",
    }.get(cb)
```

This is the recommended escape hatch when the inferred classifier
mis-fires on a specific scene — game-specific knowledge always beats
unsupervised inference.

## Case study: `retrokix.plugins.emerald_party`

Step-by-step walk-through of how the Emerald party plugin was built —
from "where's my Torchic in memory?" to "an agent can curl
`/plugins/emerald_party/party` and read the whole team" — lives at
[cookbook/emerald_party.md](cookbook/emerald_party.md).

## See also

- [api.md](api.md) — the HTTP surface plugin routes plug into
- [concepts.md](concepts.md) — the cooperative loop story
- [state-tracker.md](state-tracker.md) — where `ctx.state` comes from
