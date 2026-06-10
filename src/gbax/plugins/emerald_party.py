"""gbax plugin — live Pokémon Emerald party panel.

Reads all 6 party slots, decrypts the substructure block via personality +
OT_id XOR, and renders a Rich table with Lv / HP / Exp / species per slot.
Updates ~3 Hz to keep the SDL main thread responsive.
"""
from __future__ import annotations

import struct

import gbax

p = gbax.plugin()


# --- canonical Emerald layout ---

PARTY_BASE = 0x020244EC     # slot 0 start
SLOT_SIZE = 100             # bytes per party slot
SLOT_COUNT = 6

# Offsets WITHIN a slot (slot+N):
OFF_PERSONALITY = 0x00      # u32
OFF_OTID = 0x04             # u32
OFF_ENC_BLOCK = 0x20        # 48 encrypted bytes (4 × 12-byte substructures)
OFF_LEVEL = 0x54            # u8
OFF_CURRENT_HP = 0x56       # u16_le
OFF_MAX_HP = 0x58           # u16_le

# 24 permutations of (Growth, Attacks, EVs, Misc) within the encrypted block,
# indexed by personality % 24.
SUBSTRUCT_ORDERS = [
    "GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA",
    "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
    "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG",
    "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG",
]


def _u8(runtime, addr):
    return runtime.read_memory(addr, 1)[0]


def _u16(runtime, addr):
    return struct.unpack("<H", runtime.read_memory(addr, 2))[0]


def _u32(runtime, addr):
    return struct.unpack("<I", runtime.read_memory(addr, 4))[0]


def _decrypt_growth(enc_block: bytes, key: int) -> dict:
    """Return the Growth substructure as {species, held, exp, pp_bonus, friendship}."""
    dec = bytearray()
    for i in range(0, 48, 4):
        w = struct.unpack("<I", enc_block[i:i + 4])[0] ^ key
        dec.extend(struct.pack("<I", w))
    # (We don't know the permutation yet — caller does.)
    return dec


def read_slot(runtime, slot_idx: int):
    """Return a dict for the slot, or None if the slot is empty."""
    base = PARTY_BASE + slot_idx * SLOT_SIZE
    personality = _u32(runtime, base + OFF_PERSONALITY)
    if personality == 0:
        return None
    otid = _u32(runtime, base + OFF_OTID)
    key = personality ^ otid
    level = _u8(runtime, base + OFF_LEVEL)
    hp = _u16(runtime, base + OFF_CURRENT_HP)
    max_hp = _u16(runtime, base + OFF_MAX_HP)

    enc = runtime.read_memory(base + OFF_ENC_BLOCK, 48)
    dec = _decrypt_growth(enc, key)
    order = SUBSTRUCT_ORDERS[personality % 24]
    g_pos = order.index("G") * 12
    species = struct.unpack("<H", dec[g_pos:g_pos + 2])[0]
    held = struct.unpack("<H", dec[g_pos + 2:g_pos + 4])[0]
    exp = struct.unpack("<I", dec[g_pos + 4:g_pos + 8])[0]
    pp_bonus = dec[g_pos + 8]
    friendship = dec[g_pos + 9]

    return {
        "slot": slot_idx,
        "species": species,
        "level": level,
        "hp": hp,
        "max_hp": max_hp,
        "exp": exp,
        "held": held,
        "friendship": friendship,
        "pp_bonus": pp_bonus,
    }


# --- Rich Live panel ---

_live = None
_render_fn = None


def _build_table(runtime):
    from rich.table import Table
    t = Table(title="party (live)", show_header=True, header_style="bold cyan", expand=False)
    t.add_column("#", justify="right")
    t.add_column("species", justify="right")
    t.add_column("lv", justify="right")
    t.add_column("hp", justify="right")
    t.add_column("exp", justify="right")
    t.add_column("fnd", justify="right")
    for i in range(SLOT_COUNT):
        slot = read_slot(runtime, i)
        if slot is None:
            continue
        hp_color = "green" if slot["hp"] >= slot["max_hp"] * 0.5 else "yellow" if slot["hp"] >= slot["max_hp"] * 0.25 else "red"
        t.add_row(
            str(slot["slot"]),
            str(slot["species"]),
            str(slot["level"]),
            f"[{hp_color}]{slot['hp']}/{slot['max_hp']}[/{hp_color}]",
            str(slot["exp"]),
            str(slot["friendship"]),
        )
    return t


@p.route("/party")
def http_party(ctx):
    """Full party as structured JSON."""
    slots = []
    for i in range(SLOT_COUNT):
        s = read_slot(ctx.runtime, i)
        if s is not None:
            slots.append(s)
    return {"count": len(slots), "slots": slots}


@p.route("/slot/{idx}")
def http_slot(ctx, idx: int):
    """One slot by index (0-5). 404 if empty."""
    from fastapi import HTTPException
    if not 0 <= idx < SLOT_COUNT:
        raise HTTPException(status_code=400, detail=f"slot index {idx} out of range")
    s = read_slot(ctx.runtime, idx)
    if s is None:
        raise HTTPException(status_code=404, detail=f"slot {idx} is empty")
    return s


@p.on_setup
def setup(ctx):
    global _live, _render_fn
    from rich.console import Console
    from rich.live import Live

    def render():
        return _build_table(ctx.runtime)

    _render_fn = render
    _live = Live(render(), console=Console(), refresh_per_second=4, transient=False)
    _live.__enter__()
    ctx.log("emerald-party plugin loaded")


@p.on_frame(every=20)
def refresh(ctx):
    if _live is not None and _render_fn is not None:
        try:
            _live.update(_render_fn())
        except Exception as exc:
            ctx.log(f"party-panel refresh error: {exc}")


@p.on_teardown
def teardown(ctx):
    global _live
    if _live is not None:
        _live.__exit__(None, None, None)
        _live = None
