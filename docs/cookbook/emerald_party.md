# Cookbook: Pokémon Emerald party plugin

Walk-through of how `gbax.plugins.emerald_party` was built. This is
the canonical example of decoding game-specific structured state and
exposing it as plugin HTTP routes. Useful as a template for similar
plugins targeting other GBA games.

The full source lives at
[`src/gbax/plugins/emerald_party.py`](https://github.com/apiad/gbax/blob/main/src/gbax/plugins/emerald_party.py).

## The problem

Pokémon Emerald's party data isn't in plain memory — each of the six
party slots stores most fields (species, moves, EVs, experience,
held item) in an encrypted 48-byte block. Reading it requires:

1. Knowing where slot 0 starts.
2. Reading the personality value (4 bytes) and original-trainer ID
   (4 bytes) at the slot start. These are unencrypted.
3. Computing the XOR key as `personality ^ OT_id`.
4. Reading the 48-byte encrypted block and XOR-decrypting each u32.
5. Figuring out which 12-byte sub-block holds Growth (which contains
   experience) via the 24-permutation table indexed by
   `personality % 24`.
6. Parsing the Growth sub-block as `(species: u16, held: u16,
   experience: u32, pp_bonus: u8, friendship: u8, unknown: u16)`.

For each of the six slots.

The unencrypted fields (level, current HP, max HP) live at fixed
offsets within the 100-byte slot and don't need decryption.

## Finding slot 0

gbax's state tracker won't find encrypted data directly — the byte
values don't match labels. But it will find adjacent unencrypted
fields. The path used to bootstrap this plugin:

1. Captured state with `Ctrl+F` at varied HP and level values across
   8-10 in-game moments.
2. Ran `gbax state compile emerald` and saw two candidate addresses
   for `level`: one display buffer at `0x020240AE` (only valid when
   the POKEMON menu is open) and one canonical address at
   `0x02024540`.
3. Verified `0x02024540` reads `6` in the overworld matches Torchic's
   level. Confirmed.
4. Inferred slot 0 starts at `0x02024540 - 0x54 = 0x020244EC` (since
   level lives at slot+0x54 in the documented layout).

The full path-of-discovery is documented in the state-tracker docs
under "Known blind spots: Display buffers vs canonical addresses."

## The slot layout (subset gbax cares about)

| Offset | Field | Width |
|---|---|---|
| 0x00 | personality | u32 |
| 0x04 | OT_id | u32 |
| 0x20 | encrypted block | 48 bytes |
| 0x54 | level | u8 |
| 0x56 | current HP | u16-LE |
| 0x58 | max HP | u16-LE |

Slot N starts at `0x020244EC + N * 100`.

## The 24-permutation table

The encrypted block is 4 substructures of 12 bytes each, in one of 24
orders. The index = `personality % 24`. Substructure names:

- **G**rowth — species, held item, experience, pp_bonuses, friendship
- **A**ttacks — 4 moves and their PP
- **E**Vs/condition
- **M**isc — pokerus, met location, ribbons, etc.

Lookup table:

```
GAEM GAME GEAM GEMA GMAE GMEA
AGEM AGME AEGM AEMG AMGE AMEG
EGAM EGMA EAGM EAMG EMGA EMAG
MGAE MGEA MAGE MAEG MEGA MEAG
```

So personality `0x5C14E9A2`, `% 24 = 18`, looks up the 19th entry
(`MGAE`), which means substructure 0 in the encrypted block is Misc,
substructure 1 (at offset 12 of the decrypted block) is Growth, and
so on.

## Decryption

XOR each u32 in the encrypted block with the key:

```python
import struct

def decrypt_block(enc_bytes: bytes, key: int) -> bytes:
    out = bytearray()
    for i in range(0, 48, 4):
        word = struct.unpack("<I", enc_bytes[i:i+4])[0] ^ key
        out.extend(struct.pack("<I", word))
    return bytes(out)
```

Then locate the Growth substructure at `order.index("G") * 12` and
parse:

```python
def parse_growth(growth: bytes) -> dict:
    species, held = struct.unpack("<HH", growth[0:4])
    experience = struct.unpack("<I", growth[4:8])[0]
    pp_bonus = growth[8]
    friendship = growth[9]
    return {"species": species, "held": held, "exp": experience,
            "pp_bonus": pp_bonus, "friendship": friendship}
```

## Putting it together in a plugin

```python
import gbax
p = gbax.plugin()

PARTY_BASE = 0x020244EC
SLOT_SIZE = 100
SLOT_COUNT = 6
SUBSTRUCT_ORDERS = [
    "GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA",
    "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
    "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG",
    "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG",
]

def read_slot(runtime, slot_idx: int):
    base = PARTY_BASE + slot_idx * SLOT_SIZE
    personality = struct.unpack("<I", runtime.read_memory(base, 4))[0]
    if personality == 0:
        return None  # empty slot
    otid = struct.unpack("<I", runtime.read_memory(base + 4, 4))[0]
    key = personality ^ otid

    level = runtime.read_memory(base + 0x54, 1)[0]
    hp = struct.unpack("<H", runtime.read_memory(base + 0x56, 2))[0]
    max_hp = struct.unpack("<H", runtime.read_memory(base + 0x58, 2))[0]

    enc = runtime.read_memory(base + 0x20, 48)
    dec = decrypt_block(enc, key)
    order = SUBSTRUCT_ORDERS[personality % 24]
    growth = dec[order.index("G") * 12 : order.index("G") * 12 + 12]
    g = parse_growth(growth)
    return {"slot": slot_idx, "level": level, "hp": hp, "max_hp": max_hp, **g}

@p.route("/party")
def http_party(ctx):
    return {"slots": [s for s in (read_slot(ctx.runtime, i) for i in range(SLOT_COUNT)) if s]}

@p.route("/slot/{idx}")
def http_slot(ctx, idx: int):
    from fastapi import HTTPException
    if not 0 <= idx < SLOT_COUNT:
        raise HTTPException(400, f"out of range: {idx}")
    s = read_slot(ctx.runtime, idx)
    if s is None:
        raise HTTPException(404, f"slot {idx} is empty")
    return s
```

That's the core. The bundled plugin adds a Rich Live terminal panel
that renders the table while you play, but the HTTP routes are the
same.

## Running it

```bash
gbax play emerald --listen --plugin gbax.plugins.emerald_party
```

Then from any terminal:

```bash
$ curl localhost:8420/plugins/emerald_party/party | jq '.slots[0]'
{ "slot": 0, "level": 11, "hp": 33, "max_hp": 33,
  "species": 280, "exp": 853, "friendship": 113, ... }
```

## Generalizing to other games

The pattern (find canonical address via state tracker → decode
structured state via known game-specific format → expose via plugin
HTTP route) works for:

- **Metroid Fusion** — Samus position, HP, missiles, suit upgrades.
  No encryption, simpler.
- **Castlevania Aria of Sorrow** — soul list, HP/MP, equipped
  weapons.
- **Advance Wars** — unit positions, terrain, funds.
- **Fire Emblem** — unit roster, levels, equipment.

Per-game memory layouts are documented at the various RAM-map wikis
for each franchise. The state tracker tells you which addresses
*your* save file has them at; the plugin gives you a structured API
to read them.

## See also

- [plugins.md](../plugins.md) — plugin authoring reference
- [state-tracker.md](../state-tracker.md) — finding canonical addresses
- [concepts.md](../concepts.md) — the cooperative loop story
