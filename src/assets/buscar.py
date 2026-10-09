"""Búsqueda de assets repartida entre las fuentes de la marca.

Un proveedor que falla (sin key, 4xx, timeout) se salta: el error queda en
brand_sources.ultimo_error y en `avisos`, y la búsqueda sigue (spec §4). Los
proveedores de pago (`de_pago=True`) nunca corren por omisión.
"""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from itertools import zip_longest

import config
from src import db
from src.assets import TIPOS, Candidata
from src.assets.proveedores import PROVEEDORES
from src.assets.proveedores.base import SinLlave

_MAX_ERROR = 300
_PARAM_SECRETO = re.compile(r"(?i)\b(key|api_key|apikey|client_id|access_key|token)=[^&\s'\"]+")
_HEADER_SECRETO = re.compile(r"(?i)\b(authorization|client-id|bearer|key)\s*[:=]?\s+\S+")


class LimiteDiario(Exception):
    """La marca ya gastó su tope diario de generaciones de pago."""


def _max_ia_dia() -> int:
    try:
        return max(0, int(os.getenv("INSTAGOD_IA_IMAGEN_MAX_DIA", "20")))
    except ValueError:
        return 20


def _reservar_ia(cx, account_id: int) -> None:
    """Cuenta una llamada a ia_imagen (día UTC) o lanza LimiteDiario si ya se llegó al tope."""
    tope = _max_ia_dia()
    usadas = cx.execute("SELECT COUNT(*) FROM ia_generaciones WHERE account_id = ? "
                        "AND date(creado_en) = date('now')", (account_id,)).fetchone()[0]
    if usadas >= tope:
        raise LimiteDiario(f"Llegaste al tope diario de {tope} generaciones con IA para esta "
                           "marca. Inténtalo mañana o pídele a un administrador subir el límite.")
    cx.execute("INSERT INTO ia_generaciones (account_id) VALUES (?)", (account_id,))
    cx.commit()


def _limpiar(msg: str, creds: dict) -> str:
    for valor in creds.values():
        if valor and len(valor) >= 4:
            msg = msg.replace(valor, "***")
    msg = _PARAM_SECRETO.sub(r"\1=***", msg)
    msg = _HEADER_SECRETO.sub(r"\1 ***", msg)
    return msg[:_MAX_ERROR]


def _ahora() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _proveedores_extra(cx, account_id: int) -> list[str]:
    """Proveedores activos sin fila en brand_sources: ig_seguidos se activa solo
    cuando la marca ya tiene assets ingeridos de IG."""
    hay = db.rows(cx, "SELECT 1 FROM brand_assets WHERE account_id = ?"
                      " AND proveedor = 'ig_seguidos' AND COALESCE(descartada, 0) = 0 LIMIT 1",
                  (account_id,))
    return ["ig_seguidos"] if hay else []


def buscar_con_avisos(cx, account_id: int, slug: str, q: str, *, tipo: str = "imagen",
                      proveedores: list[str] | None = None, n: int = 20
                      ) -> tuple[list[Candidata], list[str]]:
    if tipo not in TIPOS:
        raise ValueError("tipo")
    q = (q or "").strip()[:200]
    n = max(1, min(n, 60))
    creds = config.account_creds(slug)
    filas = db.rows(cx, "SELECT * FROM brand_sources WHERE account_id = ? AND kind = ? "
                        "AND activa = 1 ORDER BY orden, id", (account_id, tipo))
    fila_de: dict[str, dict] = {}
    for f in filas:
        fila_de.setdefault(f["provider"], f)

    avisos: list[str] = []
    if proveedores is None:
        nombres = [p for p in fila_de if p in PROVEEDORES and not PROVEEDORES[p].de_pago]
        if not nombres:
            nombres = ["carpeta"] + (["pexels"] if creds.get("PEXELS_API_KEY") else [])
        nombres += _proveedores_extra(cx, account_id)
    else:
        nombres = []
        for p in proveedores:
            cls = PROVEEDORES.get(p)
            if cls is None:
                avisos.append(f"{p}: proveedor desconocido")
            elif cls.de_pago and p not in fila_de:
                avisos.append(f"{p}: es de pago; actívalo en Ajustes → Fuentes")
            else:
                nombres.append(p)

    if "ia_imagen" in nombres and tipo in PROVEEDORES["ia_imagen"].tipos:
        _reservar_ia(cx, account_id)   # antes de gastar; también cuenta si el proveedor falla
    listas: list[list[Candidata]] = []
    for nombre in dict.fromkeys(nombres):
        cls = PROVEEDORES.get(nombre)
        if cls is None or tipo not in cls.tipos:
            continue
        fila = fila_de.get(nombre)
        error = None
        try:
            conf = json.loads(fila["config_json"] or "{}") if fila else {}
            prov = cls(cx=cx, account_id=account_id, slug=slug, creds=creds, config=conf)
            res = list(prov.buscar(q, tipo=tipo, n=n))
        except SinLlave as e:
            res, error = [], f"falta {e.args[0]}"
        except Exception as e:  # noqa: BLE001 — un proveedor no tumba la búsqueda
            res, error = [], _limpiar(f"{type(e).__name__}: {e}", creds)
        if error:
            avisos.append(f"{nombre}: {error}")
        if fila is not None:
            db.update(cx, "brand_sources", fila["id"], ultimo_run=_ahora(), ultimo_error=error)
        listas.append(res)
    cx.commit()

    out: list[Candidata] = []
    vistos: set[str] = set()
    for grupo in zip_longest(*listas):
        for c in grupo:
            if c is None or c.url in vistos:
                continue
            vistos.add(c.url)
            out.append(c)
    return out[:n], avisos


def buscar(cx, account_id: int, slug: str, q: str, *, tipo: str = "imagen",
           proveedores: list[str] | None = None, n: int = 20) -> list[Candidata]:
    return buscar_con_avisos(cx, account_id, slug, q, tipo=tipo, proveedores=proveedores,
                             n=n)[0]
