"""Game-state context for the LLM Hints panel.

`build_context(runtime)` aggregates the live state from the other shared
modules; `context_prompt(ctx)` renders it as the LLM user message (pure);
`salient_signature(ctx)` is the Auto-mode change detector (pure).
"""
from __future__ import annotations

from retrokix.plugins.pokemon.shared import bag as _bag
from retrokix.plugins.pokemon.shared import battle as _battle
from retrokix.plugins.pokemon.shared import encounters as _enc
from retrokix.plugins.pokemon.shared import gyms as _gyms
from retrokix.plugins.pokemon.shared import pokedex as _dex
from retrokix.plugins.pokemon.shared import world as _world
from retrokix.plugins.pokemon.shared.party import SLOT_COUNT, read_slot


def build_context(runtime) -> dict:
    """A structured snapshot of the current game state, or {} if unreadable."""
    ctx: dict = {}
    w = _world.read_world(runtime)
    if w:
        ctx["trainer"] = w["trainer"]
        ctx["money"] = w["money"]
        ctx["badges"] = w["badges"]["count"]
        ctx["play_time"] = w["play_time"]

    b = _bag.read_bag(runtime) or {}
    ctx["balls"] = b.get("Balls", [])
    ctx["key_items"] = b.get("Key", [])

    dex = _dex.read_dex(runtime)
    if dex:
        caught, seen, total = _dex.counts(dex)
        ctx["dex"] = {"caught": caught, "seen": seen, "total": total}

    enc = _enc.read_encounters(runtime)
    if enc:
        ctx["location"] = enc["location"]
        ctx["wild_land"] = [r["name"] for r in enc["land"]]

    party = [read_slot(runtime, i) for i in range(SLOT_COUNT)]
    ctx["party"] = [
        {
            "name": t["species_name"], "species": t["species"], "level": t["level"],
            "hp": t["hp"], "max_hp": t["max_hp"],
        }
        for t in party
        if t
    ]

    ctx["location_name"] = _world.location_name(runtime)

    # Grounded gym facts: the next gym (by badge count) + a computed type plan so
    # the LLM never invents matchups.
    badges = ctx.get("badges")
    if badges is not None:
        gym = _gyms.next_gym(badges)
        if gym:
            ctx["next_gym"] = gym
            ctx["gym_plan"] = _gyms.gym_plan(gym["type_id"], ctx["party"])

    if _battle.is_in_battle(runtime):
        ctx["battle"] = {
            "double": _battle.is_double(runtime),
            "opponents": [
                {"name": o["species_name"], "level": o["level"]}
                for o in _battle.active_opponents(runtime)
            ],
            "enemy_team": [s["species_name"] for s in _battle.enemy_party(runtime)],
        }
    return ctx


def context_prompt(ctx: dict) -> str:
    lines = []
    t = ctx.get("trainer")
    if t:
        lines.append(f"Trainer: {t['name']} ({t['gender']}), ID {t['id']}")
    if "money" in ctx:
        lines.append(f"Money: P{ctx['money']}   Badges: {ctx.get('badges', 0)}/8")
    pt = ctx.get("play_time")
    if pt:
        lines.append(f"Play time: {pt['h']}h{pt['m']:02d}m")
    d = ctx.get("dex")
    if d:
        lines.append(f"Pokedex: {d['caught']} caught / {d['seen']} seen / {d['total']}")
    if ctx.get("location_name"):
        wl = ctx.get("wild_land") or []
        here = f"; wild grass here: {', '.join(wl)}" if wl else "; no wild encounters on this map"
        lines.append(f"Location: {ctx['location_name']}{here}")
    party = ctx.get("party") or []
    if party:
        lines.append("Party:")
        for p in party:
            lines.append(f"  - {p['name']} Lv{p['level']} ({p['hp']}/{p['max_hp']} HP)")
    balls = ctx.get("balls") or []
    lines.append("Balls: " + (", ".join(f"{i['name']} x{i['qty']}" for i in balls) or "none"))
    keys = ctx.get("key_items") or []
    lines.append("Key items: " + (", ".join(i["name"] for i in keys) or "none"))
    ng = ctx.get("next_gym")
    if ng:
        gp = ctx.get("gym_plan") or {}
        lines.append(
            f"NEXT GYM: {ng['leader']} in {ng['town']} — {ng['type']}-type "
            f"(ace ~Lv{ng['ace_level']})"
        )
        if gp.get("se_types"):
            lines.append(
                f"  [authoritative] Super-effective vs {ng['type']}: "
                f"{', '.join(gp['se_types'])} — catch/use these types"
            )
        if gp.get("resist"):
            lines.append(f"  [authoritative] Your mons that resist {ng['type']}: {', '.join(gp['resist'])}")
        if gp.get("weak"):
            lines.append(f"  [authoritative] Your mons WEAK to {ng['type']}: {', '.join(gp['weak'])}")

    bt = ctx.get("battle")
    if bt:
        opp = ", ".join(f"{o['name']} Lv{o['level']}" for o in bt["opponents"])
        kind = "double" if bt["double"] else "single"
        lines.append(f"IN BATTLE ({kind}) vs {opp}; full enemy team: {', '.join(bt['enemy_team'])}")
    return "\n".join(lines)


def salient_signature(ctx: dict) -> tuple:
    """Auto-mode change key: location, in-battle, badge count, key-item set.
    Excludes HP / levels / step counts so it only fires on meaningful changes."""
    keys = frozenset(
        i.get("id", i.get("name")) for i in (ctx.get("key_items") or [])
    )
    return (ctx.get("location"), bool(ctx.get("battle")), ctx.get("badges", 0), keys)
