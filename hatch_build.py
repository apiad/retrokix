"""Hatch build hook: stamp the wheel platform tag when the bundled .so is present.

Without this hook the wheel comes out `py3-none-any`, which would make
pip happily install it on macOS/Windows and then crash at runtime with
a missing libretro core. With this hook, the wheel ships as
`py3-none-manylinux_2_28_x86_64` when (and only when) the bundled .so
is present, so pip resolves to it correctly on Linux x86_64 and falls
back to the sdist on every other platform.
"""
from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CoreTagHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name != "wheel":
            return
        cores_dir = Path(self.root) / "src" / "gbax" / "cores"
        # Any bundled core makes the wheel platform-specific. Both .so
        # files are Linux x86_64; either presence flips the tag.
        if any((cores_dir / name).exists() for name in ("mgba_libretro.so", "fceumm_libretro.so")):
            build_data["tag"] = "py3-none-manylinux_2_28_x86_64"
            build_data["pure_python"] = False
