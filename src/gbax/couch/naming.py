"""Three-word room codes, Wireguard-style.

64 adjectives × 64 colors × 64 animals = 262,144 codes. Small enough
to fit in memory, large enough that two friends generating codes the
same minute won't collide. Words are short, easy to say out loud, and
chosen to avoid homonyms / hard spellings.

Codes look like `quick-amber-otter` — three lowercase words separated
by hyphens. Parser is lenient: case + extra whitespace + commas are
all fine.
"""

from __future__ import annotations

import re
import secrets

_ADJECTIVES = (
    "amber", "ancient", "bold", "brave", "bright", "brisk", "calm", "clever",
    "cosmic", "crisp", "dapper", "deep", "eager", "easy", "fancy", "fair",
    "fierce", "flat", "fluffy", "fresh", "gentle", "giant", "glad", "happy",
    "humble", "icy", "jolly", "keen", "kind", "late", "lively", "loud",
    "loyal", "lucky", "lush", "mellow", "merry", "mighty", "mild", "misty",
    "noble", "odd", "polite", "proud", "pure", "quick", "quiet", "rapid",
    "rare", "rich", "royal", "rustic", "sharp", "shiny", "silent", "silly",
    "slim", "smug", "snug", "soft", "solid", "spry", "spunky", "stark",
)

_COLORS = (
    "amber", "ash", "azure", "beige", "blush", "bronze", "brown", "buff",
    "carmine", "cerise", "cobalt", "coral", "cream", "crimson", "cyan", "denim",
    "ebony", "emerald", "fuchsia", "garnet", "gold", "green", "grey", "henna",
    "indigo", "ivory", "jade", "khaki", "lapis", "lemon", "lilac", "lime",
    "linen", "magenta", "maroon", "mauve", "mint", "navy", "ochre", "olive",
    "onyx", "orange", "peach", "pearl", "pewter", "pink", "plum", "purple",
    "raven", "red", "rose", "ruby", "russet", "saffron", "sage", "salmon",
    "scarlet", "sepia", "silver", "tan", "teal", "topaz", "violet", "wine",
)

_ANIMALS = (
    "ant", "ape", "badger", "bat", "bear", "bee", "boar", "buck",
    "camel", "cat", "civet", "cobra", "crab", "crane", "crow", "deer",
    "dingo", "dog", "dove", "duck", "eagle", "elk", "emu", "ferret",
    "finch", "fox", "frog", "gecko", "goat", "goose", "grub", "hare",
    "hawk", "heron", "hippo", "horse", "ibex", "ibis", "koala", "lion",
    "lemur", "lynx", "marmot", "mole", "moose", "newt", "okapi", "otter",
    "owl", "panda", "parrot", "puma", "quail", "rabbit", "raven", "robin",
    "salmon", "seal", "shark", "shrew", "skunk", "sloth", "stork", "swan",
)


def new_room_code() -> str:
    """Return a fresh three-word room code, e.g. 'quick-amber-otter'."""
    return "-".join((
        secrets.choice(_ADJECTIVES),
        secrets.choice(_COLORS),
        secrets.choice(_ANIMALS),
    ))


_VALID_RE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")


def is_valid_room_code(code: str) -> bool:
    """Format check only. Doesn't verify the words are in our list —
    rooms could be named anything reasonable, the wordlist is only a
    code *generator*. (Hand-picked names like 'staging' or 'family'
    should keep working.)"""
    if not isinstance(code, str):
        return False
    return bool(_VALID_RE.match(code))


def normalize_room_code(raw: str) -> str:
    """Lowercase, strip, collapse runs of separators. Tolerant parser."""
    if not raw:
        return ""
    s = raw.strip().lower()
    # Replace whitespace, commas, dots with hyphens; collapse runs.
    s = re.sub(r"[\s,._]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


DEFAULT_ROOM = "default"
