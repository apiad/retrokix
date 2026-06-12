"""emerald_couch — the first couch demo plugin.

Two friends each running

    gbax play emerald --plugin gbax.plugins.pokemon.emerald_couch

become couch peers. Press G to gift the highlighted peer a 'tier-3
consumable tool' — semantically a Master Ball. On the receiving end,
a Master Ball intent is logged (the actual write into the encrypted
Emerald bag pocket lands in a later slice — bag/pocket addressing is
TODO in shared/bag.py).

This slice proves the round trip — emit-on-keypress + receive-on-
peer-event + drain-on-SDL-thread + ctx.couch surface — through the
real play loop, not just unit tests.
"""

from __future__ import annotations

import gbax

p = gbax.plugin()
p.emit_couch("couch.gift.consumable.tool")


@p.on_setup
def hello(ctx) -> None:
    ctx.log("emerald_couch: plugin loaded — press 'G' to gift a Master Ball to your peer.")


@p.on_key("G")
def gift(ctx) -> None:
    """Send a tier-3 consumable tool (Master Ball-shaped) to the first peer."""
    if ctx.couch is None:
        ctx.log("emerald_couch: ctx.couch not connected — is the broker running?")
        return
    peers = ctx.couch.peers()
    if not peers:
        ctx.log("emerald_couch: no peers on the couch yet. Boot a friend's gbax to join.")
        return
    target = peers[0]
    payload = {"tier": 3, "count": 1, "item_hint": "MASTER_BALL"}
    ctx.couch.send(target.id, "couch.gift.consumable.tool", payload)
    ctx.log(f"emerald_couch: → sent Master Ball to {target.name} ({target.id})")


@p.on_couch_event("couch.gift.consumable.tool")
def receive_tool(ctx, peer, payload) -> None:
    """Materialise the gift in this player's bag.

    For this slice we log the intent rather than write to memory: the
    Emerald bag-pocket addressing (with quantity-XOR-key obfuscation)
    is still a TODO in shared/bag.py. Once that lands, replace the log
    line below with an actual write_memory call.
    """
    item_hint = payload.get("item_hint", "?")
    count = payload.get("count", 1)
    tier = payload.get("tier", "?")
    ctx.log(
        f"emerald_couch: ← {peer.name} gifted {count}× {item_hint} (tier {tier}) — "
        "TODO: write into bag pocket (shared/bag.py is a stub)."
    )
