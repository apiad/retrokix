# State tracker

Teach gbax which memory addresses hold which gameplay values, by
example. No per-game memory map ships with gbax — you label snapshots
as you play (`hp=45, scene=fight-menu, money=12420`), gbax intersects
the labels across captures and infers where each value lives.

## The capture / compile / refine loop

1. **Capture** while you play, at varied scenes and values. Each
   capture is a 30-frame stability filter over EWRAM + IWRAM with
   your key=value labels attached.
2. **Compile** offline to run supervised address inference: numeric
   tags (integer labels) get value-match search; categorical tags
   (string labels) get cross-group discrimination.
3. **Refine** by adding more captures wherever the inference is
   ambiguous.

## Capturing

Two ways:

### In-game hotkey

```
[in-game]
Ctrl+F                          # snapshot current state
[alt-tab to terminal]
capturing state — type labels (key=value, comma-separated):
> scene=overworld, hp=45, max_hp=100, money=12420
recording 30 frames…
captured. (52,134 stable bytes)
```

### HTTP (from a coding agent)

```bash
curl -X POST localhost:8420/capture_state -H 'content-type: application/json' \
  -d '{
    "labels": {"scene": "overworld", "hp": 45, "max_hp": 100, "money": 12420}
  }' | jq
```

Same outcome — a `.dump` file with the sparse-filtered memory + a
`.labels.json` sidecar.

## Compiling

```
$ gbax state compile emerald
compiled → /home/you/.gbax/states/<sha1>/compiled.json

$ gbax state list emerald
captures: 7
  hp        numeric      0x02024382  (u8)
  max_hp    numeric      0x02024383  (u8)
  money     numeric      0x02025e34  (u32_le)
  scene     categorical  0x03000fa4  (3 values)
```

`gbax state ambiguous <rom>` lists tags where >1 address survives the
intersection — those need more captures with varied values to
disambiguate.

## Live readout

```
$ gbax play emerald --watch-state
┌─ state ─────────────────────────────────────────────────┐
│ hp: 45  max_hp: 100  money: 12420  scene: fight-menu   │
└─────────────────────────────────────────────────────────┘
```

Rich panel updates ~10 Hz alongside normal stdout. Stays out of the
way of `print()` and `input()` from plugins.

## Supported tag types

| Kind | Label | What's inferred |
|---|---|---|
| numeric | integer | address + width (u8 / u16-LE / u32-LE) where value matches in every capture |
| scene | string | multi-byte memory-vote across u8/u16-LE/u32-LE AND a perceptual-hash framebuffer template |
| string | (deferred) | needs per-game character encoding; not in v1 |

Need ≥2 distinct scene values to discriminate.

## Scene detection

String labels go through a three-strategy classifier at runtime, in
priority order. The first strategy that returns a non-None value wins.

### Strategy 1: plugin resolver (highest priority)

A plugin can register a function that reads game-specific structures
(e.g., `gMain.callback1` in pokeemerald) and returns a scene label
directly. See [plugins.md](plugins.md) for `@p.scene_resolver`.

### Strategy 2: memory-pattern vote

At compile time, `find_memory_addresses` scans EWRAM + IWRAM across
u8, u16-LE, and u32-LE widths for offsets where the value is
**constant within each scene** AND **distinct across all scenes**.
The top-K survivors form the vote slate, stored in `compiled.json`.

At runtime, the classifier reads each address, looks up which scene
matches, and votes. If ≥ k_required addresses vote for the same scene,
that scene wins.

Multi-byte widths matter — single-byte categorical inference (the
pre-v0.11 algorithm) misses scenes that are only distinguishable by a
function-pointer value (4 bytes) at a specific WRAM address. The
u32-LE pass catches those.

### Strategy 3: pHash framebuffer template (fallback)

Each capture writes a sibling `.png` of the 240×160 framebuffer.
Compile computes a perceptual hash per scene (dHash by default,
hash_size=8 → 64-bit fingerprint). At runtime, if memory voting is
inconclusive, the classifier hashes the current framebuffer and
matches against the templates by Hamming distance.

Works well for menus and other visually-bounded scenes. Fails on
visually-unbounded scenes like overworld where every screen looks
different — within-scene hash distance approaches random. Treat as
fallback, not primary signal.

### Known caveats

- **Display-buffer trap.** Some games stage scene-conditional bytes
  through a render buffer that reads 0x00 in other scenes. Those
  addresses look perfectly discriminating in training but break the
  moment the buffer flips. The compiler tags any address where some
  scene reads 0x00 as `trap=true` so a future runtime can weight them
  down; v0.11 still includes them in the vote.
- **Selection-gated training accuracy.** The memory-vote slate is the
  top-K addresses that score best on the training captures by
  construction. Generalisation across sessions is unmeasured. If a
  scene flips silently, add more captures from a fresh session and
  recompile.
- **pHash overworld failure.** As above. Don't rely on pHash for
  unbounded scenes.

## Known blind spots

### Display buffers vs canonical addresses

The supervised inference picks the LOWEST-addressed candidate that
matches all labels. In games where in-game menus copy state into a
render buffer for display, both the buffer and the canonical address
match — and the inference often picks the buffer.

**How to spot it**: read the inferred address while the menu is
closed. If the value reads `0` or stale, it's a buffer, not canonical.

**Workaround**: capture while the menu is closed but the value has
changed (e.g., HP dropped from a hit you took while walking, with no
menu interaction in between). The buffer stays stale; the canonical
updates. The intersection survives only at the canonical address.

For deeper game-specific state (encrypted party blocks, RAM-side
inventories), the state tracker won't reach it — you write a plugin
that decodes the canonical block via `ctx.runtime.read_memory`. See
[plugins.md](plugins.md) and [cookbook/emerald_party.md](cookbook/emerald_party.md).

### Constant values during a capture session

If a value never varies across your captures (e.g., `max_hp = 21` the
entire session because you never leveled up), the numeric inference
has too many false positives — every byte that happens to equal 21
becomes a candidate. Need at least one capture where the value
differs.

## Storage layout

```
~/.gbax/states/<rom-sha1>/
├── captures/
│   ├── 2026-06-10T14-21-40.dump
│   ├── 2026-06-10T14-21-40.labels.json
│   ├── 2026-06-10T14-21-40.png     # framebuffer for pHash (v0.11+)
│   └── …
└── compiled.json                    # schema version 2
```

`.dump` files are forward-compatible; recompile any time with `gbax
state compile <rom>` to re-run inference with newer algorithms.

## See also

- [concepts.md](concepts.md) — the cooperative loop story
- [plugins.md](plugins.md) — `ctx.state` plus plugin overrides for
  derived state
- [api.md](api.md) — `/capture_state` HTTP endpoint
