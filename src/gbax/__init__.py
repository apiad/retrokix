from importlib.metadata import PackageNotFoundError, version as _pkg_version

from gbax.plugin import Plugin, plugin

try:
    __version__ = _pkg_version("gbax")
except PackageNotFoundError:
    # Running from an editable checkout without metadata installed.
    __version__ = "0.0.0+local"


__all__ = ["Plugin", "plugin", "__version__"]
