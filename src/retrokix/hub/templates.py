"""HTML for the hub landing page.

Slice 1: a minimal grid of owned ROMs. Clicking a tile POSTs
/games/launch and opens the returned URL in a new tab.

Slice 2 replaces this body with the full stream-visual-language
treatment (purple palette, JetBrains Mono, fame-ranked + console-
grouped grid).
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from retrokix.hub.server import LibraryGroup


_MINIMAL_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>retrokix — hub</title>
<style>
  body {{ font-family: monospace; background: #0b0a14; color: #e9e9f4; padding: 1.5rem; }}
  h1 {{ font-size: 1rem; letter-spacing: 0.04em; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ padding: 0.4rem 0; }}
  a {{ color: #a78bfa; text-decoration: none; cursor: pointer; }}
  a:hover {{ color: #f0abfc; }}
  .empty {{ color: #6e6c92; padding: 1rem 0; }}
  .console {{ color: #6e6c92; font-size: 0.75rem; margin-right: 0.5rem; }}
  .stars {{ color: #34d399; margin-right: 0.5rem; }}
</style>
</head>
<body>
<h1>retrokix <span style="color:#a78bfa">·</span> hub (v{version})</h1>
{body}
<script>
document.querySelectorAll('[data-rom]').forEach(a => {{
  a.addEventListener('click', async e => {{
    e.preventDefault();
    const resp = await fetch('/games/launch', {{
      method: 'POST',
      headers: {{'content-type': 'application/json'}},
      body: JSON.stringify({{rom_path: a.dataset.rom}}),
    }});
    if (!resp.ok) {{ alert('launch failed: ' + resp.status); return; }}
    const {{url}} = await resp.json();
    window.open(url, '_blank');
  }});
}});
</script>
</body>
</html>
"""


def render_landing(groups: "list[LibraryGroup]", *, version: str) -> str:
    if not groups:
        body = (
            '<p class="empty">No ROMs in your library yet. '
            'Use <code>retrokix download &lt;query&gt;</code> to grab one, '
            'then refresh.</p>'
        )
        return _MINIMAL_HTML.format(version=html.escape(version), body=body)

    rows: list[str] = []
    for g in groups:
        stars = "★" * g.stars + "☆" * (5 - g.stars)
        rows.append(
            '<li>'
            f'<span class="console">[{html.escape(g.console.upper())}]</span>'
            f'<span class="stars">{stars}</span>'
            f'<a data-rom="{html.escape(str(g.primary))}">{html.escape(g.title)}</a>'
            '</li>'
        )
    body = '<ul>' + "\n".join(rows) + '</ul>'
    return _MINIMAL_HTML.format(version=html.escape(version), body=body)
