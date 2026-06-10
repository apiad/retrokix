"""End-to-end smoke against the bundled libretro core.

Skips when the bundle isn't present (sdist install, dev tree without
`bin/build-core` run). Runs end-to-end against the test ROM so that a
broken bundle (LTO trap, wrong glibc, missing dep) fails at unit-test
time, not at user-install time.
"""
from __future__ import annotations

import pytest

from gbax.cores import bundled_core_path
from gbax.runtime import EmulatorRuntime, Mode


def test_bundled_core_loads_and_steps_one_frame(test_rom):
    bundled = bundled_core_path()
    if bundled is None:
        pytest.skip("no bundled core (run bin/build-core)")

    with EmulatorRuntime(test_rom, core_path=bundled, mode=Mode.STEP) as rt:
        rt.step()
        assert rt.frame_count >= 1
