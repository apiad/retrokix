"""StepDriver (training) + RealtimeDriver (tournament).

Both drivers share startup: Controller + Scenario + Player subprocess +
HELLO/READY handshake. They differ in the decision-loop pacing.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from gbax.controller import Controller
from gbax.player import (
    ACT,
    DONE,
    HELLO,
    OBS,
    READY,
    SCHEMA_VERSION,
    encode_message,
    iter_messages,
)
from gbax.scenario import Scenario


@dataclass
class MatchOutcome:
    player_label: str
    player_name: str
    result: dict
    reason: str
    frame_count: int
    lag_misses: int = 0
    wall_clock_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


def _parse_cmd(cmd: str | list[str]) -> list[str]:
    if isinstance(cmd, list):
        return cmd
    return shlex.split(cmd)


class _PlayerSubprocess:
    """Thin wrapper around a Popen + iter_messages over its stdout."""

    def __init__(self, cmd: list[str]):
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.stdin: IO[bytes] = self.proc.stdin
        self.stdout: IO[bytes] = self.proc.stdout
        self._iter = iter_messages(self.stdout)

    def send(self, payload: dict) -> None:
        self.stdin.write(encode_message(payload))
        self.stdin.flush()

    def recv(self) -> dict:
        return next(self._iter)

    def close(self, grace_s: float = 0.5) -> None:
        try:
            self.stdin.close()
        except BrokenPipeError:
            pass
        try:
            self.proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class StepDriver:
    """Training driver — untimed. Emulator advances only when stepped."""

    def __init__(
        self,
        rom_path: str | Path,
        scenario_cls: type[Scenario],
        core_path: str | Path | None = None,
    ):
        self.rom_path = Path(rom_path)
        self.scenario_cls = scenario_cls
        self.core_path = core_path

    def run_match(
        self,
        player_cmd: str | list[str],
        player_label: str,
    ) -> MatchOutcome:
        scenario = self.scenario_cls()
        ctl = Controller(self.rom_path, core_path=self.core_path)
        wall_start = time.monotonic()
        notes: list[str] = []
        try:
            scenario.setup(ctl)
        except Exception as exc:
            fc = ctl.frame_count
            ctl.close()
            return MatchOutcome(
                player_label=player_label,
                player_name="<setup-failed>",
                result={"score": 0.0},
                reason="crashed",
                frame_count=fc,
                notes=[f"scenario.setup raised: {exc}"],
                wall_clock_seconds=time.monotonic() - wall_start,
            )

        cmd = _parse_cmd(player_cmd)
        player = _PlayerSubprocess(cmd)
        try:
            player.send({
                "type": HELLO,
                "scenario": scenario.name,
                "decision_period": scenario.decision_period,
                "schema_version": SCHEMA_VERSION,
            })
            ready = player.recv()
            if ready.get("type") != READY:
                raise RuntimeError(f"expected READY, got {ready!r}")
            player_name = str(ready.get("name", "anonymous"))

            frame = 0
            while True:
                obs = scenario.observe(ctl, frame)
                player.send({"type": OBS, "frame": frame, "data": obs})
                try:
                    act = player.recv()
                except StopIteration:
                    notes.append("player exited mid-match")
                    result = scenario.score(ctl, frame)
                    return MatchOutcome(
                        player_label=player_label,
                        player_name=player_name,
                        result=result,
                        reason="crashed",
                        frame_count=frame,
                        notes=notes,
                        wall_clock_seconds=time.monotonic() - wall_start,
                    )
                if act.get("type") != ACT:
                    raise RuntimeError(f"expected ACT, got {act!r}")
                buttons = list(act.get("buttons", []))
                ctl.hold(buttons)
                ctl.wait(scenario.decision_period)
                frame += scenario.decision_period

                if scenario.done(ctl, frame):
                    result = scenario.score(ctl, frame)
                    reason = "scored"
                    break
                if frame >= scenario.max_frames:
                    result = scenario.score(ctl, frame)
                    reason = "timeout"
                    break

            scenario.teardown(ctl)
            player.send({"type": DONE, "result": result, "reason": reason})
            return MatchOutcome(
                player_label=player_label,
                player_name=player_name,
                result=result,
                reason=reason,
                frame_count=frame,
                notes=notes,
                wall_clock_seconds=time.monotonic() - wall_start,
            )
        finally:
            player.close()
            ctl.close()


import select


FRAME_TIME_S = 1.0 / 60.0


class RealtimeDriver:
    """Tournament driver — emulator runs at 60 fps wall clock regardless of
    player. Player has decision_period × 16.67 ms to respond between
    observations. Late responses still apply but increment a lag counter.
    """

    def __init__(
        self,
        rom_path: str | Path,
        scenario_cls: type[Scenario],
        core_path: str | Path | None = None,
        lag_forfeit: int = 60,
        slack_s: float = 0.001,
    ):
        self.rom_path = Path(rom_path)
        self.scenario_cls = scenario_cls
        self.core_path = core_path
        self.lag_forfeit = lag_forfeit
        self.slack_s = slack_s

    def run_match(
        self,
        player_cmd: str | list[str],
        player_label: str,
    ) -> MatchOutcome:
        scenario = self.scenario_cls()
        ctl = Controller(self.rom_path, core_path=self.core_path)
        wall_start = time.monotonic()
        notes: list[str] = []

        try:
            scenario.setup(ctl)
        except Exception as exc:
            ctl.close()
            return MatchOutcome(
                player_label=player_label,
                player_name="<setup-failed>",
                result={"score": 0.0},
                reason="crashed",
                frame_count=0,
                notes=[f"scenario.setup raised: {exc}"],
                wall_clock_seconds=time.monotonic() - wall_start,
            )

        cmd = _parse_cmd(player_cmd)
        player = _PlayerSubprocess(cmd)
        try:
            player.send({
                "type": HELLO,
                "scenario": scenario.name,
                "decision_period": scenario.decision_period,
                "schema_version": SCHEMA_VERSION,
            })
            ready = player.recv()
            if ready.get("type") != READY:
                raise RuntimeError(f"expected READY, got {ready!r}")
            player_name = str(ready.get("name", "anonymous"))

            frame                  = 0
            last_obs_frame         = -scenario.decision_period
            pending_obs_frame: int | None = None
            lag_misses             = 0
            forfeited              = False
            clock_start            = time.monotonic()
            result: dict = {"score": 0.0}
            reason: str = "timeout"

            while True:
                if not forfeited and frame >= last_obs_frame + scenario.decision_period:
                    obs = scenario.observe(ctl, frame)
                    player.send({"type": OBS, "frame": frame, "data": obs})
                    if pending_obs_frame is not None:
                        lag_misses += 1
                        if lag_misses >= self.lag_forfeit:
                            forfeited = True
                    pending_obs_frame = frame
                    last_obs_frame    = frame

                while _has_data(player.stdout):
                    try:
                        act = player.recv()
                    except StopIteration:
                        notes.append("player exited mid-match")
                        forfeited = True
                        break
                    if act.get("type") != ACT:
                        raise RuntimeError(f"expected ACT, got {act!r}")
                    buttons = list(act.get("buttons", []))
                    ctl.hold(buttons)
                    pending_obs_frame = None

                ctl.wait(1)
                frame += 1

                if scenario.done(ctl, frame):
                    result = scenario.score(ctl, frame)
                    reason = "scored"
                    break
                if frame >= scenario.max_frames:
                    result = scenario.score(ctl, frame)
                    reason = "timeout"
                    break
                if forfeited and frame >= last_obs_frame + scenario.decision_period * self.lag_forfeit:
                    result = scenario.score(ctl, frame)
                    reason = "forfeit"
                    break

                target = clock_start + (frame + 1) * FRAME_TIME_S - self.slack_s
                delay = target - time.monotonic()
                if delay > 0:
                    time.sleep(delay)

            scenario.teardown(ctl)
            final_reason = "forfeit" if forfeited else reason
            player.send({"type": DONE, "result": result, "reason": final_reason})
            return MatchOutcome(
                player_label=player_label,
                player_name=player_name,
                result=result,
                reason=final_reason,
                frame_count=frame,
                lag_misses=lag_misses,
                notes=notes,
                wall_clock_seconds=time.monotonic() - wall_start,
            )
        finally:
            player.close()
            ctl.close()


def _has_data(stream: IO[bytes]) -> bool:
    """Non-blocking peek at a binary stream's file descriptor."""
    ready, _, _ = select.select([stream.fileno()], [], [], 0)
    return bool(ready)
