"""retrokix driver plugin — Pokémon Emerald automation.

Action surface for the Emerald companion: HTTP endpoints + in-game hotkeys
that take routine play decisions and execute button sequences. Strictly
game-rule fidelity — no memory writes, no flag-flipping, no cheats.

Depends on retrokix.plugins.pokemon.shared (not on the informational plugin
itself — both share the same logic library).

Imports the auto-fight from the previous v0.15.x emerald_party.py verbatim
for slice 1; slice 2 will rewrite this using gMain.callback2 scene detection.
"""
from __future__ import annotations

import base64
import threading
from io import BytesIO

import retrokix
from retrokix.input import button_from_str
from retrokix.plugins.pokemon.shared.addresses import (
    BMON_PLAYER_SLOT, MENU_TRANSITION_FRAMES, NAV_GAP_FRAMES,
    OPP_SINGLES_SLOT, PARTY_MENU_SETTLE_FRAMES, PRESS_FRAMES, SETTLE_FRAMES,
    SLOT_COUNT,
)
from retrokix.plugins.pokemon.shared.battle import (
    battle_state_dict, read_battle_mon,
)
from retrokix.plugins.pokemon.shared.party import (
    party_slots_full,
)
from retrokix.plugins.pokemon.shared.scene import (
    ADVANCEABLE_PHASES, PHASE_ACTION_MENU, PHASE_SECONDARY_MENU,
    PHASE_TRAINER_ANNOUNCE, WAIT_PHASES, in_battle, phase_raw,
)

p = retrokix.plugin()


# --- Sequence helpers ---

def _home_cursor_steps():
    """Up Up Left Left to drive any 2x2 menu cursor to top-left."""
    return [
        {"hold": ["up"], "frames": PRESS_FRAMES}, {"release": True, "frames": NAV_GAP_FRAMES},
        {"hold": ["up"], "frames": PRESS_FRAMES}, {"release": True, "frames": NAV_GAP_FRAMES},
        {"hold": ["left"], "frames": PRESS_FRAMES}, {"release": True, "frames": NAV_GAP_FRAMES},
        {"hold": ["left"], "frames": PRESS_FRAMES}, {"release": True, "frames": NAV_GAP_FRAMES},
    ]


def _nav_to_2x2_slot_steps(slot: int):
    out = []
    if slot in (1, 3):
        out += [{"hold": ["right"], "frames": PRESS_FRAMES}, {"release": True, "frames": NAV_GAP_FRAMES}]
    if slot in (2, 3):
        out += [{"hold": ["down"], "frames": PRESS_FRAMES}, {"release": True, "frames": NAV_GAP_FRAMES}]
    return out


def _press_a_steps(settle=SETTLE_FRAMES, screenshot=False):
    return [
        {"hold": ["a"], "frames": PRESS_FRAMES},
        {"release": True, "frames": settle, "screenshot": screenshot},
    ]


def _run_action(runtime, steps):
    from PIL import Image
    screenshots = []
    with runtime._lock:
        for step in steps:
            if step.get("release"):
                runtime.set_buttons(set())
            if step.get("hold") is not None:
                runtime.set_buttons({button_from_str(b) for b in step["hold"]})
            if step.get("frames", 0) > 0:
                runtime.step(step["frames"])
            if step.get("screenshot"):
                fb = runtime.framebuffer()
                buf = BytesIO()
                Image.fromarray(fb).save(buf, format="PNG")
                screenshots.append(base64.b64encode(buf.getvalue()).decode())
        runtime.set_buttons(set())
    return screenshots


def _press_button(runtime, btn: str, hold_frames=3, settle_frames=80):
    with runtime._lock:
        runtime.set_buttons({button_from_str(btn)})
        runtime.step(hold_frames)
        runtime.set_buttons(set())
        if settle_frames:
            runtime.step(settle_frames)


def _wait_frames(runtime, frames: int):
    with runtime._lock:
        runtime.step(frames)


# --- High-level battle commands (single decisions) ---

@p.route("/battle/advance", methods=["POST"])
def http_battle_advance(ctx):
    """Press A once and settle. Refuses if interactive menu is open."""
    raw = phase_raw(ctx.runtime)
    if raw in (PHASE_ACTION_MENU, PHASE_SECONDARY_MENU):
        return {"error": "refused", "reason": "interactive menu open",
                "phase_id": raw, "state": battle_state_dict(ctx.runtime)}
    shots = _run_action(ctx.runtime, _press_a_steps(screenshot=True))
    return {"state": battle_state_dict(ctx.runtime),
            "phase_id": phase_raw(ctx.runtime),
            "screenshot_b64": shots[0] if shots else None}


@p.route("/battle/use_move/{slot}", methods=["POST"])
def http_battle_use_move(ctx, slot: int):
    from fastapi import HTTPException
    if not 0 <= slot <= 3:
        raise HTTPException(400, detail=f"slot {slot} not in 0..3")
    steps = []
    steps += _home_cursor_steps()
    steps += [{"hold": ["a"], "frames": PRESS_FRAMES},
              {"release": True, "frames": MENU_TRANSITION_FRAMES}]
    steps += _home_cursor_steps()
    steps += _nav_to_2x2_slot_steps(slot)
    steps += _press_a_steps(settle=SETTLE_FRAMES, screenshot=True)
    shots = _run_action(ctx.runtime, steps)
    return {"state": battle_state_dict(ctx.runtime),
            "screenshot_b64": shots[-1] if shots else None}


@p.route("/battle/switch/{party_slot}", methods=["POST"])
def http_battle_switch(ctx, party_slot: int):
    from fastapi import HTTPException
    if not 0 <= party_slot <= 5:
        raise HTTPException(400, detail=f"party_slot {party_slot} not in 0..5")
    if party_slot == 0:
        raise HTTPException(400, detail="can't switch to the active slot")
    steps = []
    steps += _home_cursor_steps()
    steps += [{"hold": ["down"], "frames": PRESS_FRAMES},
              {"release": True, "frames": NAV_GAP_FRAMES}]
    steps += [{"hold": ["a"], "frames": PRESS_FRAMES},
              {"release": True, "frames": PARTY_MENU_SETTLE_FRAMES}]
    steps += [{"hold": ["right"], "frames": PRESS_FRAMES},
              {"release": True, "frames": NAV_GAP_FRAMES}]
    for _ in range(party_slot - 1):
        steps += [{"hold": ["down"], "frames": PRESS_FRAMES},
                  {"release": True, "frames": NAV_GAP_FRAMES}]
    steps += [{"hold": ["a"], "frames": PRESS_FRAMES},
              {"release": True, "frames": MENU_TRANSITION_FRAMES}]
    steps += _press_a_steps(settle=SETTLE_FRAMES, screenshot=True)
    shots = _run_action(ctx.runtime, steps)
    return {"state": battle_state_dict(ctx.runtime),
            "screenshot_b64": shots[-1] if shots else None}


# --- Auto-fight driver (policy B: HP-threshold switch + matchup-best bench) ---

AUTO_HP_SWITCH_THRESHOLD = 0.40
AUTO_MAX_ITERS = 400


def _confirm_out_of_battle(runtime, samples: int = 3, frames_between: int = 20) -> bool:
    if in_battle(runtime):
        return False
    for _ in range(samples - 1):
        _wait_frames(runtime, frames_between)
        if in_battle(runtime):
            return False
    return True


def _detect_forced_switch(runtime) -> bool:
    if not in_battle(runtime):
        return False
    active = read_battle_mon(runtime, BMON_PLAYER_SLOT)
    if active and active.get("hp", 1) > 0:
        return False
    party = party_slots_full(runtime)
    if not any(s and s.get("hp", 0) == 0 for s in party if s):
        return False
    return True


def _visual_position(data_slot: int, active_data_slot: int) -> int:
    if data_slot == active_data_slot:
        return 0
    pos = 1
    for i in range(SLOT_COUNT):
        if i == active_data_slot:
            continue
        if i == data_slot:
            return pos
        pos += 1
    return 0


def _score_move_vs(types_list: list[int], move_type_name: str, power: int) -> float:
    from retrokix.plugins.pokemon.shared.formulas import type_effectiveness
    from retrokix.plugins.pokemon.shared.battle import _type_id_for_name
    type_id = _type_id_for_name(move_type_name or "NORMAL")
    if type_id is None:
        return 0.0
    return float(power) * type_effectiveness(type_id, types_list)


def _best_real_move_score(slot_dict: dict, defender_types: list[int]) -> float:
    if not slot_dict:
        return 0.0
    best = 0.0
    for m in slot_dict.get("moves", []):
        if m.get("pp_current", 0) <= 0:
            continue
        s = _score_move_vs(defender_types, m.get("type") or "NORMAL", m.get("power") or 0)
        if s > best:
            best = s
    return best


def _bench_best_switch(runtime, active_data_slot: int, opp_types: list[int]) -> int | None:
    party = party_slots_full(runtime)
    best_idx = None
    best_score = 0.0
    for i, slot in enumerate(party):
        if slot is None or i == active_data_slot:
            continue
        if slot.get("hp", 0) <= 0:
            continue
        s = _best_real_move_score(slot, opp_types)
        if s > best_score:
            best_score = s
            best_idx = i
    return best_idx if best_score > 0 else None


def _active_party_data_slot(runtime, active_species: int) -> int | None:
    party = party_slots_full(runtime)
    for i, slot in enumerate(party):
        if slot and slot.get("species") == active_species and slot.get("hp", 0) > 0:
            return i
    return None


def _handle_forced_switch(runtime) -> bool:
    party = party_slots_full(runtime)
    fainted_slot = None
    for i, s in enumerate(party):
        if s and s.get("hp", 0) == 0:
            fainted_slot = i
            break
    if fainted_slot is None:
        return False
    opp = read_battle_mon(runtime, OPP_SINGLES_SLOT)
    opp_types = opp["types"] if opp else None
    best_idx = None
    if opp_types:
        best_idx = _bench_best_switch(runtime, fainted_slot, opp_types)
    if best_idx is None:
        for i, s in enumerate(party):
            if i == fainted_slot:
                continue
            if s and s.get("hp", 0) > 0:
                best_idx = i
                break
    if best_idx is None:
        return False
    vis_pos = _visual_position(best_idx, fainted_slot)
    _press_button(runtime, "a", settle_frames=80)
    _press_button(runtime, "right", settle_frames=30)
    for _ in range(vis_pos - 1):
        _press_button(runtime, "down", settle_frames=20)
    _press_button(runtime, "a", settle_frames=120)
    _press_button(runtime, "a", settle_frames=300)
    return True


def _advance_to_decision(runtime, max_iters=AUTO_MAX_ITERS):
    """Loop A/B/wait until phase becomes PHASE_ACTION_MENU or battle ends."""
    forced_switch_attempts = 0
    phase_1_streak = 0
    for _ in range(max_iters):
        if _confirm_out_of_battle(runtime):
            return None
        if _detect_forced_switch(runtime) and forced_switch_attempts < 3:
            forced_switch_attempts += 1
            _handle_forced_switch(runtime)
            phase_1_streak = 0
            continue
        ph = phase_raw(runtime)
        if ph == PHASE_ACTION_MENU:
            return ph
        if ph == PHASE_TRAINER_ANNOUNCE:
            phase_1_streak += 1
            if phase_1_streak == 1:
                _press_button(runtime, "a", settle_frames=80)
            elif phase_1_streak in (2, 3):
                _press_button(runtime, "b", settle_frames=80)
            elif phase_1_streak == 4:
                _press_button(runtime, "right", settle_frames=20)
                for _ in range(5):
                    _press_button(runtime, "down", settle_frames=15)
                _press_button(runtime, "a", settle_frames=150)
            elif phase_1_streak > 8:
                return ph
            else:
                _press_button(runtime, "b", settle_frames=80)
            continue
        phase_1_streak = 0
        if ph == PHASE_SECONDARY_MENU:
            _press_button(runtime, "b", settle_frames=80)
            continue
        if ph in WAIT_PHASES:
            _wait_frames(runtime, 80)
            continue
        if ph in ADVANCEABLE_PHASES:
            _press_button(runtime, "a", settle_frames=80)
            continue
        _press_button(runtime, "b", settle_frames=80)
    return None


def _do_use_move_sequence(runtime, slot: int):
    steps = []
    steps += _home_cursor_steps()
    steps += [{"hold": ["a"], "frames": PRESS_FRAMES},
              {"release": True, "frames": MENU_TRANSITION_FRAMES}]
    steps += _home_cursor_steps()
    steps += _nav_to_2x2_slot_steps(slot)
    steps += _press_a_steps(settle=SETTLE_FRAMES)
    _run_action(runtime, steps)


def _do_switch_sequence(runtime, visual_position: int):
    steps = []
    steps += _home_cursor_steps()
    steps += [{"hold": ["down"], "frames": PRESS_FRAMES},
              {"release": True, "frames": NAV_GAP_FRAMES}]
    steps += [{"hold": ["a"], "frames": PRESS_FRAMES},
              {"release": True, "frames": PARTY_MENU_SETTLE_FRAMES}]
    steps += [{"hold": ["right"], "frames": PRESS_FRAMES},
              {"release": True, "frames": NAV_GAP_FRAMES}]
    for _ in range(visual_position - 1):
        steps += [{"hold": ["down"], "frames": PRESS_FRAMES},
                  {"release": True, "frames": NAV_GAP_FRAMES}]
    steps += [{"hold": ["a"], "frames": PRESS_FRAMES},
              {"release": True, "frames": MENU_TRANSITION_FRAMES}]
    steps += _press_a_steps(settle=SETTLE_FRAMES)
    _run_action(runtime, steps)


def _auto_one_turn(runtime) -> dict:
    p_after = _advance_to_decision(runtime)
    if p_after != PHASE_ACTION_MENU:
        return {"decision": {"action": "noop", "reason": f"phase={p_after}"},
                "phase": p_after, "in_battle": in_battle(runtime)}

    active = read_battle_mon(runtime, BMON_PLAYER_SLOT)
    opp = read_battle_mon(runtime, OPP_SINGLES_SLOT)
    if not active or not opp:
        return {"decision": {"action": "noop", "reason": "could not read battlers"},
                "in_battle": in_battle(runtime)}

    hp_frac = active["hp"] / max(1, active["max_hp"])
    active_data_slot = _active_party_data_slot(runtime, active["species"])

    decision = None
    if hp_frac < AUTO_HP_SWITCH_THRESHOLD and active_data_slot is not None:
        bench_data_slot = _bench_best_switch(runtime, active_data_slot, opp["types"])
        if bench_data_slot is not None:
            vis_pos = _visual_position(bench_data_slot, active_data_slot)
            decision = {"action": "switch", "from_data_slot": active_data_slot,
                        "to_data_slot": bench_data_slot, "visual_position": vis_pos,
                        "active_hp_frac": round(hp_frac, 3)}
            _do_switch_sequence(runtime, vis_pos)
    if decision is None:
        from retrokix.plugins.pokemon.shared.data import load_moves
        from retrokix.plugins.pokemon.shared.formulas import type_effectiveness
        from retrokix.plugins.pokemon.shared.battle import _type_id_for_name
        moves_table = load_moves()
        best_slot = 0
        best_score = -1.0
        for i, mid in enumerate(active["move_ids"]):
            if mid == 0 or active["pp"][i] <= 0:
                continue
            rec = moves_table.get(str(mid)) or {}
            type_id = _type_id_for_name(rec.get("type", "NORMAL"))
            power = rec.get("power", 0) or 0
            mul = type_effectiveness(type_id, opp["types"]) if type_id is not None else 1.0
            score = float(power) * mul
            if score > best_score:
                best_score = score
                best_slot = i
        decision = {"action": "use_move", "menu_slot": best_slot, "score": round(best_score, 2)}
        _do_use_move_sequence(runtime, best_slot)

    final_phase = _advance_to_decision(runtime)
    return {"decision": decision, "phase_after": final_phase,
            "in_battle": in_battle(runtime), "state": battle_state_dict(runtime)}


@p.route("/battle/auto/turn", methods=["POST"])
def http_auto_turn(ctx):
    return _auto_one_turn(ctx.runtime)


@p.route("/battle/auto/opponent", methods=["POST"])
def http_auto_opponent(ctx):
    if not in_battle(ctx.runtime):
        return {"error": "not in battle"}
    start_opp = read_battle_mon(ctx.runtime, OPP_SINGLES_SLOT)
    start_species = start_opp["species"] if start_opp else None
    turns = []
    noops = 0
    for _ in range(20):
        if not in_battle(ctx.runtime):
            break
        result = _auto_one_turn(ctx.runtime)
        turns.append(result)
        if result.get("decision", {}).get("action") not in ("use_move", "switch"):
            noops += 1
            if noops >= 3:
                break
        else:
            noops = 0
        if not result.get("in_battle"):
            break
        cur_opp = read_battle_mon(ctx.runtime, OPP_SINGLES_SLOT)
        if cur_opp and cur_opp["species"] != start_species:
            break
    return {"turns": turns, "in_battle": in_battle(ctx.runtime),
            "state": battle_state_dict(ctx.runtime)}


@p.route("/battle/auto/full", methods=["POST"])
def http_auto_full(ctx):
    if not in_battle(ctx.runtime):
        return {"error": "not in battle"}
    turns = []
    noops = 0
    for _ in range(60):
        if not in_battle(ctx.runtime):
            break
        result = _auto_one_turn(ctx.runtime)
        turns.append(result)
        if result.get("decision", {}).get("action") not in ("use_move", "switch"):
            noops += 1
            if noops >= 3:
                break
        else:
            noops = 0
        if not result.get("in_battle"):
            break
    return {"turn_count": len(turns), "turns": turns,
            "in_battle": in_battle(ctx.runtime),
            "state": battle_state_dict(ctx.runtime)}


# --- Hotkey bindings: singleton background thread ---

_AUTO_RUNNER_LOCK: threading.Lock | None = None


def _run_async(fn, *args):
    global _AUTO_RUNNER_LOCK
    if _AUTO_RUNNER_LOCK is None:
        _AUTO_RUNNER_LOCK = threading.Lock()
    if not _AUTO_RUNNER_LOCK.acquire(blocking=False):
        return
    def wrapper():
        try:
            fn(*args)
        finally:
            _AUTO_RUNNER_LOCK.release()
    threading.Thread(target=wrapper, daemon=True).start()


def _auto_turn_handler(ctx):
    ctx.log("[J] auto/turn fired")
    if not in_battle(ctx.runtime):
        ctx.log("[J] not in battle — skipping")
        return
    _run_async(_auto_one_turn, ctx.runtime)


def _auto_opponent_handler(ctx):
    ctx.log("[K] auto/opponent fired")
    if not in_battle(ctx.runtime):
        ctx.log("[K] not in battle — skipping")
        return
    def runner(rt):
        start = read_battle_mon(rt, OPP_SINGLES_SLOT)
        start_species = start["species"] if start else None
        noops = 0
        for _ in range(20):
            if _confirm_out_of_battle(rt):
                break
            result = _auto_one_turn(rt)
            decision = result.get("decision") or {}
            action = decision.get("action") if isinstance(decision, dict) else None
            if action not in ("use_move", "switch"):
                noops += 1
                if noops >= 3:
                    ctx.log("[K] stop: 3 noops")
                    break
            else:
                noops = 0
            cur_opp = read_battle_mon(rt, OPP_SINGLES_SLOT)
            if cur_opp is None:
                break
            if start_species is not None and cur_opp["species"] != start_species:
                ctx.log(f"[K] stop: opp species {start_species}→{cur_opp['species']}")
                break
        ctx.log("[K] done")
    _run_async(runner, ctx.runtime)


def _auto_full_handler(ctx):
    ctx.log("[L] auto/full fired")
    if not in_battle(ctx.runtime):
        ctx.log("[L] not in battle — skipping")
        return
    def runner(rt):
        noops = 0
        for i in range(60):
            if _confirm_out_of_battle(rt):
                ctx.log(f"[L] exited battle after {i} turns")
                return
            result = _auto_one_turn(rt)
            decision = result.get("decision") or {}
            action = decision.get("action") if isinstance(decision, dict) else None
            if action not in ("use_move", "switch"):
                noops += 1
                if noops >= 3:
                    ctx.log("[L] stop: 3 noops")
                    break
            else:
                noops = 0
        ctx.log("[L] done")
    _run_async(runner, ctx.runtime)


p.on_key("J")(_auto_turn_handler)
p.on_key("K")(_auto_opponent_handler)
# Bind /battle/auto/full to multiple keys (L can collide with a macro slot)
p.on_key("L")(_auto_full_handler)
p.on_key("P")(_auto_full_handler)
p.on_key("Y")(_auto_full_handler)


@p.on_setup
def setup(ctx):
    ctx.log("pokemon.emerald_driver loaded (auto-fight: J=turn, K=opponent, L/P/Y=full)")
