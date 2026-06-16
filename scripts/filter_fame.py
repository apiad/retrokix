#!/usr/bin/env python3
"""Filter wikipedia_fame.json by Wikipedia categories.

The opensearch resolver in refresh_fame.py validates by token-set
equality on titles, which fires false positives for No-Intro entries
whose title coincides with a cultural giant — "Wordle", "Napoleon",
"Titanic", "Harry Potter", etc. — that resolve to the franchise /
historical article instead of the obscure game.

This pass walks every resolved entry, fetches the article's category
list, and zeroes out the entry if no category mentions "video game".
Resume-safe: writes after every batch.

Usage:
    python scripts/filter_fame.py             # full pass
    python scripts/filter_fame.py --limit 50  # smoke test
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAME_JSON = ROOT / "src" / "retrokix" / "data" / "wikipedia_fame.json"

UA = "retrokix-fame-filter/0.1 (+https://github.com/apiad/retrokix)"
SLEEP = 0.2
TIMEOUT = 15
RETRIES = 3
RETRY_BACKOFF = 2.0


def _get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read())
        except Exception:  # noqa: BLE001
            time.sleep(RETRY_BACKOFF * (attempt + 1))
    return None


def _is_video_game(article: str) -> bool | None:
    """Fetch the article's categories. Returns True if any contains
    'video game', False otherwise. None on network failure (don't
    zero out on transient errors)."""
    enc = urllib.parse.quote(article)
    # cllimit=max returns up to 500 categories per page; plenty for any
    # article and one call is enough.
    url = (
        f"https://en.wikipedia.org/w/api.php?action=query&titles={enc}"
        f"&prop=categories&cllimit=max&format=json"
    )
    data = _get(url)
    if not data:
        return None
    try:
        page = next(iter(data["query"]["pages"].values()))
    except (KeyError, StopIteration):
        return False
    cats = page.get("categories", [])
    for c in cats:
        title = c.get("title", "").lower()
        if "video game" in title:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after N candidates checked (smoke test)")
    args = ap.parse_args()

    data = json.loads(FAME_JSON.read_text())
    candidates = [
        (c, t) for c, m in data.items() for t, info in m.items()
        if info.get("article") and info.get("views_12mo", 0) > 0
        and not info.get("category_validated")
    ]
    print(f"Candidates to validate: {len(candidates)}")
    if args.limit:
        candidates = candidates[: args.limit]

    kept = filtered = errored = 0
    for i, (console, title) in enumerate(candidates, 1):
        info = data[console][title]
        article = info["article"]
        verdict = _is_video_game(article)
        time.sleep(SLEEP)
        if verdict is True:
            info["category_validated"] = True
            kept += 1
        elif verdict is False:
            old = info["views_12mo"]
            info["views_12mo"] = 0
            info["category_validated"] = False
            info["filtered_reason"] = "no video-game category"
            info["filtered_from_views"] = old
            filtered += 1
            print(f"  [{i}] FILTER  {console} · {title!r:<40} → {article!r}  (views={old:,} → 0)")
        else:
            errored += 1
        if i % 25 == 0:
            FAME_JSON.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))
            print(f"  …{i}/{len(candidates)}  kept={kept} filtered={filtered} errored={errored}")

    FAME_JSON.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))
    print(f"\nDone. kept={kept} filtered={filtered} errored={errored}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
