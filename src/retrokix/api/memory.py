"""/memory — bus-address read/write."""

from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel


MAX_READ_LEN = 65536  # 64 KB per request


class MemoryWriteBody(BaseModel):
    addr: int
    data: str   # hex
    width: int  # 1, 2, or 4


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/memory")
    def get_memory(
        request: Request,
        addr: int = Query(...),
        len: int = Query(..., gt=0),
        fmt: str = Query("hex"),
    ) -> dict:
        if len > MAX_READ_LEN:
            raise HTTPException(400, detail=f"len must be <= {MAX_READ_LEN}")
        rt = request.app.state.runtime
        try:
            data = rt.read_memory(addr, len)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        if fmt == "hex":
            return {"addr": addr, "len": len, "data": data.hex()}
        if fmt == "base64":
            return {"addr": addr, "len": len, "data": base64.b64encode(data).decode()}
        raise HTTPException(400, detail=f"unknown fmt: {fmt}; expected hex|base64")

    @router.post("/memory")
    def post_memory(body: MemoryWriteBody, request: Request) -> dict:
        if body.width not in (1, 2, 4):
            raise HTTPException(400, detail="width must be 1, 2, or 4")
        try:
            data = bytes.fromhex(body.data)
        except ValueError as exc:
            raise HTTPException(400, detail=f"invalid hex: {exc}") from exc
        if len(data) % body.width != 0:
            raise HTTPException(400, detail="data length must be a multiple of width")
        rt = request.app.state.runtime
        try:
            rt.write_memory(body.addr, data)
        except (ValueError, PermissionError) as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        return {"addr": body.addr, "written": len(data)}

    return router
