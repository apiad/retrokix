"""Tests for retrokix.plugin — registry, dispatch, context."""
from __future__ import annotations

import pytest

from retrokix.plugin import Plugin


# ---- Plugin registry (decorators) ----


def test_on_setup_registers_handler():
    p = Plugin()

    @p.on_setup
    def setup(ctx):
        ctx.called = True

    assert len(p.setup_handlers) == 1
    fake_ctx = type("C", (), {})()
    p.setup_handlers[0](fake_ctx)
    assert fake_ctx.called is True


def test_on_teardown_registers_handler():
    p = Plugin()

    @p.on_teardown
    def teardown(ctx):
        pass

    assert len(p.teardown_handlers) == 1


def test_on_frame_bare_registers_with_every_1():
    p = Plugin()

    @p.on_frame
    def every_frame(ctx):
        pass

    assert len(p.frame_handlers) == 1
    _fn, every = p.frame_handlers[0]
    assert every == 1


def test_on_frame_with_every_filter():
    p = Plugin()

    @p.on_frame(every=60)
    def heartbeat(ctx):
        pass

    assert len(p.frame_handlers) == 1
    _fn, every = p.frame_handlers[0]
    assert every == 60


def test_on_state_change_registers_with_tag():
    p = Plugin()

    @p.on_state_change("scene")
    def scene_changed(ctx, old, new):
        pass

    assert "scene" in p.state_change_handlers
    handlers = p.state_change_handlers["scene"]
    assert len(handlers) == 1


def test_on_state_change_with_to_filter():
    p = Plugin()

    @p.on_state_change("scene", to="fight-menu")
    def fight(ctx, old, new):
        pass

    handlers = p.state_change_handlers["scene"]
    _fn, to_value = handlers[0]
    assert to_value == "fight-menu"


def test_on_state_change_without_to_filter():
    p = Plugin()

    @p.on_state_change("hp")
    def hp_changed(ctx, old, new):
        pass

    _fn, to_value = p.state_change_handlers["hp"][0]
    assert to_value is None


def test_on_key_registers_with_slot():
    p = Plugin()

    @p.on_key("M")
    def add_money(ctx):
        pass

    assert "M" in p.key_handlers
    assert len(p.key_handlers["M"]) == 1


def test_on_key_normalizes_slot_case():
    p = Plugin()

    @p.on_key("m")
    def add_money(ctx):
        pass

    assert "M" in p.key_handlers


def test_on_key_rejects_invalid_slot():
    p = Plugin()
    with pytest.raises(ValueError, match="invalid key slot"):
        @p.on_key("INVALID!")
        def _(ctx):
            pass


# ---- PluginContext ----


class _FakeStateReader:
    def __init__(self, values):
        self._values = dict(values)

    def read_all(self):
        return dict(self._values)


class _FakeRuntime:
    def __init__(self, frame_count=0, rom_sha1="abc", rom_name="rom.gba"):
        from pathlib import Path
        self.frame_count = frame_count
        self.rom_sha1 = rom_sha1
        self.rom_path = Path(rom_name)
        self.writes: list[tuple[int, bytes]] = []
        self._memory: dict[int, int] = {}
        self.played_macros: list = []

    def read_memory(self, addr, length):
        return bytes(self._memory.get(addr + i, 0) for i in range(length))

    def write_memory(self, addr, data):
        self.writes.append((addr, bytes(data)))

    def play_macro(self, macro):
        self.played_macros.append(macro)


def _make_ctx(state_values=None, runtime=None, compiled_tags=None):
    from retrokix.plugin import PluginContext
    state_values = state_values or {}
    runtime = runtime or _FakeRuntime()
    compiled_tags = compiled_tags or {}
    reader = _FakeStateReader(state_values)
    logs: list[str] = []
    ctx = PluginContext(runtime, reader, compiled_tags, log_fn=logs.append)
    return ctx, logs


def test_ctx_state_get():
    ctx, _ = _make_ctx(state_values={"hp": 45, "scene": "fight-menu"})
    ctx.refresh_state()
    assert ctx.state["hp"] == 45
    assert ctx.state.get("missing", 99) == 99


def test_ctx_frame_count_mirrors_runtime():
    runtime = _FakeRuntime(frame_count=1234)
    ctx, _ = _make_ctx(runtime=runtime)
    assert ctx.frame_count == 1234


def test_ctx_set_writes_u8():
    runtime = _FakeRuntime()
    ctx, _ = _make_ctx(
        runtime=runtime,
        compiled_tags={"hp": {"addr": "0x02024382", "width": "u8", "kind": "numeric"}},
    )
    ctx.set("hp", 45)
    assert runtime.writes == [(0x02024382, bytes([45]))]


def test_ctx_set_writes_u16_le():
    runtime = _FakeRuntime()
    ctx, _ = _make_ctx(
        runtime=runtime,
        compiled_tags={"money": {"addr": "0x02025e34", "width": "u16_le", "kind": "numeric"}},
    )
    ctx.set("money", 12420)
    assert runtime.writes == [(0x02025e34, bytes([0x84, 0x30]))]


def test_ctx_set_writes_u32_le():
    runtime = _FakeRuntime()
    ctx, _ = _make_ctx(
        runtime=runtime,
        compiled_tags={"money": {"addr": "0x02025e34", "width": "u32_le", "kind": "numeric"}},
    )
    ctx.set("money", 999999)
    assert runtime.writes == [(0x02025e34, bytes([0x3F, 0x42, 0x0F, 0x00]))]


def test_ctx_set_unknown_tag_raises():
    runtime = _FakeRuntime()
    ctx, _ = _make_ctx(runtime=runtime, compiled_tags={})
    with pytest.raises(KeyError, match="unknown_tag"):
        ctx.set("unknown_tag", 1)


def test_ctx_set_overflow_raises():
    runtime = _FakeRuntime()
    ctx, _ = _make_ctx(
        runtime=runtime,
        compiled_tags={"hp": {"addr": "0x02024382", "width": "u8", "kind": "numeric"}},
    )
    with pytest.raises(ValueError, match="overflows u8"):
        ctx.set("hp", 999)


def test_ctx_set_categorical_raises():
    runtime = _FakeRuntime()
    ctx, _ = _make_ctx(
        runtime=runtime,
        compiled_tags={"scene": {"addr": "0x03000fa4", "width": "u8", "kind": "categorical"}},
    )
    with pytest.raises(ValueError, match="categorical writes not supported"):
        ctx.set("scene", "fight-menu")


def test_ctx_press_queues_macro():
    from retrokix.input import Button
    runtime = _FakeRuntime()
    ctx, _ = _make_ctx(runtime=runtime)
    ctx.press([Button.A, Button.DOWN], frames=3)
    assert len(runtime.played_macros) == 1
    macro = runtime.played_macros[0]
    assert macro.total_frames == 3
    assert macro.events[0] == (0, frozenset({Button.A, Button.DOWN}))
    assert macro.events[-1] == (3, frozenset())


def test_ctx_press_accepts_string_button_names():
    runtime = _FakeRuntime()
    ctx, _ = _make_ctx(runtime=runtime)
    ctx.press(["a", "down"], frames=2)
    from retrokix.input import Button
    macro = runtime.played_macros[0]
    assert macro.events[0] == (0, frozenset({Button.A, Button.DOWN}))


def test_ctx_press_swallows_macro_collision(capsys):
    runtime = _FakeRuntime()
    def raising_play(macro):
        raise RuntimeError("cannot play a macro while recording")
    runtime.play_macro = raising_play
    ctx, _ = _make_ctx(runtime=runtime)
    ctx.press(["a"], frames=1)
    captured = capsys.readouterr().out
    assert "warning" in captured.lower()


def test_ctx_log_calls_log_fn():
    ctx, logs = _make_ctx()
    ctx.log("hello")
    assert logs == ["hello"]


# ---- load_plugin ----


def test_load_plugin_finds_single_instance(tmp_path):
    from retrokix.plugin import load_plugin

    plugin_file = tmp_path / "myplugin.py"
    plugin_file.write_text(
        "import retrokix\n"
        "p = retrokix.plugin()\n"
        "@p.on_setup\n"
        "def setup(ctx):\n"
        "    pass\n"
    )
    plugin = load_plugin(plugin_file)
    assert isinstance(plugin, Plugin)
    assert len(plugin.setup_handlers) == 1


def test_load_plugin_zero_instances_raises(tmp_path):
    from retrokix.plugin import load_plugin

    plugin_file = tmp_path / "empty.py"
    plugin_file.write_text("x = 1\n")
    with pytest.raises(RuntimeError, match="found 0"):
        load_plugin(plugin_file)


def test_load_plugin_multiple_instances_raises(tmp_path):
    from retrokix.plugin import load_plugin

    plugin_file = tmp_path / "two.py"
    plugin_file.write_text(
        "import retrokix\n"
        "p1 = retrokix.plugin()\n"
        "p2 = retrokix.plugin()\n"
    )
    with pytest.raises(RuntimeError, match="found 2"):
        load_plugin(plugin_file)


def test_load_plugin_syntax_error_propagates(tmp_path):
    from retrokix.plugin import load_plugin

    plugin_file = tmp_path / "bad.py"
    plugin_file.write_text("def broken(:\n")
    with pytest.raises(SyntaxError):
        load_plugin(plugin_file)


def test_load_plugin_by_module_name():
    """The bundled pokemon.emerald informational plugin loads via dotted module name."""
    from retrokix.plugin import Plugin, load_plugin

    plugin = load_plugin("retrokix.plugins.pokemon.emerald")
    assert isinstance(plugin, Plugin)
    # Should have @p.route entries we registered.
    assert any(r[0] == "/party" for r in plugin.http_routes)
