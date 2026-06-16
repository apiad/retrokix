#!/usr/bin/env python3
"""Compute a Wikipedia-pageviews fame score per ROM group.

Walks the bundled GBA + NES No-Intro indexes, collapses regional/version
variants into title groups via `gbax.browse._title_key`, and for each
group resolves a Wikipedia article + sums its monthly pageviews over
the last 12 months. Output goes to `src/gbax/data/wikipedia_fame.json`
keyed by (console, title), which `gbax browse` consults to sort
results DESC by views.

Resume-safe: writes after every group. Pass `--limit N` for a smoke
test that processes the first N unprocessed groups.

Usage:
    python scripts/refresh_fame.py                  # full refresh
    python scripts/refresh_fame.py --limit 100      # smoke test (next 100)
    python scripts/refresh_fame.py --console nes    # one console
    python scripts/refresh_fame.py --rebuild        # ignore existing cache

Rate limit: ~3 requests per group at 0.25s spacing → ~10k groups takes
~2hrs. We follow Wikimedia's recommended UA and serialize calls.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gbax.library import CONSOLES, RomLibrary, title_key  # noqa: E402

UA = "gbax-fame-refresh/0.1 (+https://github.com/apiad/gbax)"
SLEEP = 0.25
TIMEOUT = 15
RETRIES = 3
RETRY_BACKOFF = 2.0

FAME_JSON = ROOT / "src" / "gbax" / "data" / "wikipedia_fame.json"


def _get(url: str) -> dict | list | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last_err: Exception | None = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(RETRY_BACKOFF * (attempt + 1))
    sys.stderr.write(f"  ! fetch failed: {url} ({last_err})\n")
    return None


# --- title normalization + match validation -------------------------------

_NOISE_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")

# No-Intro suffixes that Wikipedia doesn't carry.
_STRIP_SUFFIXES = (
    " version", " the video game", " the game",
)


def _normalize(text: str) -> str:
    """Strip accents + punctuation + extra whitespace, lowercase. Used to
    compare a No-Intro group title to a Wikipedia article title."""
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    s = s.lower()
    s = _NOISE_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    for suf in _STRIP_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)].rstrip()
    return s


def _denoun_search_title(title: str) -> str:
    """Pre-process a No-Intro title for searching.

    - "Legend of Zelda, The" → "The Legend of Zelda" (Wikipedia uses the
      forward order)
    - " - " separators → " " (No-Intro uses dashes; Wikipedia rarely does)
    - Strip " Version" trailer ("Pokemon - Emerald Version" → "Pokemon Emerald")
    """
    s = title
    if ", The" in s:
        head, rest = s.split(", The", 1)
        s = f"The {head}{rest}"
    s = s.replace(" - ", " ")
    if s.lower().endswith(" version"):
        s = s[: -len(" version")].rstrip()
    return s


_STOPWORDS = {"the", "a", "an", "of"}


def _tokens(text: str) -> set[str]:
    return {t for t in _normalize(text).split() if t and t not in _STOPWORDS}


def _looks_like_match(search_title: str, article_title: str) -> bool:
    """Token-set equality on normalized titles after stripping the
    article's parenthetical disambiguator. Order-insensitive (handles
    'Legend of Zelda, The' vs 'The Legend of Zelda') and stopword-free
    ('The Foo' == 'Foo'). Tight enough to reject OpenSearch fuzzy
    misses ('Rad Racer' → 'Rat Race') and disambig stubs ('Mortal
    Kombat 3' → 'Mortal Kombat')."""
    a = _tokens(search_title)
    bare_article = re.sub(r"\s*\([^)]+\)\s*", " ", article_title)
    b = _tokens(bare_article)
    return bool(a) and a == b


def _opensearch(query: str) -> str | None:
    """Return the top article title for `query`, or None."""
    enc = urllib.parse.quote(query)
    data = _get(
        f"https://en.wikipedia.org/w/api.php?action=opensearch&search={enc}&limit=3&format=json"
    )
    if data and len(data) > 1 and data[1]:
        return data[1][0]
    return None


def _resolve_article(title: str) -> str | None:
    """Resolve a No-Intro group title to a canonical Wikipedia article.

    Strategy:
      1. Try the cleaned bare title — gets a high-quality canonical hit
         when the article shares a name with the game.
      2. Validate by strict equality on normalized titles.
      3. If the bare result is the wrong article (or no result), retry
         with an explicit "(video game)" disambiguator.
      4. Otherwise treat as unresolved.
    """
    cleaned = _denoun_search_title(title)
    bare = _opensearch(cleaned)
    if bare and _looks_like_match(cleaned, bare):
        return bare
    time.sleep(SLEEP)
    disambig = _opensearch(f"{cleaned} (video game)")
    if disambig and _looks_like_match(cleaned, disambig):
        return disambig
    return None


def _page_size(article: str) -> int:
    enc = urllib.parse.quote(article)
    data = _get(
        f"https://en.wikipedia.org/w/api.php?action=query&titles={enc}&prop=info&inprop=length&format=json"
    )
    if not data:
        return 0
    try:
        page = next(iter(data["query"]["pages"].values()))
        return int(page.get("length", 0))
    except (KeyError, StopIteration):
        return 0


def _pageviews(article: str, months: int = 12) -> int:
    """Sum monthly all-access user pageviews over the last `months`."""
    end = datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)
    start = (end - timedelta(days=months * 31)).replace(day=1)
    s = start.strftime("%Y%m01")
    e = end.strftime("%Y%m%d")
    enc = urllib.parse.quote(article.replace(" ", "_"), safe="")
    url = (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        f"en.wikipedia/all-access/user/{enc}/monthly/{s}/{e}"
    )
    data = _get(url)
    if not data:
        return 0
    return sum(int(it.get("views", 0)) for it in data.get("items", []))


def _all_groups(consoles: list[str]) -> list[tuple[str, str]]:
    """List unique (console, title-group) tuples present in the bundled libraries."""
    lib = RomLibrary()
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for e in lib.entries():
        if e.console not in consoles:
            continue
        key = (e.console, title_key(e.name))
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _load_cache() -> dict[str, dict[str, dict]]:
    if FAME_JSON.exists():
        return json.loads(FAME_JSON.read_text())
    return {c: {} for c in CONSOLES}


def _save_cache(cache: dict) -> None:
    FAME_JSON.write_text(json.dumps(cache, indent=2, sort_keys=True, ensure_ascii=False))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--console", choices=list(CONSOLES), action="append",
                    help="Restrict to one or more consoles (default: all)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after N newly-processed groups (smoke test)")
    ap.add_argument("--rebuild", action="store_true",
                    help="Ignore existing cache and reprocess everything")
    ap.add_argument("--shuffle", action="store_true",
                    help="Process the to-do list in random order — useful with --limit "
                         "for a representative smoke-test sample (alphabetical sampling "
                         "starts with compilations that have no Wikipedia article).")
    args = ap.parse_args()

    consoles = args.console or list(CONSOLES)
    cache = {c: {} for c in CONSOLES} if args.rebuild else _load_cache()
    for c in CONSOLES:
        cache.setdefault(c, {})

    groups = _all_groups(consoles)
    print(f"Total groups across {consoles}: {len(groups)}")

    todo = [(c, t) for (c, t) in groups if t not in cache[c]]
    print(f"Already cached: {len(groups) - len(todo)}  Still to process: {len(todo)}")
    if args.shuffle:
        random.seed(0)  # deterministic sample for repeatable smoke tests
        random.shuffle(todo)
    if args.limit:
        todo = todo[: args.limit]
        print(f"Smoke-test limit applied: {len(todo)} this run")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for i, (console, title) in enumerate(todo, 1):
        article = _resolve_article(title)
        time.sleep(SLEEP)
        if not article:
            cache[console][title] = {
                "article": None, "size": 0, "views_12mo": 0, "resolved_at": today,
            }
            print(f"  [{i}/{len(todo)}] {console} · {title} — no article")
            _save_cache(cache)
            continue
        size = _page_size(article)
        time.sleep(SLEEP)
        views = _pageviews(article)
        time.sleep(SLEEP)
        cache[console][title] = {
            "article": article,
            "size": size,
            "views_12mo": views,
            "resolved_at": today,
        }
        print(f"  [{i}/{len(todo)}] {console} · {title:<45.45s}  →  {article[:45]:<45s}  views={views:>9,}")
        # Save every iteration so the script is interrupt-safe.
        if i % 25 == 0:
            _save_cache(cache)

    _save_cache(cache)
    print(f"\nDone. Cache at {FAME_JSON.relative_to(ROOT)} — {sum(len(v) for v in cache.values())} entries total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
