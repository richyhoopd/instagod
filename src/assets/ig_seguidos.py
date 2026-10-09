"""Fuente «Seguidos de IG»: el following de una cuenta semilla, curado por marca,
como banco de fotos y reels en brand_assets.

Generaliza lo de gdlscene (import_followees + ingest_ig) a cualquier marca SIN
tocar `bands`: las cuentas viven en brand_ig_cuentas y los medios en brand_assets.
Reusa el pool de cookies (SesionRotatoria) y su ritmo; no sube la concurrencia.
"""
from __future__ import annotations

import re
from typing import Any

from src import db, import_followees

PROVEEDOR = "ig_seguidos"
ESTADOS = ("candidata", "activa", "descartada")
_HANDLE_RE = re.compile(r"^[a-z0-9._]{1,30}\Z")


def normalizar_handle(texto: str) -> str:
    """'  @Cafe.Tacuba ' -> 'cafe.tacuba'. ValueError si no es un handle de IG válido."""
    h = (texto or "").strip().lstrip("@").lower()
    if not _HANDLE_RE.match(h) or ".." in h:
        raise ValueError(f"handle de Instagram inválido: {texto!r}")
    return h


def _fila(cx, account_id: int, handle: str) -> dict[str, Any] | None:
    filas = db.rows(cx, "SELECT * FROM brand_ig_cuentas WHERE account_id = ? AND ig_handle = ?",
                    (account_id, handle))
    return dict(filas[0]) if filas else None


def listar(cx, account_id: int, *, estado: str | None = None) -> list[dict[str, Any]]:
    """Cuentas de la marca: primero candidatas (lo que falta curar), luego activas."""
    sql = "SELECT * FROM brand_ig_cuentas WHERE account_id = ?"
    params: list[Any] = [account_id]
    if estado is not None:
        if estado not in ESTADOS:
            raise ValueError(f"estado inválido: {estado!r}")
        sql += " AND estado = ?"
        params.append(estado)
    sql += (" ORDER BY CASE estado WHEN 'candidata' THEN 0 WHEN 'activa' THEN 1 ELSE 2 END,"
            " ig_handle")
    return [dict(r) for r in db.rows(cx, sql, tuple(params))]


def fijar_estado(cx, account_id: int, handle: str, estado: str) -> dict[str, Any]:
    """Aprueba, descarta o agrega a mano. Si la cuenta no existía, nace con origen 'manual'."""
    if estado not in ESTADOS:
        raise ValueError(f"estado inválido: {estado!r}")
    h = normalizar_handle(handle)
    fila = _fila(cx, account_id, h)
    if fila:
        db.update(cx, "brand_ig_cuentas", fila["id"], estado=estado)
    else:
        db.insert(cx, "brand_ig_cuentas", account_id=account_id, ig_handle=h,
                  nombre=h, estado=estado, origen="manual")
    return _fila(cx, account_id, h)


def importar_seguidos(cx, account_id: int, semilla: str,
                      limite: int | None = None) -> dict[str, int]:
    """Importa el following de `semilla` como candidatas de la marca.

    Nunca toca filas existentes: la curaduría (activa/descartada) manda sobre
    cualquier reimportación. Propaga IngestRateLimited si el pool se agota.
    """
    s = normalizar_handle(semilla)
    usuarios = import_followees._listar_con_pool(s, limite)
    nuevas = ya = 0
    for u in usuarios:
        try:
            h = normalizar_handle(str(u.get("username") or ""))
        except ValueError:
            continue
        if _fila(cx, account_id, h):
            ya += 1
            continue
        avatar = u.get("profile_pic_url") or ""
        db.insert(cx, "brand_ig_cuentas", account_id=account_id, ig_handle=h,
                  nombre=(u.get("full_name") or "").strip() or h,
                  origen=f"seguido_de:{s}",
                  avatar_url=avatar if avatar.startswith("https://") else None,
                  privada=1 if u.get("is_private") else 0)
        nuevas += 1
    return {"nuevas": nuevas, "ya": ya, "total": len(usuarios)}
