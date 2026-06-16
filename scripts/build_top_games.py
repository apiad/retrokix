#!/usr/bin/env python3
"""Generate the landing-page ticker dataset from wikipedia_fame.json.

Picks the top 100 ranked groups across all consoles, assigns a
contextual emoji per title (keyword lookup; default 🎮), and writes
the data out as a JS file the landing can include directly. The
ticker animation + DOM build live in docs/javascripts/ticker.js.

Re-run any time the fame snapshot changes:

    python scripts/build_top_games.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAME_JSON = ROOT / "src" / "retrokix" / "data" / "wikipedia_fame.json"
OUT_JS = ROOT / "docs" / "javascripts" / "top_games_data.js"

TOP_N = 100

# Keyword → emoji. First match wins; iterate in declared order so more
# specific keys (e.g. "ninja turtles") are caught before broader ones
# (e.g. "ninja"). Keep lowercase. Multi-word keys are matched as
# substrings.
EMOJI_RULES: list[tuple[str, str]] = [
    # Nintendo first-party (most specific first)
    ("pokemon",            "⚡"),
    ("pokémon",            "⚡"),
    ("zelda",              "🗡️"),
    ("metroid",            "🚀"),
    ("kirby",              "⭐"),
    ("mario kart",         "🏁"),
    ("mario party",        "🎲"),
    ("mario golf",         "⛳"),
    ("mario tennis",       "🎾"),
    ("mario bros",         "🍄"),
    ("super mario",        "🍄"),
    ("mario",              "🍄"),
    ("yoshi",              "🥚"),
    ("wario",              "💰"),
    ("kid icarus",         "🏹"),
    ("excitebike",         "🏍️"),
    ("ice climber",        "🧗"),
    ("balloon fight",      "🎈"),
    ("punch-out",          "🥊"),
    ("punch out",          "🥊"),
    ("donkey kong",        "🦍"),
    ("mother",             "🛸"),
    ("earthbound",         "🛸"),
    ("chrono trigger",     "🕐"),
    ("chrono cross",       "🕐"),
    ("secret of mana",     "🌳"),
    ("seiken densetsu",    "🌳"),
    ("lufia",              "🛡️"),
    ("illusion of gaia",   "🌍"),
    ("terranigma",         "🌍"),
    ("soul blazer",        "✨"),
    ("ogre battle",        "♟️"),
    ("actraiser",          "👼"),
    ("demon's crest",      "👹"),
    ("killer instinct",    "💀"),
    ("pilotwings",         "✈️"),
    ("star fox",           "🦊"),
    ("f-zero",             "🏎️"),
    ("advance wars",       "⚔️"),
    ("fire emblem",        "⚔️"),
    ("golden sun",         "☀️"),
    # Sega / Konami / Capcom / Square classics
    ("sonic",              "🦔"),
    ("castlevania",        "🦇"),
    ("contra",             "💥"),
    ("gradius",            "🛸"),
    ("mega man",           "🤖"),
    ("megaman",            "🤖"),
    ("street fighter",     "👊"),
    ("mortal kombat",      "🩸"),
    ("tekken",             "🥋"),
    ("final fight",        "👊"),
    ("ninja turtles",      "🐢"),
    ("ninja gaiden",       "🥷"),
    ("ninja",              "🥷"),
    ("samurai",            "⚔️"),
    ("resident evil",      "🧟"),
    ("silent hill",        "👻"),
    ("metal gear",         "🪖"),
    ("snake",              "🐍"),
    ("final fantasy",      "💎"),
    ("dragon warrior",     "🐉"),
    ("dragon quest",       "🐉"),
    ("dragon ball",        "🐲"),
    ("kingdom hearts",     "🗝️"),
    ("tactics ogre",       "♟️"),
    ("sword of mana",      "🗡️"),
    ("breath of fire",     "🔥"),
    ("crystalis",          "💎"),
    ("faxanadu",           "🗡️"),
    ("ys",                 "⚔️"),
    # 3rd-party action
    ("doom",               "😈"),
    ("wolfenstein",        "💀"),
    ("duke nukem",         "🔫"),
    ("prince of persia",   "🗡️"),
    ("tomb raider",        "🏛️"),
    ("crash bandicoot",    "🦊"),
    ("spider-man",         "🕷️"),
    ("spiderman",          "🕷️"),
    ("batman",             "🦇"),
    ("superman",           "🦸"),
    ("x-men",              "🦸"),
    ("james bond",         "🔫"),
    ("007",                "🔫"),
    ("james pond",         "🐟"),
    # Sports / racing
    ("tony hawk",          "🛹"),
    ("skate or die",       "🛹"),
    ("rc pro-am",          "🏎️"),
    ("r.c. pro-am",        "🏎️"),
    ("nascar",             "🏁"),
    ("fifa",               "⚽"),
    ("nfl",                "🏈"),
    ("nba",                "🏀"),
    ("tecmo",              "🏈"),
    ("madden",             "🏈"),
    ("golf",               "⛳"),
    ("tennis",             "🎾"),
    ("baseball",           "⚾"),
    ("hockey",             "🏒"),
    ("formula",            "🏁"),
    ("rally",              "🏎️"),
    # Puzzle / arcade
    ("tetris",             "🟦"),
    ("pac-man",            "👻"),
    ("pacman",             "👻"),
    ("bubble bobble",      "🫧"),
    ("wordle",             "📝"),
    ("flappy bird",        "🐤"),
    ("cookie clicker",     "🍪"),
    ("pinball",            "🎱"),
    ("solitaire",          "🃏"),
    # Cult / classic
    ("rygar",              "🛡️"),
    ("blaster master",     "🚜"),
    ("battletoads",        "🐸"),
    ("river city",         "🥷"),
    ("double dragon",      "🐉"),
    ("adventure island",   "🏝️"),
    ("solomon",            "🔑"),
    ("solstice",           "❄️"),
    ("boktai",             "☀️"),
    ("drill dozer",        "⛏️"),
    ("rhythm tengoku",     "🎵"),
    ("astro boy",          "🤖"),
    ("klonoa",             "🌙"),
    ("iridion",            "🛸"),
    ("space invaders",     "👾"),
    ("galaga",             "👾"),
    ("centipede",          "🐛"),
    # Licensed franchises
    ("harry potter",       "⚡"),
    ("lord of the rings",  "💍"),
    ("star wars",          "⭐"),
    ("star trek",          "🖖"),
    ("disney",             "🏰"),
    ("simpsons",           "🍩"),
    ("pixar",              "🎞️"),
    ("muppet",             "🎭"),
    ("scooby",             "🐕"),
    ("titanic",            "🚢"),
    ("jurassic park",      "🦖"),
    ("indiana jones",      "🎩"),
    ("rocky",              "🥊"),
    ("rambo",              "🔫"),
    # Verbs / generic
    ("tank",               "🪖"),
    ("racing",             "🏁"),
    ("warrior",            "⚔️"),
    ("hero",               "🦸"),
    ("dragon",             "🐉"),
    ("knight",             "🛡️"),
    ("magic",               "✨"),
    ("wizard",              "🧙"),
    ("vampire",             "🧛"),
    ("zombie",              "🧟"),
    ("alien",               "👽"),
    ("robot",               "🤖"),
    ("pirate",              "🏴‍☠️"),
    ("car",                 "🚗"),
    ("plane",               "✈️"),
    ("ship",                "🚢"),
    ("space",               "🚀"),
    ("dog",                 "🐕"),
    ("cat",                 "🐈"),
    ("fish",                "🐠"),
]
DEFAULT_EMOJI = "🎮"


def pick_emoji(title: str) -> str:
    low = title.lower()
    for key, em in EMOJI_RULES:
        if key in low:
            return em
    return DEFAULT_EMOJI


def main() -> int:
    fame = json.loads(FAME_JSON.read_text())
    flat = [
        {
            "title": title,
            "console": console.upper(),
            "fame": int(info["views_12mo"]),
        }
        for console, m in fame.items()
        for title, info in m.items()
        if info.get("views_12mo", 0) > 0
    ]
    flat.sort(key=lambda x: -x["fame"])
    top = flat[:TOP_N]

    # Strip ", The" → "The " for display and "X - Y" → "X: Y" for prettiness
    out = []
    seen_titles: set[str] = set()
    for g in top:
        t = g["title"]
        if ", The" in t:
            head, rest = t.split(", The", 1)
            t = f"The {head}{rest}"
        t = re.sub(r"\s+-\s+", ": ", t)
        if t in seen_titles:  # GBA+NES might both have "Tetris"; one entry is enough
            continue
        seen_titles.add(t)
        out.append({"t": t, "c": g["console"], "e": pick_emoji(t)})

    OUT_JS.parent.mkdir(parents=True, exist_ok=True)
    OUT_JS.write_text(
        "/* Auto-generated by scripts/build_top_games.py — do not edit. */\n"
        f"window.GX_TOP_GAMES = {json.dumps(out, ensure_ascii=False)};\n"
    )
    print(f"Wrote {len(out)} games → {OUT_JS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
