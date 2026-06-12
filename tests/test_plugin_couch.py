"""Tests for the couch surface on the Plugin class — emit_couch,
on_couch_event, and the demo plugin's registration shape."""

from __future__ import annotations

import pytest

import gbax


def test_emit_couch_registers_event_types():
    p = gbax.plugin()
    p.emit_couch("couch.gift.consumable.tool", "couch.cheer")
    assert p.couch_emits == ["couch.gift.consumable.tool", "couch.cheer"]


def test_emit_couch_dedupes():
    p = gbax.plugin()
    p.emit_couch("couch.cheer")
    p.emit_couch("couch.cheer")
    assert p.couch_emits == ["couch.cheer"]


def test_emit_couch_rejects_empty_string():
    p = gbax.plugin()
    with pytest.raises(ValueError):
        p.emit_couch("")


def test_on_couch_event_registers_handler_and_appears_in_receives():
    p = gbax.plugin()

    @p.on_couch_event("couch.gift.consumable.tool")
    def take(ctx, peer, payload):
        return None

    assert "couch.gift.consumable.tool" in p.couch_receives
    assert len(p.couch_event_handlers["couch.gift.consumable.tool"]) == 1


def test_on_couch_event_allows_multiple_handlers_per_event():
    p = gbax.plugin()

    @p.on_couch_event("couch.gift.consumable.tool")
    def h1(ctx, peer, payload):
        return None

    @p.on_couch_event("couch.gift.consumable.tool")
    def h2(ctx, peer, payload):
        return None

    assert len(p.couch_event_handlers["couch.gift.consumable.tool"]) == 2


def test_plugin_context_couch_defaults_to_none():
    from gbax.plugin import PluginContext

    class _FakeRT:
        frame_count = 0
    class _FakeReader:
        def read_all(self):
            return {}

    ctx = PluginContext(_FakeRT(), _FakeReader(), compiled_tags={})
    assert ctx.couch is None


def test_emerald_couch_plugin_loads_with_expected_capabilities():
    from gbax.plugin import load_plugin

    p = load_plugin("gbax.plugins.pokemon.emerald_couch")
    assert "couch.gift.consumable.tool" in p.couch_emits
    assert "couch.gift.consumable.tool" in p.couch_receives
    # G key handler is registered for the gift hotkey
    assert "G" in p.key_handlers
