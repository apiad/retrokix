#!/usr/bin/env python3
"""Extract structured JSON tables from a local pokeemerald clone.

Reads pokeemerald source files and emits the JSON tables that the
gbax.plugins.emerald_party plugin loads at runtime. Idempotent — run
after a `git pull` of pokeemerald.

Data is © Nintendo / Game Freak / Creatures. Source:
https://github.com/pret/pokeemerald
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_POKEEMERALD = Path("/home/apiad/Workspace/.playground/pokeemerald")
OUT_DIR = Path(__file__).parent.parent / "src" / "gbax" / "data"

GROWTH_RANK = {
    "MEDIUM_FAST": 0, "ERRATIC": 1, "FLUCTUATING": 2,
    "MEDIUM_SLOW": 3, "FAST": 4, "SLOW": 5,
}

# Type names in canonical pokeemerald ordering — drives type chart indexing.
# Source: include/constants/battle.h (TYPE_NORMAL=0 .. TYPE_DARK=17, with
# TYPE_MYSTERY=9 as separator). We preserve the integer values verbatim.
TYPE_NAMES = {
    0: "Normal", 1: "Fighting", 2: "Flying", 3: "Poison", 4: "Ground",
    5: "Rock", 6: "Bug", 7: "Ghost", 8: "Steel", 9: "???",
    10: "Fire", 11: "Water", 12: "Grass", 13: "Electric",
    14: "Psychic", 15: "Ice", 16: "Dragon", 17: "Dark",
}

# Move effectiveness opcodes from include/constants/battle.h
TYPE_MUL_NO_EFFECT = 0
TYPE_MUL_NOT_EFFECTIVE = 5
TYPE_MUL_NORMAL = 10
TYPE_MUL_SUPER_EFFECTIVE = 20
TYPE_FORESIGHT = 0xFE   # marker: entries past this only apply under Foresight
TYPE_ENDTABLE = 0xFF


def load_species_ids(root: Path) -> dict[str, int]:
    out = {}
    for line in (root / "include/constants/species.h").read_text().splitlines():
        m = re.match(r"^#define\s+SPECIES_([A-Z0-9_]+)\s+(\d+)\s*$", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def load_move_ids(root: Path) -> dict[str, int]:
    out = {}
    for line in (root / "include/constants/moves.h").read_text().splitlines():
        m = re.match(r"^#define\s+MOVE_([A-Z0-9_]+)\s+(\d+)\s*$", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def load_item_ids(root: Path) -> dict[str, int]:
    out = {}
    for line in (root / "include/constants/items.h").read_text().splitlines():
        m = re.match(r"^#define\s+ITEM_([A-Z0-9_]+)\s+(\d+)\s*$", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def load_ability_ids(root: Path) -> dict[str, int]:
    out = {}
    for line in (root / "include/constants/abilities.h").read_text().splitlines():
        m = re.match(r"^#define\s+ABILITY_([A-Z0-9_]+)\s+(\d+)\s*$", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def load_type_ids(root: Path) -> dict[str, int]:
    """Return full TYPE_X → int (keys include the TYPE_ prefix)."""
    out = {}
    for line in (root / "include/constants/pokemon.h").read_text().splitlines():
        m = re.match(r"^#define\s+(TYPE_[A-Z0-9_]+)\s+(\d+)\s*$", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def title(name: str) -> str:
    """SPECIES_MR_MIME → Mr-Mime style. Preserve numerals."""
    return name.replace("_", " ").title().replace(" ", "-")


def parse_species_info(root: Path, species_ids: dict[str, int]) -> dict:
    """Parse src/data/pokemon/species_info.h into per-species records.

    Walks blocks `[SPECIES_X] = { ... }`, captures all `.field = value` pairs
    that we care about. Brace-counting since types/abilities are nested.
    """
    text = (root / "src/data/pokemon/species_info.h").read_text()
    out = {}
    # Token-walk: find each [SPECIES_X] = { and balance braces.
    i = 0
    pat_head = re.compile(r"\[SPECIES_([A-Z0-9_]+)\]\s*=\s*\{")
    while True:
        m = pat_head.search(text, i)
        if not m:
            break
        name = m.group(1)
        # Find matching close brace.
        start = m.end()
        depth = 1
        j = start
        while j < len(text) and depth > 0:
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            j += 1
        body = text[start:j - 1]
        i = j
        if name not in species_ids:
            continue
        rec = _parse_species_block(body)
        if rec:
            out[species_ids[name]] = rec
    return out


def _parse_species_block(body: str) -> dict:
    rec = {}

    def grab_int(field):
        m = re.search(rf"\.{field}\s*=\s*(-?\d+)", body)
        return int(m.group(1)) if m else None

    def grab_name(field):
        m = re.search(rf"\.{field}\s*=\s*([A-Z_][A-Z0-9_]+)", body)
        return m.group(1) if m else None

    for field in (
        "baseHP", "baseAttack", "baseDefense", "baseSpeed",
        "baseSpAttack", "baseSpDefense",
        "catchRate", "expYield", "eggCycles", "safariZoneFleeRate",
        "evYield_HP", "evYield_Attack", "evYield_Defense",
        "evYield_Speed", "evYield_SpAttack", "evYield_SpDefense",
    ):
        v = grab_int(field)
        if v is not None:
            rec[field] = v

    # genderRatio is one of the PERCENT_FEMALE() / MON_MALE / MON_GENDERLESS macros
    m = re.search(r"\.genderRatio\s*=\s*([A-Z_]+|PERCENT_FEMALE\([^)]+\))", body)
    if m:
        rec["genderRatio"] = m.group(1)

    growth = grab_name("growthRate")
    if growth and growth.startswith("GROWTH_"):
        rec["growthRate"] = GROWTH_RANK.get(growth[len("GROWTH_"):], 0)

    base_friendship = grab_name("friendship")
    if base_friendship:
        rec["friendshipMacro"] = base_friendship

    # types = { TYPE_A, TYPE_B }
    m = re.search(r"\.types\s*=\s*\{\s*TYPE_([A-Z_]+)\s*,\s*TYPE_([A-Z_]+)\s*\}", body)
    if m:
        rec["types"] = [m.group(1), m.group(2)]

    # abilities = { ABILITY_A, ABILITY_B }
    m = re.search(r"\.abilities\s*=\s*\{\s*ABILITY_([A-Z_]+)\s*,\s*ABILITY_([A-Z_]+)\s*\}", body)
    if m:
        rec["abilities"] = [m.group(1), m.group(2)]

    # eggGroups
    m = re.search(r"\.eggGroups\s*=\s*\{\s*EGG_GROUP_([A-Z_]+)\s*,\s*EGG_GROUP_([A-Z_]+)\s*\}", body)
    if m:
        rec["eggGroups"] = [m.group(1), m.group(2)]

    for field in ("itemCommon", "itemRare"):
        v = grab_name(field)
        if v:
            rec[field] = v

    return rec


def parse_evolutions(root: Path, species_ids: dict[str, int]) -> dict:
    """Parse src/data/pokemon/evolution.h.

    Each row: [SPECIES_X] = {{EVO_TYPE, param, SPECIES_TARGET}, ...} —
    up to 5 evolution slots per species, terminated by {0, 0, 0}.
    """
    text = (root / "src/data/pokemon/evolution.h").read_text()
    out = {}
    pat = re.compile(
        r"\[SPECIES_([A-Z0-9_]+)\]\s*=\s*\{(.*?)\},",
        re.DOTALL,
    )
    for m in pat.finditer(text):
        name = m.group(1)
        if name not in species_ids:
            continue
        body = m.group(2)
        slots = []
        for trip in re.finditer(
            r"\{\s*EVO_([A-Z0-9_]+)\s*,\s*(\d+)\s*,\s*SPECIES_([A-Z0-9_]+)\s*\}",
            body,
        ):
            trigger, param, target = trip.group(1), int(trip.group(2)), trip.group(3)
            if target not in species_ids:
                continue
            slots.append({
                "trigger": trigger,
                "param": param,
                "target_species": species_ids[target],
                "target_name": title(target),
            })
        if slots:
            out[species_ids[name]] = slots
    return out


def parse_levelup_learnsets(root: Path, species_ids: dict[str, int],
                             move_ids: dict[str, int]) -> dict:
    """Parse src/data/pokemon/level_up_learnsets.h.

    Each species has `static const u16 sXxxLevelUpLearnset[]` filled with
    LEVEL_UP_MOVE(lvl, MOVE_X). Decode each entry; output species_id →
    [{level, move_id, move_name}, ...] sorted by level.
    """
    text = (root / "src/data/pokemon/level_up_learnsets.h").read_text()
    out = {}
    # Match each named array: static const u16 sNAMELevelUpLearnset[] = { ... };
    pat = re.compile(
        r"static const u16 s([A-Za-z0-9_]+?)LevelUpLearnset\[\]\s*=\s*\{(.*?)\};",
        re.DOTALL,
    )
    for m in pat.finditer(text):
        sp_pascal = m.group(1)
        body = m.group(2)
        # Convert PascalCase species name → SCREAMING_SNAKE for species lookup.
        # E.g. "MrMime" → "MR_MIME", "PorygonZ" handled but Emerald doesn't have it.
        sp_caps = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", sp_pascal).upper()
        if sp_caps not in species_ids:
            # Try common aliases (Nidoran etc).
            continue
        moves = []
        for mm in re.finditer(
            r"LEVEL_UP_MOVE\(\s*(\d+)\s*,\s*MOVE_([A-Z0-9_]+)\s*\)", body
        ):
            level = int(mm.group(1))
            mv = mm.group(2)
            if mv not in move_ids:
                continue
            moves.append({
                "level": level,
                "move_id": move_ids[mv],
                "move_name": title(mv),
            })
        moves.sort(key=lambda r: r["level"])
        if moves:
            out[species_ids[sp_caps]] = moves
    return out


def parse_moves(root: Path, move_ids: dict[str, int]) -> dict:
    """Parse src/data/battle_moves.h.

    Each entry: [MOVE_X] = { .effect = ..., .power = ..., ... }.
    """
    text = (root / "src/data/battle_moves.h").read_text()
    out = {}
    pat_head = re.compile(r"\[MOVE_([A-Z0-9_]+)\]\s*=\s*\{")
    i = 0
    while True:
        m = pat_head.search(text, i)
        if not m:
            break
        name = m.group(1)
        start = m.end()
        depth = 1
        j = start
        while j < len(text) and depth > 0:
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            j += 1
        body = text[start:j - 1]
        i = j
        if name not in move_ids:
            continue
        rec = {"name": title(name)}
        for field, key in [
            ("power", "power"),
            ("accuracy", "accuracy"),
            ("pp", "pp"),
            ("priority", "priority"),
            ("secondaryEffectChance", "secondary_chance"),
        ]:
            mm = re.search(rf"\.{field}\s*=\s*(\d+)", body)
            if mm:
                rec[key] = int(mm.group(1))
        mt = re.search(r"\.type\s*=\s*TYPE_([A-Z_]+)", body)
        if mt:
            rec["type"] = mt.group(1)
        me = re.search(r"\.effect\s*=\s*EFFECT_([A-Z0-9_]+)", body)
        if me:
            rec["effect"] = me.group(1)
        mtarget = re.search(r"\.target\s*=\s*MOVE_TARGET_([A-Z_]+)", body)
        if mtarget:
            rec["target"] = mtarget.group(1)
        # Flags: split on |
        mf = re.search(r"\.flags\s*=\s*([A-Z_0-9 |]+)", body)
        if mf:
            flags = [f.strip()[5:] for f in mf.group(1).split("|") if f.strip().startswith("FLAG_")]
            if flags:
                rec["flags"] = flags
        out[move_ids[name]] = rec
    return out


def parse_type_chart(root: Path, type_ids: dict[str, int]) -> list[list[int]]:
    """Parse gTypeEffectiveness from src/battle_main.c — list of (atk, def, mul)
    triples until TYPE_FORESIGHT marker (post-Foresight section excluded).
    """
    text = (root / "src/battle_main.c").read_text()
    m = re.search(r"const u8 gTypeEffectiveness\[\d+\]\s*=\s*\{(.*?)\};", text, re.DOTALL)
    if not m:
        return []
    body = m.group(1)
    # Find TYPE_FORESIGHT and stop there.
    tokens = []
    for line in body.splitlines():
        line = re.sub(r"//.*", "", line).strip()
        if not line:
            continue
        for tok in line.split(","):
            tok = tok.strip()
            if not tok:
                continue
            tokens.append(tok)
    # Resolve names to ints.
    resolved = []
    for tok in tokens:
        if tok in type_ids:
            resolved.append(type_ids[tok])
        elif tok == "TYPE_MUL_NO_EFFECT":
            resolved.append(TYPE_MUL_NO_EFFECT)
        elif tok == "TYPE_MUL_NOT_EFFECTIVE":
            resolved.append(TYPE_MUL_NOT_EFFECTIVE)
        elif tok == "TYPE_MUL_NORMAL":
            resolved.append(TYPE_MUL_NORMAL)
        elif tok == "TYPE_MUL_SUPER_EFFECTIVE":
            resolved.append(TYPE_MUL_SUPER_EFFECTIVE)
        elif tok == "TYPE_FORESIGHT":
            resolved.append(TYPE_FORESIGHT)
        elif tok == "TYPE_ENDTABLE":
            resolved.append(TYPE_ENDTABLE)
        elif tok.isdigit():
            resolved.append(int(tok))
        # else: unknown token, skip silently
    # Include both pre- and post-Foresight sections (post-Foresight entries
    # are Normal→Ghost and Fighting→Ghost = 0×; they apply by DEFAULT and are
    # only REMOVED when Foresight is used). The marker itself is skipped.
    triples = []
    i = 0
    while i + 2 < len(resolved):
        atk = resolved[i]
        if atk == TYPE_ENDTABLE:
            break
        if atk == TYPE_FORESIGHT:
            i += 3
            continue
        triples.append([atk, resolved[i + 1], resolved[i + 2]])
        i += 3
    return triples


def parse_natures(root: Path) -> dict:
    """Parse gNatureStatTable from src/pokemon.c (or src/pokemon_2.c).
    Returns {nature_id: [hp_mod, atk_mod, def_mod, spd_mod, spa_mod, spdef_mod]}
    where mod ∈ {-1, 0, +1} matching the 0.9/1.0/1.1 multiplier semantics.

    Pokémon ordering: index = nature (0=Hardy .. 24=Quirky).
    """
    # Hardcoded — pokeemerald's table is well-known and never changes.
    # Order: HARDY, LONELY, BRAVE, ADAMANT, NAUGHTY, BOLD, DOCILE, RELAXED,
    #        IMPISH, LAX, TIMID, HASTY, SERIOUS, JOLLY, NAIVE, MODEST, MILD,
    #        QUIET, BASHFUL, RASH, CALM, GENTLE, SASSY, CAREFUL, QUIRKY
    # Stats: [atk, def, spe, spa, spd]  (HP unaffected, no HP-mod nature exists)
    NATURE_NAMES = [
        "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
        "Bold", "Docile", "Relaxed", "Impish", "Lax",
        "Timid", "Hasty", "Serious", "Jolly", "Naive",
        "Modest", "Mild", "Quiet", "Bashful", "Rash",
        "Calm", "Gentle", "Sassy", "Careful", "Quirky",
    ]
    # Source: gNatureStatTable in src/pokemon.c
    TABLE = [
        [0, 0, 0, 0, 0],     # Hardy
        [+1, -1, 0, 0, 0],   # Lonely
        [+1, 0, -1, 0, 0],   # Brave
        [+1, 0, 0, -1, 0],   # Adamant
        [+1, 0, 0, 0, -1],   # Naughty
        [-1, +1, 0, 0, 0],   # Bold
        [0, 0, 0, 0, 0],     # Docile
        [0, +1, -1, 0, 0],   # Relaxed
        [0, +1, 0, -1, 0],   # Impish
        [0, +1, 0, 0, -1],   # Lax
        [-1, 0, +1, 0, 0],   # Timid
        [0, -1, +1, 0, 0],   # Hasty
        [0, 0, 0, 0, 0],     # Serious
        [0, 0, +1, -1, 0],   # Jolly
        [0, 0, +1, 0, -1],   # Naive
        [-1, 0, 0, +1, 0],   # Modest
        [0, -1, 0, +1, 0],   # Mild
        [0, 0, -1, +1, 0],   # Quiet
        [0, 0, 0, 0, 0],     # Bashful
        [0, 0, 0, +1, -1],   # Rash
        [-1, 0, 0, 0, +1],   # Calm
        [0, -1, 0, 0, +1],   # Gentle
        [0, 0, -1, 0, +1],   # Sassy
        [0, 0, 0, -1, +1],   # Careful
        [0, 0, 0, 0, 0],     # Quirky
    ]
    return {str(i): {"name": NATURE_NAMES[i], "mods": TABLE[i]} for i in range(25)}


def parse_items(root: Path, item_ids: dict[str, int]) -> dict:
    text = (root / "src/data/items.h").read_text()
    out = {}
    pat_head = re.compile(r"\[ITEM_([A-Z0-9_]+)\]\s*=\s*\{")
    i = 0
    while True:
        m = pat_head.search(text, i)
        if not m:
            break
        name = m.group(1)
        start = m.end()
        depth = 1
        j = start
        while j < len(text) and depth > 0:
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            j += 1
        body = text[start:j - 1]
        i = j
        if name not in item_ids:
            continue
        rec = {"name": title(name)}
        for field in ("price", "secondaryId", "holdEffectParam", "importance"):
            mm = re.search(rf"\.{field}\s*=\s*(\d+)", body)
            if mm:
                rec[field] = int(mm.group(1))
        mp = re.search(r"\.pocket\s*=\s*POCKET_([A-Z_]+)", body)
        if mp:
            rec["pocket"] = mp.group(1)
        mh = re.search(r"\.holdEffect\s*=\s*HOLD_EFFECT_([A-Z_]+)", body)
        if mh:
            rec["holdEffect"] = mh.group(1)
        out[item_ids[name]] = rec
    return out


def parse_abilities(ability_ids: dict[str, int]) -> dict:
    return {str(v): title(k) for k, v in ability_ids.items()}


def parse_mapsec(root: Path) -> dict:
    """Region map section ID → display name. The constants file gives IDs;
    sections.json gives entries. We emit ID → 'Route 104'-style names.
    """
    # Two paths to try, pokeemerald has both .json and a header.
    sections_path = root / "src/data/region_map/region_map_sections.json"
    constants_path = root / "include/constants/region_map_sections.h"
    out = {}
    if constants_path.exists():
        for line in constants_path.read_text().splitlines():
            m = re.match(r"^#define\s+MAPSEC_([A-Z0-9_]+)\s+(\d+)\s*$", line)
            if m:
                out[m.group(2)] = title(m.group(1))
    if sections_path.exists():
        try:
            data = json.loads(sections_path.read_text())
            # Schema varies; if entries are dicts with id+name, override.
            entries = data.get("map_sections") or data.get("sections") or data
            if isinstance(entries, list):
                for e in entries:
                    if isinstance(e, dict) and "id" in e:
                        key = str(e["id"]) if isinstance(e["id"], int) else str(e["id"]).removeprefix("MAPSEC_")
                        out[key] = e.get("name", out.get(key, "?"))
        except json.JSONDecodeError:
            pass
    return out


def git_sha(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def wrap(table: dict | list, source_path: str, root: Path, description: str):
    return {
        "__source__": source_path,
        "__upstream__": "https://github.com/pret/pokeemerald",
        "__upstream_sha__": git_sha(root),
        "__description__": description,
        "__note__": (
            "Data © Nintendo / Game Freak / Creatures. "
            "This JSON is derived from the pokeemerald community decompilation "
            "for informational use only."
        ),
        "data": table,
    }


def dump(name: str, payload: dict):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    size = path.stat().st_size
    entries = len(payload.get("data") or [])
    print(f"  wrote {name}: {entries} entries, {size:,} bytes")


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=DEFAULT_POKEEMERALD,
                    help=f"pokeemerald clone (default: {DEFAULT_POKEEMERALD})")
    args = ap.parse_args()
    root = args.root
    if not (root / "include/constants/species.h").exists():
        print(f"error: {root} does not look like a pokeemerald clone", file=sys.stderr)
        sys.exit(1)

    print(f"reading from {root} (sha {git_sha(root)[:8]})")
    print(f"writing to   {OUT_DIR}")

    species_ids = load_species_ids(root)
    move_ids = load_move_ids(root)
    item_ids = load_item_ids(root)
    ability_ids = load_ability_ids(root)
    type_ids = load_type_ids(root)
    print(f"  resolved {len(species_ids)} species, {len(move_ids)} moves, "
          f"{len(item_ids)} items, {len(ability_ids)} abilities, "
          f"{len(type_ids)} types")

    dump("emerald_species_info.json", wrap(
        parse_species_info(root, species_ids),
        "src/data/pokemon/species_info.h", root,
        "Per-species base stats, types, abilities, EV yield, etc."))

    dump("emerald_evolutions.json", wrap(
        parse_evolutions(root, species_ids),
        "src/data/pokemon/evolution.h", root,
        "Evolution triggers + targets per species."))

    dump("emerald_levelup.json", wrap(
        parse_levelup_learnsets(root, species_ids, move_ids),
        "src/data/pokemon/level_up_learnsets.h", root,
        "Level-up move list per species, sorted by level."))

    dump("emerald_moves.json", wrap(
        parse_moves(root, move_ids),
        "src/data/battle_moves.h", root,
        "Move stats: type, power, accuracy, PP, priority, effect."))

    dump("emerald_type_chart.json", wrap(
        parse_type_chart(root, type_ids),
        "src/battle_main.c::gTypeEffectiveness", root,
        "[atk_type, def_type, multiplier_x10] triples. Pre-Foresight section."))

    dump("emerald_items.json", wrap(
        parse_items(root, item_ids),
        "src/data/items.h", root,
        "Item name, price, pocket, hold effect."))

    dump("emerald_abilities.json", wrap(
        parse_abilities(ability_ids),
        "include/constants/abilities.h", root,
        "Ability ID → display name."))

    dump("emerald_natures.json", wrap(
        parse_natures(root),
        "src/pokemon.c::gNatureStatTable", root,
        "25 natures with per-stat modifier (-1/0/+1 for ×0.9/×1.0/×1.1)."))

    dump("emerald_mapsec.json", wrap(
        parse_mapsec(root),
        "include/constants/region_map_sections.h + src/data/region_map/region_map_sections.json", root,
        "Map section ID → display name."))

    # Type names for client-side rendering
    dump("emerald_types.json", wrap(
        TYPE_NAMES,
        "include/constants/pokemon.h (TYPE_*)", root,
        "Type ID → display name."))

    print("done.")


if __name__ == "__main__":
    main()
