"""HTML for the hub landing page.

Same visual language as `api/stream.py` — purple/violet palette,
JetBrains Mono + Press Start 2P accents, pill chips, slide-in header.

Landing shape:

  header        retrokix · hub [HUB badge]   live-search input
  ───────────
  per-console section
    [GBA] Game Boy Advance — N titles
    fame-ranked tile grid
  per-console section
    [NES] …
  footer
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from retrokix.hub.server import LibraryGroup


_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>retrokix — hub</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Press+Start+2P&display=swap">
<style>
  :root {
    --bg: #0b0a14;
    --bg-1: #11101f;
    --bg-2: #1a1830;
    --border: #2a2849;
    --border-soft: #1f1d38;
    --text: #e9e9f4;
    --text-dim: #a4a4c8;
    --text-soft: #6e6c92;
    --accent: #a78bfa;
    --accent-deep: #7c3aed;
    --accent-hot: #f0abfc;
    --emerald: #34d399;
    --red: #fb7185;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    background:
      radial-gradient(ellipse 80% 50% at 50% 0%,
        rgba(124,58,237,0.18), transparent 60%),
      var(--bg);
    color: var(--text);
    font-family: "JetBrains Mono", Menlo, Consolas, monospace;
    min-height: 100vh;
  }
  body {
    display: grid;
    grid-template-rows: auto 1fr auto;
  }
  header {
    padding: 0.85rem 1.25rem;
    border-bottom: 1px solid var(--border-soft);
    display: flex;
    align-items: center;
    gap: 1rem;
    background: rgba(11,10,20,0.7);
    backdrop-filter: blur(10px);
    position: sticky;
    top: 0;
    z-index: 10;
  }
  header h1 {
    margin: 0;
    font-size: 0.96rem;
    font-weight: 600;
    letter-spacing: 0.04em;
  }
  header h1 .dot { color: var(--accent); }
  header h1 .v { color: var(--text-soft); font-weight: 400; margin-left: 0.4em; }
  header .badge {
    font-size: 0.7rem;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--accent);
    border: 1px solid rgba(167,139,250,0.35);
    background: rgba(167,139,250,0.08);
    border-radius: 999px;
    padding: 0.25rem 0.65rem;
  }
  header .search {
    margin-left: auto;
    min-width: min(360px, 50vw);
    background: var(--bg-2);
    border: 1px solid var(--border-soft);
    color: var(--text);
    padding: 0.45rem 0.85rem;
    border-radius: 999px;
    font: inherit;
    font-size: 0.85rem;
  }
  header .search:focus {
    outline: 0;
    border-color: rgba(167,139,250,0.45);
  }
  main {
    padding: 1.5rem clamp(1rem, 4vw, 3rem) 2rem;
    max-width: 1400px;
    width: 100%;
    margin: 0 auto;
  }
  .console-section {
    margin-bottom: 2.2rem;
  }
  .console-section__head {
    display: flex;
    align-items: baseline;
    gap: 0.7rem;
    margin-bottom: 0.9rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--border-soft);
  }
  .console-chip {
    font-family: "Press Start 2P", monospace;
    font-size: 0.62rem;
    letter-spacing: 0.04em;
    color: var(--accent-hot);
    border: 1px solid rgba(240,171,252,0.35);
    background: rgba(240,171,252,0.06);
    padding: 0.32rem 0.55rem;
    border-radius: 6px;
  }
  .console-section__label {
    font-size: 0.92rem;
    color: var(--text);
    font-weight: 600;
    letter-spacing: 0.02em;
  }
  .console-section__count {
    color: var(--text-soft);
    font-size: 0.78rem;
    margin-left: auto;
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 0.85rem;
  }
  .tile {
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    background: var(--bg-1);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 0.85rem 0.95rem;
    cursor: pointer;
    text-decoration: none;
    color: inherit;
    transition: border-color 0.12s ease, background 0.12s ease, transform 0.12s ease;
    text-align: left;
    font: inherit;
  }
  .tile:hover {
    border-color: rgba(167,139,250,0.55);
    background: linear-gradient(180deg, rgba(167,139,250,0.06), transparent 60%), var(--bg-1);
    transform: translateY(-1px);
  }
  .tile:active { transform: translateY(0); }
  .tile__title {
    color: var(--text);
    font-size: 0.88rem;
    font-weight: 500;
    line-height: 1.3;
    word-break: break-word;
  }
  .tile__row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    font-size: 0.74rem;
    color: var(--text-soft);
  }
  .tile__stars {
    color: var(--emerald);
    letter-spacing: 0.06em;
  }
  .tile__action {
    margin-left: auto;
    color: var(--accent);
    font-weight: 600;
  }
  .tile.is-launching {
    border-color: var(--emerald);
  }
  .tile.is-launching .tile__action {
    color: var(--emerald);
  }
  .empty {
    padding: 3rem 1rem;
    text-align: center;
    color: var(--text-soft);
  }
  .empty code {
    color: var(--accent);
    background: rgba(167,139,250,0.08);
    border: 1px solid rgba(167,139,250,0.18);
    padding: 0.1em 0.45em;
    border-radius: 4px;
  }
  .hidden { display: none !important; }
  footer {
    padding: 0.85rem 1.25rem;
    border-top: 1px solid var(--border-soft);
    color: var(--text-soft);
    font-size: 0.72rem;
    text-align: center;
  }
  footer code {
    color: var(--accent);
    background: rgba(167,139,250,0.08);
    border: 1px solid rgba(167,139,250,0.18);
    padding: 0.08em 0.36em;
    border-radius: 4px;
  }
  .toast {
    position: fixed;
    bottom: 1.4rem;
    left: 50%;
    transform: translateX(-50%) translateY(8px);
    background: var(--bg-2);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 0.55rem 1rem;
    border-radius: 999px;
    font-size: 0.84rem;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease, transform 0.2s ease;
    z-index: 60;
  }
  .toast.is-visible {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }
  .toast.is-error { border-color: rgba(251,113,133,0.55); color: var(--red); }
</style>
</head>
<body>
"""

_FOOT = """
<footer>
  retrokix hub <code>v{version}</code> · click a tile to play in a new tab
</footer>
<div class="toast" id="toast"></div>
<script>
  const toastEl = document.getElementById('toast');
  let toastT;
  function toast(msg, kind) {{
    toastEl.textContent = msg;
    toastEl.classList.toggle('is-error', kind === 'error');
    toastEl.classList.add('is-visible');
    clearTimeout(toastT);
    toastT = setTimeout(() => toastEl.classList.remove('is-visible'), 2400);
  }}

  document.querySelectorAll('[data-rom]').forEach(el => {{
    el.addEventListener('click', async ev => {{
      ev.preventDefault();
      const rom = el.dataset.rom;
      el.classList.add('is-launching');
      el.querySelector('.tile__action').textContent = 'launching…';
      try {{
        const resp = await fetch('/games/launch', {{
          method: 'POST',
          headers: {{'content-type': 'application/json'}},
          body: JSON.stringify({{rom_path: rom}}),
        }});
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const {{url, rom: romName}} = await resp.json();
        window.open(url, '_blank');
        toast('▶ launched ' + romName);
      }} catch (err) {{
        toast('launch failed: ' + err.message, 'error');
      }} finally {{
        setTimeout(() => {{
          el.classList.remove('is-launching');
          el.querySelector('.tile__action').textContent = '▶ play';
        }}, 1200);
      }}
    }});
  }});

  const searchEl = document.getElementById('search');
  if (searchEl) {{
    searchEl.addEventListener('input', () => {{
      const q = searchEl.value.toLowerCase().trim();
      const tokens = q.split(/\\s+/).filter(Boolean);
      let anyVisible = false;
      document.querySelectorAll('.tile').forEach(t => {{
        const hay = (t.dataset.search || '').toLowerCase();
        const ok = tokens.every(tk => hay.includes(tk));
        t.classList.toggle('hidden', !ok);
        if (ok) anyVisible = true;
      }});
      document.querySelectorAll('.console-section').forEach(s => {{
        const hasAny = s.querySelectorAll('.tile:not(.hidden)').length > 0;
        s.classList.toggle('hidden', !hasAny);
      }});
    }});
  }}
</script>
</body>
</html>
"""


_CONSOLE_LABELS: dict[str, str] = {
    "gba": "Game Boy Advance",
    "nes": "Nintendo Entertainment System",
    "snes": "Super Nintendo Entertainment System",
}


def _stars(n: int) -> str:
    return "★" * n + "<span style='color:var(--text-soft)'>" + ("☆" * (5 - n)) + "</span>"


def _tile(group: "LibraryGroup") -> str:
    title = html.escape(group.title)
    rom = html.escape(str(group.primary))
    stars = _stars(group.stars)
    extra = ""
    if len(group.variants) > 1:
        extra = (
            f"<span class='tile__row__extra'>+{len(group.variants) - 1} variants</span>"
        )
    return (
        f'<button class="tile" data-rom="{rom}" '
        f'data-search="{title.lower()}">'
        f'<div class="tile__title">{title}</div>'
        f'<div class="tile__row">'
        f'<span class="tile__stars">{stars}</span>'
        f'{extra}'
        f'<span class="tile__action">▶ play</span>'
        f'</div>'
        f'</button>'
    )


def _section(console: str, groups: list["LibraryGroup"]) -> str:
    label = _CONSOLE_LABELS.get(console, console.upper())
    tiles = "\n".join(_tile(g) for g in groups)
    return (
        f'<section class="console-section" data-console="{html.escape(console)}">'
        f'<div class="console-section__head">'
        f'<span class="console-chip">[{html.escape(console.upper())}]</span>'
        f'<span class="console-section__label">{html.escape(label)}</span>'
        f'<span class="console-section__count">{len(groups)} title'
        f'{"s" if len(groups) != 1 else ""}</span>'
        f'</div>'
        f'<div class="grid">{tiles}</div>'
        f'</section>'
    )


def render_landing(groups: "list[LibraryGroup]", *, version: str) -> str:
    """Render the hub landing — fame-ranked, console-grouped tile grid."""
    head = _HEAD
    header = (
        '<header>'
        '<h1>retrokix<span class="dot"> · </span>hub'
        f'<span class="v">v{html.escape(version)}</span></h1>'
        '<span class="badge">HUB</span>'
        '<input id="search" class="search" type="search" placeholder="search…" autocomplete="off">'
        '</header>'
    )

    if not groups:
        main = (
            '<main>'
            '<div class="empty">'
            'No ROMs in your library yet. '
            'Use <code>retrokix download &lt;query&gt;</code> to grab one, then refresh.'
            '</div>'
            '</main>'
        )
        return head + header + main + _FOOT.format(version=html.escape(version))

    # Stable console order with known consoles first, then any others
    by_console: dict[str, list[LibraryGroup]] = {}
    for g in groups:
        by_console.setdefault(g.console, []).append(g)
    ordered: list[str] = []
    for slug in ("gba", "nes", "snes"):
        if slug in by_console:
            ordered.append(slug)
    for slug in by_console:
        if slug not in ordered:
            ordered.append(slug)

    sections = "\n".join(_section(c, by_console[c]) for c in ordered)
    main = f'<main>{sections}</main>'
    return head + header + main + _FOOT.format(version=html.escape(version))
