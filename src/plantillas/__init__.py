"""Plantillas de marca: HTML+CSS en DB con contrato de variables y versionado.

`contrato` es puro (sin I/O) para poder validar la salida del LLM en
milisegundos; el acceso a DB vive en este módulo a partir de la Task 8.
"""
from __future__ import annotations

import json
from typing import Any

from .. import db
from ..entidades import slugificar
from . import contrato as _contrato

ContratoInvalido = _contrato.ContratoInvalido


def _slug_libre(cx, account_id: int, base: str) -> str:
    base = base or "plantilla"
    candidato, n = base, 1
    while por_slug(cx, account_id, candidato) is not None:
        n += 1
        candidato = f"{base}-{n}"
    return candidato


def _validado(html: str, contrato_dict: dict[str, Any]) -> str:
    """Valida contrato y HTML, y devuelve el contrato serializado."""
    _contrato.validar(contrato_dict)
    _contrato.validar_html(html, contrato_dict)
    return json.dumps(contrato_dict, ensure_ascii=False)


def layout_de(fila: dict[str, Any]) -> dict[str, Any] | None:
    """El diseño visual de una fila, o None si es legacy (HTML a mano)."""
    crudo = fila.get("layout_json") if hasattr(fila, "get") else fila["layout_json"]
    if not crudo:
        return None
    return json.loads(crudo)


def es_editable(fila: dict[str, Any]) -> bool:
    """Un diseño se abre en el editor solo si tiene capas. Los de antes, no."""
    return layout_de(fila) is not None


def crear(cx, account_id: int, nombre: str, html: str,
          contrato_dict: dict[str, Any], *, descripcion: str | None = None,
          origen: str = "manual", creado_por: int | None = None,
          mensaje_usuario: str | None = None,
          layout: dict[str, Any] | None = None) -> int:
    contrato_json = _validado(html, contrato_dict)
    layout_json = json.dumps(layout, ensure_ascii=False) if layout else None
    tid = db.insert(
        cx, "brand_templates", account_id=account_id, nombre=nombre,
        slug=_slug_libre(cx, account_id, slugificar(nombre)),
        descripcion=descripcion, aspecto=contrato_dict["aspecto"],
        contrato_json=contrato_json, html=html, layout_json=layout_json,
        origen=origen, creado_por=creado_por, version_actual=1,
    )
    db.insert(cx, "template_versions", template_id=tid, version=1, html=html,
              contrato_json=contrato_json, layout_json=layout_json,
              mensaje_usuario=mensaje_usuario)
    cx.commit()
    return tid


def nueva_version(cx, template_id: int, html: str,
                  contrato_dict: dict[str, Any], *,
                  mensaje_usuario: str | None = None,
                  llm_meta: dict[str, Any] | None = None,
                  layout: dict[str, Any] | None = None) -> int:
    contrato_json = _validado(html, contrato_dict)
    layout_json = json.dumps(layout, ensure_ascii=False) if layout else None
    fila = obtener(cx, template_id)
    if fila is None:
        raise ValueError(f"plantilla {template_id} no existe")
    numero = int(fila["version_actual"]) + 1
    db.insert(cx, "template_versions", template_id=template_id, version=numero,
              html=html, contrato_json=contrato_json, layout_json=layout_json,
              mensaje_usuario=mensaje_usuario,
              llm_meta=json.dumps(llm_meta, ensure_ascii=False) if llm_meta else None)
    db.update(cx, "brand_templates", template_id, html=html,
              contrato_json=contrato_json, layout_json=layout_json,
              aspecto=contrato_dict["aspecto"], version_actual=numero,
              actualizado_en=_ahora(cx))
    cx.commit()
    return numero


def revertir(cx, template_id: int, numero: int) -> int:
    """No borra: copia la versión pedida como una versión nueva al final."""
    vieja = version(cx, template_id, numero)
    if vieja is None:
        raise ValueError(f"la plantilla {template_id} no tiene versión {numero}")
    layout = layout_de(vieja) if vieja.get("layout_json") else None
    return nueva_version(cx, template_id, vieja["html"],
                         json.loads(vieja["contrato_json"]),
                         mensaje_usuario=f"volver a la versión {numero}",
                         layout=layout)


def obtener(cx, template_id: int) -> dict[str, Any] | None:
    return db.get(cx, "brand_templates", template_id)


def por_slug(cx, account_id: int, slug: str) -> dict[str, Any] | None:
    filas = db.rows(
        cx, "SELECT * FROM brand_templates WHERE account_id = ? AND slug = ?",
        (account_id, slug),
    )
    return filas[0] if filas else None


def listar(cx, account_id: int, *, estado: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM brand_templates WHERE account_id = ?"
    params: list[Any] = [account_id]
    if estado:
        sql += " AND estado = ?"
        params.append(estado)
    sql += " ORDER BY nombre ASC"
    return db.rows(cx, sql, tuple(params))


def versiones(cx, template_id: int) -> list[dict[str, Any]]:
    return db.rows(
        cx, "SELECT * FROM template_versions WHERE template_id = ? ORDER BY version ASC",
        (template_id,),
    )


def version(cx, template_id: int, numero: int) -> dict[str, Any] | None:
    filas = db.rows(
        cx, "SELECT * FROM template_versions WHERE template_id = ? AND version = ?",
        (template_id, numero),
    )
    return filas[0] if filas else None


def activar(cx, template_id: int) -> None:
    db.update(cx, "brand_templates", template_id, estado="activa",
              actualizado_en=_ahora(cx))
    cx.commit()


def archivar(cx, template_id: int) -> None:
    db.update(cx, "brand_templates", template_id, estado="archivada",
              actualizado_en=_ahora(cx))
    cx.commit()


def contrato_de(fila: dict[str, Any]) -> dict[str, Any]:
    """Tolerante a JSON malformado, como entidades.atributos_de."""
    crudo = fila.get("contrato_json")
    if not crudo:
        return {}
    try:
        valor = json.loads(crudo)
    except (json.JSONDecodeError, TypeError):
        return {}
    return valor if isinstance(valor, dict) else {}


def _ahora(cx) -> str:
    return cx.execute("SELECT datetime('now')").fetchone()[0]
