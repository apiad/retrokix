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
| categorical | string | address where the byte is constant per label group AND different across groups |
| string | (deferred) | needs per-game character encoding; not in v1 |

Need ≥2 distinct categorical values to discriminate.

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

### Categorical inference is single-byte

The current categorical algorithm searches single bytes (u8) for the
discriminating address. Some game states are only distinguishable by
a function-pointer value (4 bytes) at a specific WRAM address. v1
won't find these. Workaround: write a plugin that reads the four
bytes and exposes `scene` as a computed value.

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
│   └── …
└── compiled.json
```

`.dump` files are forward-compatible; recompile any time with `gbax
state compile <rom>` to re-run inference with newer algorithms.

## See also

- [concepts.md](concepts.md) — the cooperative loop story
- [plugins.md](plugins.md) — `ctx.state` plus plugin overrides for
  derived state
- [api.md](api.md) — `/capture_state` HTTP endpoint
