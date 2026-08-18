from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["system"])
VERSION = "portal-fase1"


@router.get("/health")
def health() -> dict:
    return {"ok": True, "version": VERSION}
