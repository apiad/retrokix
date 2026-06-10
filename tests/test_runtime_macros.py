"""End-to-end tests for record + replay against the real EmulatorRuntime."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gbax.input import Button
from gbax.macros import Macro
from gbax.runtime import EmulatorRuntime, Mode


def _make_runtime(test_rom, mgba_core, tmp_path):
    return EmulatorRuntime(
        test_rom,
        core_path=mgba_core,
        save_dir=tmp_path / "saves",
        mode=Mode.STEP,
    )


def test_recording_captures_button_deltas(test_rom, mgba_core, tmp_path):
    with _make_runtime(test_rom, mgba_core, tmp_path) as rt:
        rt.start_recording_macro()
        # Frame 0..4: no buttons. Frame 5: A pressed. Frame 7: A released.
        rt.step(frames=5)
        rt.set_buttons({Button.A})
        rt.step(frames=2)
        rt.set_buttons(set())
        rt.step(frames=3)
        m = rt.stop_recording_macro()

    assert m is not None
    assert m.total_frames == 10
    # First entry is (0, empty) — initial state at record start.
    assert m.events[0] == (0, frozenset())
    # When A is pressed (between frame 5 and 6), the delta records the new set.
    held_only = [(d, set(s)) for d, s in m.events]
    assert (5, {Button.A}) in held_only
    assert (7, set()) in held_only


def test_replay_applies_recorded_buttons(test_rom, mgba_core, tmp_path):
    macro = Macro(
        slot="F3",
        name="test",
        rom_sha1="x",
        rom_name="x",
        recorded_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        total_frames=10,
        events=[
            (0, frozenset()),
            (5, frozenset({Button.A})),
            (7, frozenset()),
        ],
    )
    with _make_runtime(test_rom, mgba_core, tmp_path) as rt:
        rt.play_macro(macro)
        rt.step(frames=5)
        # At frame 5 the macro's held set becomes {A}.
        assert rt.effective_buttons_held() == {Button.A}
        rt.step(frames=2)
        # At frame 7 the macro releases.
        assert rt.effective_buttons_held() == set()
        # Replay completes after total_frames; subsequent steps don't override.
        rt.step(frames=5)
        assert rt.is_playing_macro() is False


def test_player_input_merges_with_macro(test_rom, mgba_core, tmp_path):
    macro = Macro(
        slot="F3",
        name="test",
        rom_sha1="x",
        rom_name="x",
        recorded_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        total_frames=10,
        events=[(0, frozenset({Button.A}))],
    )
    with _make_runtime(test_rom, mgba_core, tmp_path) as rt:
        rt.play_macro(macro)
        rt.set_buttons({Button.B})
        rt.step(frames=1)
        # Effective set is the union of macro and player.
        assert rt.effective_buttons_held() == {Button.A, Button.B}


def test_record_while_playing_raises(test_rom, mgba_core, tmp_path):
    macro = Macro(
        slot="F3", name="t", rom_sha1="x", rom_name="x",
        recorded_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        total_frames=1, events=[(0, frozenset())],
    )
    with _make_runtime(test_rom, mgba_core, tmp_path) as rt:
        rt.play_macro(macro)
        with pytest.raises(RuntimeError, match="playing"):
            rt.start_recording_macro()


def test_play_while_recording_raises(test_rom, mgba_core, tmp_path):
    macro = Macro(
        slot="F3", name="t", rom_sha1="x", rom_name="x",
        recorded_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        total_frames=1, events=[(0, frozenset())],
    )
    with _make_runtime(test_rom, mgba_core, tmp_path) as rt:
        rt.start_recording_macro()
        with pytest.raises(RuntimeError, match="recording"):
            rt.play_macro(macro)


def test_stop_recording_returns_none_if_not_recording(test_rom, mgba_core, tmp_path):
    with _make_runtime(test_rom, mgba_core, tmp_path) as rt:
        assert rt.stop_recording_macro() is None
