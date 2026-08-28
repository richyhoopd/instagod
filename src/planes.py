"""Dominio de planes de contenido masivo (spec 2026-08-28).

Transiciones de content_plans.estado (nadie más las mueve):
  'proponiendo' → job plan.proponer_temas → 'temas' | 'error'
  'temas'       → POST /plans/{id}/generar → job plan.generar → 'generando'
  'generando'   → fin del job → 'curacion' (≥1 pieza) | 'error' (0 piezas)
  'curacion'    → POST /plans/{id}/aprobar con 0 pendientes restantes → 'aprobado'

plan_topics.estado: 'propuesto' → 'aprobado'|'descartado' (curación de temas),
'aprobado' → 'generado'|'error' (job plan.generar). Un topic con queue_id ya
no se edita: su pieza vive en content_queue y se cura allá.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from src import db

_RE_SEMANA = re.compile(r"^\d{4}-W\d{2}$")
_RE_MES = re.compile(r"^\d{4}-\d{2}$")


def validar_periodo(tipo_periodo: str, periodo: str) -> bool:
    """'semana' ↔ '2026-W36', 'mes' ↔ '2026-09' (formato de segments.ventana_de). PURO."""
    if tipo_periodo == "semana":
        return bool(_RE_SEMANA.match(periodo))
    if tipo_periodo == "mes":
        return bool(_RE_MES.match(periodo))
    return False


def config_de(fila: dict[str, Any]) -> dict[str, Any]:
    """config_json → dict, tolerante a NULL/basura. PURO."""
    try:
        val = json.loads(fila.get("config_json") or "{}")
        return val if isinstance(val, dict) else {}
    except ValueError:
        return {}


def crear(cx: sqlite3.Connection, account_id: int, *, tipo_periodo: str,
          periodo: str, objetivo: str, config: dict[str, Any],
          creado_por: int | None) -> int:
    if not validar_periodo(tipo_periodo, periodo):
        raise ValueError("periodo")
    return db.insert(cx, "content_plans", account_id=account_id,
                     tipo_periodo=tipo_periodo, periodo=periodo,
                     objetivo=objetivo.strip(),
                     config_json=json.dumps(config, ensure_ascii=False),
                     creado_por=creado_por)


_SQL_CONTEOS = """
    SELECT p.*,
           (SELECT COUNT(*) FROM plan_topics t WHERE t.plan_id = p.id)
               AS topics_total,
           (SELECT COUNT(*) FROM plan_topics t WHERE t.plan_id = p.id
               AND t.estado = 'aprobado') AS topics_aprobados,
           (SELECT COUNT(*) FROM content_queue q WHERE q.plan_id = p.id
               AND q.status != 'descartado') AS piezas,
           (SELECT COUNT(*) FROM content_queue q WHERE q.plan_id = p.id
               AND q.status != 'descartado' AND q.aprobacion = 'pendiente')
               AS piezas_pendientes
      FROM content_plans p
"""


def listar(cx: sqlite3.Connection, account_id: int) -> list[dict[str, Any]]:
    return db.rows(cx, _SQL_CONTEOS + " WHERE p.account_id = ? ORDER BY p.id DESC",
                   (account_id,))


def detalle(cx: sqlite3.Connection, plan_id: int) -> dict[str, Any] | None:
    filas = db.rows(cx, _SQL_CONTEOS + " WHERE p.id = ?", (plan_id,))
    if not filas:
        return None
    plan = filas[0]
    plan["topics"] = db.rows(
        cx, "SELECT * FROM plan_topics WHERE plan_id = ? ORDER BY orden, id",
        (plan_id,))
    plan["piezas"] = db.rows(
        cx, "SELECT id, tipo, status, aprobacion, caption, imagen_url, "
            "scheduled_datetime, error FROM content_queue "
            "WHERE plan_id = ? AND status != 'descartado' ORDER BY id",
        (plan_id,))
    return plan


def agregar_topic(cx: sqlite3.Connection, plan_id: int, *, titulo: str,
                  formato: str | None = None, hook: str | None = None) -> int:
    """Tema manual: nace 'aprobado' (quien lo escribe a mano ya lo quiere)."""
    siguiente = cx.execute(
        "SELECT COALESCE(MAX(orden) + 1, 0) FROM plan_topics WHERE plan_id = ?",
        (plan_id,)).fetchone()[0]
    return db.insert(cx, "plan_topics", plan_id=plan_id, orden=siguiente,
                     titulo=titulo.strip(), formato=formato, hook=hook,
                     fuente="manual", estado="aprobado")


_TOPIC_EDITABLE = {"titulo", "formato", "hook", "estado"}


def editar_topic(cx: sqlite3.Connection, topic_id: int, **campos: Any) -> None:
    """Edita un topic aún no generado. ValueError('estado') si ya tiene pieza."""
    fila = db.get(cx, "plan_topics", topic_id)
    if fila is None:
        raise ValueError("no_existe")
    if fila.get("queue_id") or fila["estado"] == "generado":
        raise ValueError("estado")
    bad = set(campos) - _TOPIC_EDITABLE
    if bad:
        raise ValueError(f"campos no editables: {sorted(bad)}")
    if "estado" in campos and campos["estado"] not in ("aprobado", "descartado"):
        raise ValueError("estado_valor")
    db.update(cx, "plan_topics", topic_id, **campos)
