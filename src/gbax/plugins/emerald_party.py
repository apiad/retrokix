"""gbax plugin — live Pokémon Emerald party panel.

Reads all 6 party slots, decrypts the substructure block via personality +
OT_id XOR, and renders a Rich table with Lv / HP / Exp / species per slot.
Updates ~3 Hz to keep the SDL main thread responsive.
"""
from __future__ import annotations

import json
import struct
from importlib.resources import files

import gbax

p = gbax.plugin()


def _load_json_table(name: str) -> dict[int, object]:
    try:
        raw = files("gbax.data").joinpath(name).read_text()
        return {int(k): v for k, v in json.loads(raw).items()}
    except Exception:
        return {}


SPECIES_NAMES = _load_json_table("emerald_species.json")
GROWTH_RATES = _load_json_table("emerald_growth_rates.json")

GROWTH_MEDIUM_FAST = 0
GROWTH_ERRATIC = 1
GROWTH_FLUCTUATING = 2
GROWTH_MEDIUM_SLOW = 3
GROWTH_FAST = 4
GROWTH_SLOW = 5


def exp_at_level(growth: int, n: int) -> int:
    """Cumulative experience required to reach level n. Mirrors pokeemerald
    src/data/pokemon/experience_tables.h macros. n in [0, 100]."""
    if n <= 0:
        return 0
    if n == 1:
        return 1
    if growth == GROWTH_MEDIUM_FAST:
        return n ** 3
    if growth == GROWTH_FAST:
        return (4 * n ** 3) // 5
    if growth == GROWTH_SLOW:
        return (5 * n ** 3) // 4
    if growth == GROWTH_MEDIUM_SLOW:
        return (6 * n ** 3) // 5 - 15 * n ** 2 + 100 * n - 140
    if growth == GROWTH_ERRATIC:
        if n <= 50:
            return (100 - n) * n ** 3 // 50
        if n <= 68:
            return (150 - n) * n ** 3 // 100
        if n <= 98:
            return ((1911 - 10 * n) // 3) * n ** 3 // 500
        return (160 - n) * n ** 3 // 100
    if growth == GROWTH_FLUCTUATING:
        if n <= 15:
            return ((n + 1) // 3 + 24) * n ** 3 // 50
        if n <= 36:
            return (n + 14) * n ** 3 // 50
        return ((n // 2) + 32) * n ** 3 // 50
    return n ** 3


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

    growth = GROWTH_RATES.get(species, GROWTH_MEDIUM_FAST)
    exp_cur_lv = exp_at_level(growth, level)
    exp_next_lv = exp_at_level(growth, level + 1) if level < 100 else exp_cur_lv
    span = max(1, exp_next_lv - exp_cur_lv)
    into = max(0, exp - exp_cur_lv)
    to_next = max(0, exp_next_lv - exp)

    return {
        "slot": slot_idx,
        "species": species,
        "species_name": SPECIES_NAMES.get(species, f"#{species}"),
        "level": level,
        "hp": hp,
        "max_hp": max_hp,
        "exp": exp,
        "exp_into_level": into,
        "exp_to_next_level": to_next,
        "exp_level_span": span,
        "held": held,
        "friendship": friendship,
        "pp_bonus": pp_bonus,
        "next_move": next_move_for(species, level),
        "next_evolution": next_evolution_for(species, level),
    }


# --- Goal lookups (next move + next evolution per slot) ---

def next_move_for(species: int, level: int) -> dict | None:
    """Next level-up move this species learns after current level."""
    from gbax.plugins.emerald_data import load_levelup
    learnset = load_levelup().get(str(species), [])
    for entry in learnset:
        if entry["level"] > level:
            return {
                "level": entry["level"],
                "move_name": entry["move_name"],
                "move_id": entry["move_id"],
                "in": entry["level"] - level,
            }
    return None


def next_evolution_for(species: int, level: int) -> dict | None:
    """Next evolution and when it'll trigger. Levels only for v0.12 —
    Item/Friendship/etc. triggers report the trigger but no time-to-fire."""
    from gbax.plugins.emerald_data import load_evolutions
    evos = load_evolutions().get(str(species), [])
    if not evos:
        return None
    # Pick the first reachable: prefer LEVEL trigger over branch ones for clarity
    for evo in evos:
        if evo["trigger"] == "LEVEL":
            return {
                "target_name": evo["target_name"],
                "trigger": "LEVEL",
                "at_level": evo["param"],
                "in": max(0, evo["param"] - level),
            }
    # Fall back: any other trigger (FRIENDSHIP, ITEM, TRADE…)
    evo = evos[0]
    return {
        "target_name": evo["target_name"],
        "trigger": evo["trigger"],
        "param": evo["param"],
    }


# --- Rich Live panel ---

_live = None
_render_fn = None


def _likely_moves(species: int, level: int):
    """Heuristic: the last 4 distinct damaging moves a species has learned via
    level-up at-or-below the current level. Pokémon let you keep at most 4 at
    a time; new ones displace old ones in learn order. Status moves (power=0)
    are still returned so the panel can flag 'no damaging answer'."""
    from gbax.plugins.emerald_data import load_levelup
    learnset = load_levelup().get(str(species), [])
    eligible = [m for m in learnset if m["level"] <= level]
    # Walk newest → oldest, dedupe by move_id, take 4
    seen = set()
    keep = []
    for m in reversed(eligible):
        if m["move_id"] in seen:
            continue
        seen.add(m["move_id"])
        keep.append(m)
        if len(keep) >= 4:
            break
    return keep


def _type_id_for_name(name: str) -> int | None:
    from gbax.plugins.emerald_data import load_types
    for tid, disp in load_types().items():
        if disp.upper() == name.upper():
            return int(tid)
    return None


def _best_move_against(species: int, level: int, defender_types: list[int]):
    """Return (move_name, mul, power) for this slot's best move vs the
    defender, or None if no damaging move."""
    from gbax.plugins.emerald_data import load_moves
    from gbax.plugins.emerald_formulas import type_effectiveness
    moves = load_moves()
    best = None
    for m in _likely_moves(species, level):
        move_info = moves.get(str(m["move_id"])) or {}
        power = move_info.get("power", 0)
        if power == 0:
            continue
        type_name = move_info.get("type", "NORMAL")
        type_id = _type_id_for_name(type_name)
        if type_id is None:
            continue
        mul = type_effectiveness(type_id, defender_types)
        # Crude damage proxy: power × mul. Real calc waits for Slice 3.
        score = power * mul
        if best is None or score > best["score"]:
            best = {
                "move_name": m["move_name"],
                "type_name": type_name,
                "mul": mul,
                "power": power,
                "score": score,
            }
    return best


def _build_opponent_panel(runtime=None):
    """Rich Panel for the currently tagged opponent. None if no opponent set."""
    if _opponent is None:
        return None
    from rich.panel import Panel
    from rich.table import Table
    from gbax.plugins.emerald_formulas import species_types, weaknesses, resistances
    from gbax.plugins.emerald_data import load_types
    sp = _opponent["species"]
    lv = _opponent["level"]
    types = species_types(sp) or []
    type_names = load_types()
    name = SPECIES_NAMES.get(sp, f"#{sp}")
    types_str = " / ".join(type_names.get(str(t), f"#{t}") for t in types) or "?"

    # Top section: weakness/resistance bands
    bands = Table.grid(padding=(0, 2))
    bands.add_column(style="bold")
    bands.add_column()
    bands.add_row("[red]4×[/red]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in weaknesses(types) if m == 4.0) or "—")
    bands.add_row("[yellow]2×[/yellow]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in weaknesses(types) if m == 2.0) or "—")
    bands.add_row("[green]½×[/green]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in resistances(types) if m == 0.5) or "—")
    bands.add_row("[green]¼×[/green]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in resistances(types) if m == 0.25) or "—")
    bands.add_row("[blue]0×[/blue]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in resistances(types) if m == 0.0) or "—")

    # Per-party recommendations (needs runtime to read party)
    recs = None
    if runtime is not None:
        recs = Table(show_header=True, header_style="bold cyan", expand=False)
        recs.add_column("slot")
        recs.add_column("best move")
        recs.add_column("type")
        recs.add_column("×", justify="right")
        rows = []
        for i in range(SLOT_COUNT):
            slot = read_slot(runtime, i)
            if slot is None:
                continue
            best = _best_move_against(slot["species"], slot["level"], types)
            if best is None:
                rows.append((slot["species_name"], "(status only)", "—", 0))
                continue
            rows.append((slot["species_name"], best["move_name"], best["type_name"], best["mul"]))
        rows.sort(key=lambda r: r[3], reverse=True)
        for sp_name, mv_name, ty_name, mul in rows:
            mul_str = f"{mul:g}"
            mark = "✓" if mul >= 2.0 else (" " if mul == 1.0 else "✗")
            style = "bold green" if mul >= 2.0 else ("dim red" if mul < 1.0 else "white")
            recs.add_row(
                f"[{style}]{mark} {sp_name}[/{style}]",
                f"[{style}]{mv_name}[/{style}]",
                f"[{style}]{ty_name}[/{style}]",
                f"[{style}]{mul_str}×[/{style}]",
            )

    if recs is None:
        body = bands
    else:
        from rich.console import Group
        body = Group(bands, "", recs)

    return Panel(body,
                 title=f"[bold]opponent — {name} L{lv} ({types_str})[/bold]",
                 border_style="red")


def _build_table(runtime):
    from rich.table import Table
    t = Table(title="party (live)", show_header=True, header_style="bold cyan", expand=False)
    t.add_column("#", justify="right")
    t.add_column("species", justify="right")
    t.add_column("lv", justify="right")
    t.add_column("hp", justify="right")
    t.add_column("xp →", justify="right")
    t.add_column("next move", justify="left")
    t.add_column("next evo", justify="left")
    for i in range(SLOT_COUNT):
        slot = read_slot(runtime, i)
        if slot is None:
            continue
        hp_color = "green" if slot["hp"] >= slot["max_hp"] * 0.5 else "yellow" if slot["hp"] >= slot["max_hp"] * 0.25 else "red"
        span = slot["exp_level_span"]
        into = slot["exp_into_level"]
        pct = int(100 * into / span) if span else 0

        nm = slot.get("next_move")
        next_move_str = f"{nm['move_name']} @L{nm['level']} (+{nm['in']})" if nm else "—"

        ev = slot.get("next_evolution")
        if ev and ev.get("trigger") == "LEVEL":
            next_evo_str = f"{ev['target_name']} @L{ev['at_level']} (+{ev['in']})"
        elif ev:
            next_evo_str = f"{ev['target_name']} ({ev['trigger'].lower()})"
        else:
            next_evo_str = "—"

        t.add_row(
            str(slot["slot"]),
            slot["species_name"],
            str(slot["level"]),
            f"[{hp_color}]{slot['hp']}/{slot['max_hp']}[/{hp_color}]",
            f"{slot['exp_to_next_level']} ({pct}%)",
            next_move_str,
            next_evo_str,
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


@p.route("/weaknesses/{species_id}")
def http_weaknesses(ctx, species_id: int):
    """Type weaknesses for a species — no party context needed.

    GET /plugins/emerald_party/weaknesses/74  → Geodude.
    """
    from gbax.plugins.emerald_formulas import species_types, weaknesses
    from gbax.plugins.emerald_data import load_species_info, load_types
    from fastapi import HTTPException
    info = load_species_info().get(str(species_id))
    if not info:
        raise HTTPException(status_code=404, detail=f"unknown species {species_id}")
    types = species_types(species_id)
    if not types:
        raise HTTPException(status_code=500, detail=f"no types for species {species_id}")
    type_names = load_types()
    weak = weaknesses(types)
    return {
        "species": species_id,
        "species_name": SPECIES_NAMES.get(species_id, f"#{species_id}"),
        "types": [type_names.get(str(t), f"#{t}") for t in types],
        "weaknesses": [
            {"type": type_names.get(str(t), f"#{t}"), "mul": m} for t, m in weak
        ],
    }


# --- Battle state reader (Pokémon Emerald US v1.0) ---
#
# gBattleMons[4] sits in EWRAM as a fully-decoded BattlePokemon array
# (88 bytes per battler). Singles: opponent is index 1.
# Source: include/pokemon.h struct BattlePokemon, src/battle_main.c:164.
#
# Address is the well-known Emerald US v1.0 (rev 0) offset.
# ROM SHA1 we expect: f3ae088181bf583e55daf962a92bb46f4f1d07b7

EMERALD_US_V10_SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"
GBATTLE_MONS_BASE = 0x02024084
GBATTLE_TYPE_FLAGS = 0x02022FEC   # zeroed when battle ends — gate for stale reads
BATTLE_MON_SIZE = 88
OPP_SINGLES_SLOT = 1

# Offsets within a BattlePokemon, source: include/pokemon.h
BMON_OFF_SPECIES = 0x00
BMON_OFF_HP = 0x28
BMON_OFF_LEVEL = 0x2A
BMON_OFF_MAX_HP = 0x2C
BMON_OFF_TYPES = 0x21  # u8 × 2


def in_battle(runtime) -> bool:
    """gBattleTypeFlags non-zero ⇒ currently in a battle."""
    flags = struct.unpack("<I", runtime.read_memory(GBATTLE_TYPE_FLAGS, 4))[0]
    # In battle, only the low ~24 bits are populated. A wild value here
    # (e.g. > 0x00FFFFFF) signals our address is wrong on this build.
    return 0 < flags < 0x01000000


def read_battle_opponent(runtime):
    """Read gBattleMons[1]. Return a dict if a live opponent, else None."""
    if not in_battle(runtime):
        return None
    base = GBATTLE_MONS_BASE + OPP_SINGLES_SLOT * BATTLE_MON_SIZE
    species = struct.unpack("<H", runtime.read_memory(base + BMON_OFF_SPECIES, 2))[0]
    if species == 0 or species > 412:
        return None
    level = runtime.read_memory(base + BMON_OFF_LEVEL, 1)[0]
    if level == 0 or level > 100:
        return None
    max_hp = struct.unpack("<H", runtime.read_memory(base + BMON_OFF_MAX_HP, 2))[0]
    if max_hp == 0 or max_hp > 999:
        return None
    hp = struct.unpack("<H", runtime.read_memory(base + BMON_OFF_HP, 2))[0]
    if hp > max_hp:
        return None
    return {
        "species": species,
        "species_name": SPECIES_NAMES.get(species, f"#{species}"),
        "level": level,
        "hp": hp,
        "max_hp": max_hp,
        "auto": True,
    }


# --- Opponent tracking — auto-detected in battle, overridable via POST ---

_opponent: dict | None = None  # {"species": int, "level": int, "auto": bool?}
_autodetect_enabled = False  # set at on_setup once we verify the ROM


@p.route("/opponent", methods=["GET"])
def http_opponent_get(ctx):
    """Current 'opponent' tag — what the dashboard's matchup panel uses."""
    return _opponent or {}


@p.route("/opponent/{species_id}/{level}", methods=["POST"])
def http_opponent_set(ctx, species_id: int, level: int):
    """Tag what you're fighting. Live panel grows a matchup section."""
    global _opponent
    from gbax.plugins.emerald_data import load_species_info
    from fastapi import HTTPException
    if not load_species_info().get(str(species_id)):
        raise HTTPException(status_code=404, detail=f"unknown species {species_id}")
    _opponent = {"species": species_id, "level": level}
    return {"set": _opponent}


@p.route("/opponent/clear", methods=["POST"])
def http_opponent_clear(ctx):
    """Drop the opponent tag — panel returns to party-only view."""
    global _opponent
    _opponent = None
    return {"cleared": True}


@p.route("/debug/battle")
def http_debug_battle(ctx):
    """Raw read of the battle-state addresses, for troubleshooting auto-detect."""
    flags = struct.unpack("<I", ctx.runtime.read_memory(GBATTLE_TYPE_FLAGS, 4))[0]
    base = GBATTLE_MONS_BASE + OPP_SINGLES_SLOT * BATTLE_MON_SIZE
    species = struct.unpack("<H", ctx.runtime.read_memory(base, 2))[0]
    level = ctx.runtime.read_memory(base + BMON_OFF_LEVEL, 1)[0]
    hp = struct.unpack("<H", ctx.runtime.read_memory(base + BMON_OFF_HP, 2))[0]
    max_hp = struct.unpack("<H", ctx.runtime.read_memory(base + BMON_OFF_MAX_HP, 2))[0]
    return {
        "rom_sha1": getattr(ctx.runtime, "rom_sha1", None),
        "expected_sha1": EMERALD_US_V10_SHA1,
        "autodetect_enabled": _autodetect_enabled,
        "gBattleTypeFlags_addr": f"0x{GBATTLE_TYPE_FLAGS:08X}",
        "gBattleTypeFlags_value": f"0x{flags:08X}",
        "in_battle_judgment": 0 < flags < 0x01000000,
        "gBattleMons_1_addr": f"0x{base:08X}",
        "species": species,
        "species_name": SPECIES_NAMES.get(species, f"#{species}") if species else None,
        "level": level,
        "hp": hp,
        "max_hp": max_hp,
    }


@p.on_frame(every=30)
def _poll_battle_opponent(ctx):
    """Auto-detect: when a battle Pokémon is live in gBattleMons[1], tag it.
    When it goes away, clear (but only if the current tag was auto-set —
    a manual POST takes precedence)."""
    global _opponent
    if not _autodetect_enabled:
        return
    try:
        detected = read_battle_opponent(ctx.runtime)
    except Exception:
        detected = None
    if detected is not None:
        _opponent = detected
        return
    if _opponent is not None and _opponent.get("auto"):
        _opponent = None


@p.on_setup
def setup(ctx):
    global _live, _render_fn, _autodetect_enabled
    from rich.console import Console, Group
    from rich.live import Live

    rom_sha = getattr(ctx.runtime, "rom_sha1", None)
    if rom_sha == EMERALD_US_V10_SHA1:
        _autodetect_enabled = True
        ctx.log("emerald-party: auto-detect enabled (Emerald US v1.0)")
    else:
        ctx.log(f"emerald-party: auto-detect off (rom sha {rom_sha} != Emerald US v1.0); manual POST /opponent only")

    def render():
        party = _build_table(ctx.runtime)
        opp = _build_opponent_panel(ctx.runtime)
        if opp is None:
            return party
        return Group(party, opp)

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
