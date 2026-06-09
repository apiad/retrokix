"""Scenario abstraction — turns a ROM into a runnable task with
setup / observation / scoring / done predicates.

A scenario file is just a Python module containing one or more Scenario
subclasses. They are loaded dynamically by `gbax train` / `gbax tournament`.
"""

from __future__ import annotations

import importlib.util
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


_SHA1_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class ScenarioValidationError(ValueError):
    """Raised when a Scenario class is malformed."""


class Scenario(ABC):
    """Override in user code. Required class-level fields:
        name: str
        rom_sha1: str          — must match the ROM passed to the driver
        decision_period: int   — frames between observe/act calls (>=1)
        max_frames: int        — hard cap on match length (>=1)
    Required methods: setup, observe, score, done. teardown is optional.
    """

    name: str = ""
    rom_sha1: str = ""
    decision_period: int = 1
    max_frames: int = 18000

    @abstractmethod
    def setup(self, ctl: Any) -> None: ...

    @abstractmethod
    def observe(self, ctl: Any, frame: int) -> dict: ...

    @abstractmethod
    def score(self, ctl: Any, frame: int) -> dict: ...

    @abstractmethod
    def done(self, ctl: Any, frame: int) -> bool: ...

    def teardown(self, ctl: Any) -> None:
        return None


def _validate_class_fields(cls: type[Scenario]) -> None:
    if not getattr(cls, "name", "") or not isinstance(cls.name, str):
        raise ScenarioValidationError(f"{cls.__name__}: `name` must be a non-empty str")
    if not isinstance(cls.rom_sha1, str) or not _SHA1_RE.match(cls.rom_sha1):
        raise ScenarioValidationError(
            f"{cls.__name__}: `rom_sha1` must be a 40-char hex string, got {cls.rom_sha1!r}"
        )
    if not isinstance(cls.decision_period, int) or cls.decision_period < 1:
        raise ScenarioValidationError(
            f"{cls.__name__}: `decision_period` must be int >= 1, got {cls.decision_period!r}"
        )
    if not isinstance(cls.max_frames, int) or cls.max_frames < 1:
        raise ScenarioValidationError(
            f"{cls.__name__}: `max_frames` must be int >= 1, got {cls.max_frames!r}"
        )


def instantiate_scenario(cls: type[Scenario]) -> Scenario:
    _validate_class_fields(cls)
    return cls()


def load_scenario_file(path: str | Path, class_name: str | None = None) -> type[Scenario]:
    """Import a .py file and return the contained Scenario subclass.

    If `class_name` is given, return that exact class; otherwise the file must
    contain exactly one Scenario subclass.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    spec = importlib.util.spec_from_file_location(f"_gbax_scenario_{p.stem}", p)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {p} as a Python module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    candidates: list[type[Scenario]] = []
    for attr in dir(module):
        obj = getattr(module, attr)
        if isinstance(obj, type) and issubclass(obj, Scenario) and obj is not Scenario:
            candidates.append(obj)

    if class_name:
        for c in candidates:
            if c.__name__ == class_name:
                return c
        raise ScenarioValidationError(
            f"class {class_name!r} not found in {p}; available: {[c.__name__ for c in candidates]}"
        )
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ScenarioValidationError(f"no Scenario subclasses found in {p}")
    raise ScenarioValidationError(
        f"{p} contains multiple scenarios: {[c.__name__ for c in candidates]}; "
        f"pass --scenario {p}:<ClassName> to disambiguate"
    )
