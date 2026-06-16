# Concepts

This page is the longer version of the README's pitch — for the reader
who wants to know what retrokix is *for* before learning what it does.

## The cooperative loop

`retrokix play <rom>` opens an SDL window with sound and a keyboard. Pass
`--listen` and the same emulator runtime is also reachable as an HTTP
API on `127.0.0.1:8420`. Both inputs are live at the same time. The
human presses arrow keys; an agent posts to `/buttons`. The runtime
combines both via set-union, the game gets the merged input, the next
frame renders to the window AND streams over HTTP. Neither side blocks
the other.

That's the loop. From the agent's side: read the framebuffer, peek
memory, send button presses, take screenshots, read state. From the
human's side: play the game while watching a Rich panel that updates
in the terminal where the plugin you loaded is decoding your party.

Two audiences land here for different reasons.

### Speedrunning Pokémon Emerald with Claude Code

You launch `retrokix play emerald --listen` and a coding agent in the
adjacent terminal. The agent looks at the screen via `/frame`, reads
your HP via the bundled `emerald_party` plugin, suggests which moves
to use, takes screenshots of your inventory so you can quickly cross-
reference. You stay on the keyboard; the agent never presses buttons
unless you ask. Useful for navigating menus, decoding cryptic in-game
state, spotting easy-to-miss items.

### Testing a neurosymbolic policy

You launch `retrokix serve` (no human window) and your training loop. The
agent reads state through the same HTTP API, runs in step mode so the
emulator pauses for arbitrary thinking time, and learns against a
real, hand-crafted environment instead of a toy gridworld. 3,500+ GBA
games are available — Pokémon Ruby/Sapphire/Emerald, Metroid
Fusion/Zero Mission, Castlevania Aria of Sorrow, Advance Wars 1+2,
Mario Advance series, Fire Emblem, Golden Sun. The level designers
were genre masters. The state spaces are deep.

Both audiences use the same primitives. The cooperative loop isn't
two products — it's one architecture with two main use cases.

## The discovery toolkit

Three things make the loop work as a discovery instrument, not just
an emulator with extra endpoints:

### State tracker — learn memory by example

Pokémon Emerald's party data lives at `0x020244EC`. Metroid Fusion's
samus position lives somewhere else. retrokix doesn't ship a per-game
memory map. Instead: while you play, press `Ctrl+F` (or POST to
`/capture_state` from an agent), label what's true in this moment
(`hp=22, level=7, scene=overworld`), and retrokix records 30 frames of
memory. Repeat 5-10 times at varied states. Run `retrokix state compile
<rom>`. retrokix intersects your labels against memory and reports the
address each tag tracks.

The pattern works for any GBA game. The deeper page on this is in
[state-tracker.md](state-tracker.md).

### Plugins — write Python, publish HTTP routes

A plugin is a single Python file with a `retrokix.plugin()` instance.
Decorators register handlers: `@on_frame`, `@on_state_change`,
`@on_key`. A plugin can also expose its own HTTP routes via
`@p.route("/party")` — they get mounted at
`/plugins/<plugin_name>/party`. The agent in the next terminal calls
`curl /plugins/<plugin_name>/party`, gets structured JSON, decides.

The bundled `retrokix.plugins.emerald_party` plugin decodes the encrypted
party block (Pokémon's substructure encryption: XOR with personality
^ OT_id, permutation index from personality % 24). Loadable as
`--plugin retrokix.plugins.emerald_party`.

The deeper page on plugin authoring is in [plugins.md](plugins.md).

### Atomic HTTP actions

For multi-step plans (walk three tiles, screenshot, peek HP), a single
HTTP call is more useful than three. POST `/action` with a step list:

```json
{
  "steps": [
    {"hold": ["down"], "frames": 48},
    {"release": true, "frames": 8},
    {"screenshot": true, "read_memory": [{"addr": "0x02024542", "len": 2}]}
  ]
}
```

While the action is running, retrokix holds the runtime lock — the SDL
play loop blocks, so no real-time slop interleaves. The response
returns the screenshot as base64 PNG, the memory read as hex, and
`sdl_frames_inserted: 0` confirming atomicity.

Documented fully in [api.md](api.md).

## What's not here

- A trained model. retrokix is the environment, not the policy.
- A reward function. Scenarios in `automation.md` are one way to
  bolt one on; otherwise it's BYO.
- macOS / Windows wheels yet. Linux x86_64 first.
- Multi-player networking. One ROM, one emulator, one local session.

## Where to go next

- **Casual reader**, want to try the loop: README's "three commands"
  section, then come back here.
- **Plugin author**: [plugins.md](plugins.md) → [cookbook/emerald_party.md](cookbook/emerald_party.md).
- **State tracker user**: [state-tracker.md](state-tracker.md).
- **HTTP API client**: [api.md](api.md).
- **CLI surface**: [cli.md](cli.md).
