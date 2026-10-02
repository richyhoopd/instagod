"""Entidades de marca: el sujeto del contenido.

Para gdlscene una entidad es una banda; para una inmobiliaria, una propiedad;
para una cuenta de tips, un tema recurrente. Es lo que permite que los lotes
("las que llevan más tiempo sin publicarse") y las estadísticas por sujeto
funcionen en cualquier marca y no solo en la musical.

Este módulo NO calcula estadísticas ni ordena para lotes: solo CRUD.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from . import db

_NO_ALNUM = re.compile(r"[^a-z0-9]+")


def slugificar(nombre: str) -> str:
    """'Los Ácidos del Norte' -> 'los-acidos-del-norte'."""
    sin_acentos = unicodedata.normalize("NFKD", nombre)
    sin_acentos = sin_acentos.encode("ascii", "ignore").decode("ascii")
    return _NO_ALNUM.sub("-", sin_acentos.lower()).strip("-")


def _slug_libre(cx, account_id: int, base: str) -> str:
    """Agrega -2, -3... hasta encontrar uno libre en la cuenta."""
    base = base or "entidad"
    candidato, n = base, 1
    while por_slug(cx, account_id, candidato) is not None:
        n += 1
        candidato = f"{base}-{n}"
    return candidato


def crear(cx, account_id: int, nombre: str, tipo: str, *,
          prioridad: int = 3, atributos: dict[str, Any] | None = None,
          band_id: int | None = None, slug: str | None = None) -> int:
    slug_final = _slug_libre(cx, account_id, slug or slugificar(nombre))
    return db.insert(
        cx, "brand_entities", account_id=account_id, tipo=tipo, nombre=nombre,
        slug=slug_final, prioridad=prioridad, band_id=band_id,
        atributos_json=json.dumps(atributos or {}, ensure_ascii=False),
    )


def obtener(cx, entity_id: int) -> dict[str, Any] | None:
    return db.get(cx, "brand_entities", entity_id)


def por_slug(cx, account_id: int, slug: str) -> dict[str, Any] | None:
    filas = db.rows(
        cx, "SELECT * FROM brand_entities WHERE account_id = ? AND slug = ?",
        (account_id, slug),
    )
    return filas[0] if filas else None


def por_band_id(cx, band_id: int) -> dict[str, Any] | None:
    filas = db.rows(cx, "SELECT * FROM brand_entities WHERE band_id = ?", (band_id,))
    return filas[0] if filas else None


def listar(cx, account_id: int, *, solo_activas: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM brand_entities WHERE account_id = ?"
    if solo_activas:
        sql += " AND activa = 1"
    sql += " ORDER BY prioridad ASC, nombre ASC"
    return db.rows(cx, sql, (account_id,))


def editar(cx, entity_id: int, **campos: Any) -> None:
    if "atributos" in campos:
        campos["atributos_json"] = json.dumps(campos.pop("atributos"),
                                              ensure_ascii=False)
    db.update(cx, "brand_entities", entity_id, **campos)


def archivar(cx, entity_id: int) -> None:
    db.update(cx, "brand_entities", entity_id, activa=0)


def atributos_de(fila: dict[str, Any]) -> dict[str, Any]:
    """Tolerante a JSON malformado, como marcas._fila_a_marca."""
    crudo = fila.get("atributos_json")
    if not crudo:
        return {}
    try:
        valor = json.loads(crudo)
    except (json.JSONDecodeError, TypeError):
        return {}
    return valor if isinstance(valor, dict) else {}
