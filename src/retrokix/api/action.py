"""/action — atomic sequence of (set buttons, advance, observe) steps.

Lets an agent submit one round-trip describing several beats of input +
waiting + screenshots + memory reads. Eliminates the real-time race
between curl calls (the SDL loop keeps advancing at 60 Hz, so a
multi-step plan over individual /buttons + /step calls accrues large
gaps between thinking and acting).

Each step is a dict with any combination of the following keys, applied
in this order within the step:

  hold: list[str]            # set held buttons before advancing
  release: bool              # if true, release all buttons (equivalent to hold:[])
  frames: int                # advance N frames
  screenshot: bool           # capture a PNG of the framebuffer (base64 in response)
  read_memory: list[dict]    # [{addr: "0x02024382", "len": 1}, ...]

The response collects every screenshot taken and every memory read,
plus the total frames advanced across the action.
"""
from __future__ import annotations

import base64
import io
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from retrokix.input import button_from_str


class _MemoryReadSpec(BaseModel):
    addr: str   # hex string like "0x02024382"
    len: int    # bytes to read


class _ActionStep(BaseModel):
    hold: Optional[list[str]] = None
    release: bool = False
    frames: int = 0
    screenshot: bool = False
    read_memory: Optional[list[_MemoryReadSpec]] = None


class _ActionBody(BaseModel):
    steps: list[_ActionStep]


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/action")
    def post_action(body: _ActionBody, request: Request) -> dict:
        runtime = request.app.state.runtime
        screenshots: list[str] = []
        memory_reads: list[dict] = []
        frames_advanced = 0

        # Hold the runtime lock for the whole action so SDL's per-frame
        # step(1) blocks until we finish. RLock lets inner step() /
        # set_buttons() / read_memory() calls re-acquire freely.
        with runtime._lock:
            frame_count_before = runtime.frame_count
            for step_idx, step in enumerate(body.steps):
                try:
                    if step.release:
                        runtime.set_buttons(set())
                    if step.hold is not None:
                        held = {button_from_str(b) for b in step.hold}
                        runtime.set_buttons(held)
                    if step.frames > 0:
                        if step.frames > 60 * 60:
                            raise HTTPException(
                                status_code=400,
                                detail=f"step {step_idx}: frames={step.frames} exceeds 3600 cap",
                            )
                        runtime.step(step.frames)
                        frames_advanced += step.frames
                    if step.screenshot:
                        from PIL import Image
                        fb = runtime.framebuffer()
                        img = Image.fromarray(fb)
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        screenshots.append(base64.b64encode(buf.getvalue()).decode("ascii"))
                    if step.read_memory:
                        for spec in step.read_memory:
                            addr = int(spec.addr, 16) if spec.addr.startswith("0x") else int(spec.addr)
                            if spec.len < 1 or spec.len > 4096:
                                raise HTTPException(
                                    status_code=400,
                                    detail=f"step {step_idx}: read_memory len={spec.len} out of range",
                                )
                            data = runtime.read_memory(addr, spec.len)
                            memory_reads.append({
                                "addr": hex(addr),
                                "len": spec.len,
                                "hex": data.hex(),
                                # convenience decode for the common 1-byte case
                                "u8": data[0] if spec.len == 1 else None,
                            })
                except HTTPException:
                    raise
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=f"step {step_idx}: {exc}") from exc
            frame_count_after = runtime.frame_count

        return {
            "frames_advanced": frames_advanced,
            "frame_count_before": frame_count_before,
            "frame_count": frame_count_after,
            "sdl_frames_inserted": frame_count_after - frame_count_before - frames_advanced,
            "screenshots": screenshots,
            "memory_reads": memory_reads,
        }

    return router
