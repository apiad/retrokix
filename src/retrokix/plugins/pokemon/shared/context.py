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
            "next_evolution": t.get("next_evolution"),
            "next_move": t.get("next_move"),
        }
        for t in party
        if t
    ]

    # Catchable on the current map but not yet in the dex (encounters × dex).
    if dex and enc:
        from retrokix.plugins.pokemon.shared import pokedex_model as _pm

        caught_nat = dex["caught"]
        wild = {r["species"] for m in ("land", "water", "fishing") for r in enc[m]}
        uncaught = [
            _pm.species_name(sp) for sp in wild if _pm.national_of(sp) not in caught_nat
        ]
        ctx["catchable_here"] = sorted(set(uncaught))

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
        opponents = _battle.active_opponents(runtime)
        ctx["battle"] = {
            "double": _battle.is_double(runtime),
            "opponents": [{"name": o["species_name"], "level": o["level"]} for o in opponents],
            "opponent_species": [o["species"] for o in opponents],
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

    evos = []
    learns = []
    for p in party:
        ev = p.get("next_evolution")
        if ev and ev.get("trigger") == "LEVEL" and ev.get("in") is not None:
            evos.append(f"{p['name']} → {ev['target_name']} in {ev['in']} lvl (L{ev['at_level']})")
        nm = p.get("next_move")
        if nm and nm.get("in") is not None and nm["in"] <= 5:
            learns.append(f"{p['name']} learns {nm['move_name']} at L{nm['level']}")
    if evos:
        lines.append("Evolving soon: " + "; ".join(evos))
    if learns:
        lines.append("Learning a move soon: " + "; ".join(learns))

    ch = ctx.get("catchable_here") or []
    if ch:
        lines.append("Catchable on this map, not yet in your dex: " + ", ".join(ch))
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


def relevant_species(ctx: dict, question: str) -> list[int]:
    """Internal species ids worth injecting for a free-form question: the party,
    the current battle opponents, and any species named in the question."""
    from retrokix.plugins.pokemon.shared import pokedex_model as _pm

    ids: list[int] = [p["species"] for p in ctx.get("party", []) if p.get("species")]
    bt = ctx.get("battle") or {}
    ids += bt.get("opponent_species", [])
    q = (question or "").lower()
    if q:
        ids += [sid for sid in _pm.species_ids() if _pm.species_name(sid).lower() in q]

    seen: list[int] = []
    for i in ids:
        if i and i not in seen:
            seen.append(i)
    return seen[:8]


def pokedex_brief(species_id: int) -> str:
    """A compact one-line Pokédex summary (plain text) for the LLM."""
    from retrokix.plugins.pokemon.shared import pokedex_model as _pm

    d = _pm.assemble_detail(species_id)
    if not d:
        return ""
    m = d["matchups"]
    weak = [f"{t} x4" for t in m["weak_x4"]] + [f"{t} x2" for t in m["weak_x2"]]
    bits = [
        f"{d['name']} (#{d['national']} {'/'.join(d['types'])}, BST {d['total']})",
        f"abilities {', '.join(d['abilities']) or '—'}",
    ]
    if weak:
        bits.append("weak: " + ", ".join(weak))
    if d["evolves_into"]:
        bits.append("evolves into " + ", ".join(f"{e['name']} ({e['method']})" for e in d["evolves_into"]))
    elif d["evolves_from"]:
        bits.append(f"evolves from {d['evolves_from']['name']}")
    return "; ".join(bits)


def build_ask_prompt(ctx: dict, question: str) -> str:
    """The user message for the Ask panel: state + relevant Pokédex + question."""
    parts = [context_prompt(ctx)]
    species = relevant_species(ctx, question)
    briefs = [b for b in (pokedex_brief(s) for s in species) if b]
    if briefs:
        parts.append("\nRelevant Pokédex data:")
        parts.extend("  - " + b for b in briefs)
    parts.append(f"\nPlayer's question: {question}")
    return "\n".join(parts)


def salient_signature(ctx: dict) -> tuple:
    """Auto-mode change key: location, in-battle, badge count, key-item set.
    Excludes HP / levels / step counts so it only fires on meaningful changes."""
    keys = frozenset(
        i.get("id", i.get("name")) for i in (ctx.get("key_items") or [])
    )
    return (ctx.get("location"), bool(ctx.get("battle")), ctx.get("badges", 0), keys)
