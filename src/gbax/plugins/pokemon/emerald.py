"""gbax informational plugin — Pokémon Emerald companion.

Read-only: never calls runtime.set_buttons. Registers a Rich live panel
and HTTP routes for party, battle state, opponent, weaknesses, debug
introspection. The action surface (auto-fight, healing, walking) lives
in gbax.plugins.pokemon.emerald_driver — load it explicitly to enable.
"""
from __future__ import annotations

import struct

import gbax
from gbax.plugins.pokemon.shared.addresses import (
    BMON_OFF_HP, BMON_OFF_LEVEL, BMON_OFF_MAX_HP, BMON_OFF_SPECIES,
    BATTLE_MON_SIZE, EMERALD_US_V10_SHA1, GBATTLE_MONS_BASE, GBATTLE_TYPE_FLAGS,
    OPP_SINGLES_SLOT, SLOT_COUNT,
)
from gbax.plugins.pokemon.shared.battle import (
    battle_state_dict, read_battle_opponent,
)
from gbax.plugins.pokemon.shared.formulas import (
    resistances, species_types, weaknesses as type_weaknesses,
)
from gbax.plugins.pokemon.shared.party import (
    SPECIES_NAMES, read_slot,
)
from gbax.plugins.pokemon.shared.scene import battle_phase

p = gbax.plugin()


# --- Opponent tag (manual or auto-detected; informational only) ---

_opponent: dict | None = None
_autodetect_enabled = False


def _likely_moves(species: int, level: int):
    """Heuristic moveset: last 4 distinct level-up moves the species could know."""
    from gbax.plugins.pokemon.shared.data import load_levelup
    learnset = load_levelup().get(str(species), [])
    eligible = [m for m in learnset if m["level"] <= level]
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
    from gbax.plugins.pokemon.shared.data import load_types
    for tid, disp in load_types().items():
        if disp.upper() == name.upper():
            return int(tid)
    return None


def _best_move_against(slot_data: dict, defender_types: list[int]):
    """Per-slot best move against a defender. Uses real moves when available,
    falls back to level-up heuristic for synthetic queries."""
    from gbax.plugins.pokemon.shared.formulas import type_effectiveness
    real_moves = slot_data.get("moves") or []
    if real_moves:
        candidates = [(m["name"], m.get("type") or "NORMAL", m.get("power") or 0)
                      for m in real_moves]
    else:
        from gbax.plugins.pokemon.shared.data import load_moves
        moves_table = load_moves()
        candidates = []
        for m in _likely_moves(slot_data["species"], slot_data["level"]):
            info = moves_table.get(str(m["move_id"])) or {}
            candidates.append((m["move_name"], info.get("type", "NORMAL"), info.get("power", 0)))
    best = None
    for name, type_name, power in candidates:
        if power == 0:
            continue
        type_id = _type_id_for_name(type_name)
        if type_id is None:
            continue
        mul = type_effectiveness(type_id, defender_types)
        score = power * mul
        if best is None or score > best["score"]:
            best = {"move_name": name, "type_name": type_name, "mul": mul,
                    "power": power, "score": score}
    return best


# --- Rich panel ---

_live = None
_render_fn = None


def _build_opponent_panel(runtime=None):
    if _opponent is None:
        return None
    from rich.panel import Panel
    from rich.table import Table
    from gbax.plugins.pokemon.shared.data import load_types
    sp = _opponent["species"]
    lv = _opponent["level"]
    types = species_types(sp) or []
    type_names = load_types()
    name = SPECIES_NAMES.get(sp, f"#{sp}")
    types_str = " / ".join(type_names.get(str(t), f"#{t}") for t in types) or "?"

    bands = Table.grid(padding=(0, 2))
    bands.add_column(style="bold")
    bands.add_column()
    bands.add_row("[red]4×[/red]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in type_weaknesses(types) if m == 4.0) or "—")
    bands.add_row("[yellow]2×[/yellow]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in type_weaknesses(types) if m == 2.0) or "—")
    bands.add_row("[green]½×[/green]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in resistances(types) if m == 0.5) or "—")
    bands.add_row("[green]¼×[/green]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in resistances(types) if m == 0.25) or "—")
    bands.add_row("[blue]0×[/blue]",
        ", ".join(type_names.get(str(t), f"#{t}") for t, m in resistances(types) if m == 0.0) or "—")

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
            best = _best_move_against(slot, types)
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
            str(slot["slot"]), slot["species_name"], str(slot["level"]),
            f"[{hp_color}]{slot['hp']}/{slot['max_hp']}[/{hp_color}]",
            f"{slot['exp_to_next_level']} ({pct}%)",
            next_move_str, next_evo_str,
        )
    return t


# --- HTTP routes (read-only) ---

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
    from fastapi import HTTPException
    if not 0 <= idx < SLOT_COUNT:
        raise HTTPException(status_code=400, detail=f"slot index {idx} out of range")
    s = read_slot(ctx.runtime, idx)
    if s is None:
        raise HTTPException(status_code=404, detail=f"slot {idx} is empty")
    return s


@p.route("/weaknesses/{species_id}")
def http_weaknesses(ctx, species_id: int):
    from gbax.plugins.pokemon.shared.data import load_species_info, load_types
    from fastapi import HTTPException
    info = load_species_info().get(str(species_id))
    if not info:
        raise HTTPException(status_code=404, detail=f"unknown species {species_id}")
    types = species_types(species_id)
    if not types:
        raise HTTPException(status_code=500, detail=f"no types for species {species_id}")
    type_names = load_types()
    weak = type_weaknesses(types)
    return {
        "species": species_id,
        "species_name": SPECIES_NAMES.get(species_id, f"#{species_id}"),
        "types": [type_names.get(str(t), f"#{t}") for t in types],
        "weaknesses": [{"type": type_names.get(str(t), f"#{t}"), "mul": m} for t, m in weak],
    }


@p.route("/opponent", methods=["GET"])
def http_opponent_get(ctx):
    return _opponent or {}


@p.route("/opponent/{species_id}/{level}", methods=["POST"])
def http_opponent_set(ctx, species_id: int, level: int):
    global _opponent
    from gbax.plugins.pokemon.shared.data import load_species_info
    from fastapi import HTTPException
    if not load_species_info().get(str(species_id)):
        raise HTTPException(status_code=404, detail=f"unknown species {species_id}")
    _opponent = {"species": species_id, "level": level}
    return {"set": _opponent}


@p.route("/opponent/clear", methods=["POST"])
def http_opponent_clear(ctx):
    global _opponent
    _opponent = None
    return {"cleared": True}


@p.route("/battle/state")
def http_battle_state(ctx):
    return battle_state_dict(ctx.runtime)


@p.route("/battle/phase")
def http_battle_phase(ctx):
    raw, name = battle_phase(ctx.runtime)
    return {"phase_id": raw, "phase": name}


@p.route("/debug/battle")
def http_debug_battle(ctx):
    flags = struct.unpack("<I", ctx.runtime.read_memory(GBATTLE_TYPE_FLAGS, 4))[0]
    base = GBATTLE_MONS_BASE + OPP_SINGLES_SLOT * BATTLE_MON_SIZE
    species = struct.unpack("<H", ctx.runtime.read_memory(base + BMON_OFF_SPECIES, 2))[0]
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
        "level": level, "hp": hp, "max_hp": max_hp,
    }


# --- Frame hooks: auto-detect opponent + refresh panel ---

@p.on_frame(every=30)
def _poll_battle_opponent(ctx):
    """Auto-detect the in-battle opponent. Manual POST overrides."""
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
        ctx.log("pokemon.emerald: auto-detect enabled (Emerald US v1.0)")
    else:
        ctx.log(f"pokemon.emerald: auto-detect off (rom sha {rom_sha} != Emerald US v1.0)")

    def render():
        party = _build_table(ctx.runtime)
        opp = _build_opponent_panel(ctx.runtime)
        if opp is None:
            return party
        return Group(party, opp)

    _render_fn = render
    _live = Live(render(), console=Console(), refresh_per_second=4, transient=False)
    _live.__enter__()
    ctx.log("pokemon.emerald plugin loaded")


@p.on_frame(every=20)
def refresh(ctx):
    if _live is not None and _render_fn is not None:
        try:
            _live.update(_render_fn())
        except Exception as exc:
            ctx.log(f"pokemon.emerald panel refresh error: {exc}")


@p.on_teardown
def teardown(ctx):
    global _live
    if _live is not None:
        _live.__exit__(None, None, None)
        _live = None
