"""/frame — framebuffer as PNG or raw RGB888 bytes."""

from __future__ import annotations

from io import BytesIO

import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response
from PIL import Image


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/frame")
    def get_frame(request: Request, fmt: str = "png") -> Response:
        rt = request.app.state.runtime
        fb = rt.framebuffer()  # (160, 240, 3) uint8

        if fmt == "png":
            buf = BytesIO()
            Image.fromarray(fb).save(buf, format="PNG")
            return Response(content=buf.getvalue(), media_type="image/png")

        if fmt == "raw":
            return Response(
                content=np.ascontiguousarray(fb).tobytes(),
                media_type="application/octet-stream",
            )

        raise HTTPException(400, detail=f"unknown fmt: {fmt}; expected png|raw")

    return router
