"""Temas sugeridos por marca (`topic_suggestions`): RSS y NewsAPI.

Fase 3 (spec 2026-08-21): fuentes de tipo `info` (`brand_sources.kind='info'`)
alimentan una bandeja de temas por marca que el portal puede convertir en
slideshow. `fetch_rss`/`fetch_newsapi` SOLO bajan y normalizan; `guardar`
persiste con dedup por URL; `listar`/`descartar` son la bandeja.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from typing import Any

import requests

from src import db

_RESUMEN_MAX = 500
_NEWSAPI_URL = "https://newsapi.org/v2/everything"
_NEWSAPI_TOP = 20


def _local(tag: str) -> str:
    """Nombre del tag sin namespace (Atom viene namespaced, RSS2 no)."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _hijo(elem: ET.Element, nombre: str) -> ET.Element | None:
    for hijo in elem:
        if _local(hijo.tag) == nombre:
            return hijo
    return None


def _hijos(elem: ET.Element, nombre: str) -> list[ET.Element]:
    return [h for h in elem if _local(h.tag) == nombre]


def _texto(elem: ET.Element | None) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _texto_plano(crudo: str) -> str:
    """HTML/entidades → texto plano, colapsado y truncado a 500 chars."""
    sin_tags = re.sub(r"<[^>]+>", " ", crudo or "")
    limpio = html.unescape(sin_tags)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    return limpio[:_RESUMEN_MAX]


def _parse_rss2(root: ET.Element) -> list[dict[str, Any]]:
    canal = _hijo(root, "channel")
    items = _hijos(canal, "item") if canal is not None else []
    out = []
    for it in items:
        out.append({
            "titulo": _texto(_hijo(it, "title")),
            "resumen": _texto_plano(_texto(_hijo(it, "description"))),
            "url": _texto(_hijo(it, "link")) or None,
            "publicado_en": _texto(_hijo(it, "pubDate")) or None,
        })
    return out


def _parse_atom(root: ET.Element) -> list[dict[str, Any]]:
    entradas = _hijos(root, "entry")
    out = []
    for en in entradas:
        # OJO: un Element es "falsy" si no tiene hijos (bool depende de len(),
        # no de si es None) — `or` normal saltaría de largo un <summary> vacío
        # de subelementos pero con texto. Comparar contra None explícito.
        resumen_el = _hijo(en, "summary")
        if resumen_el is None:
            resumen_el = _hijo(en, "content")
        link_el = _hijo(en, "link")
        fecha_el = _hijo(en, "published")
        if fecha_el is None:
            fecha_el = _hijo(en, "updated")
        out.append({
            "titulo": _texto(_hijo(en, "title")),
            "resumen": _texto_plano(_texto(resumen_el)),
            "url": (link_el.get("href") if link_el is not None else None) or None,
            "publicado_en": _texto(fecha_el) or None,
        })
    return out


def fetch_rss(url: str, *, _get=None) -> list[dict[str, Any]]:
    """Baja y parsea un feed RSS2 o Atom → [{titulo, resumen, url, publicado_en}].

    Cualquier falla (red, XML malformado, formato desconocido) se avisa por
    stdout y devuelve `[]`: una fuente rota nunca debe tronar el job completo.
    """
    get = _get or requests.get
    try:
        resp = get(url, timeout=15)
        if hasattr(resp, "raise_for_status"):
            resp.raise_for_status()
        crudo = resp.text if hasattr(resp, "text") else resp
        root = ET.fromstring(crudo)
    except Exception as exc:  # noqa: BLE001 — cualquier falla de esta fuente es no-fatal
        print(f"[topics] fetch_rss error en {url}: {exc}")
        return []

    tag = _local(root.tag)
    if tag == "rss":
        return _parse_rss2(root)
    if tag == "feed":
        return _parse_atom(root)
    print(f"[topics] fetch_rss formato desconocido en {url}: <{tag}>")
    return []


def fetch_newsapi(query: str, key: str, *, idioma: str = "es", pais: str | None = None,
                   _get=None) -> list[dict[str, Any]]:
    """NewsAPI `/v2/everything` → [{titulo, resumen, url, publicado_en}] (top 20)."""
    get = _get or requests.get
    params = {"q": query, "language": idioma, "apiKey": key, "pageSize": _NEWSAPI_TOP}
    if pais:
        params["country"] = pais
    try:
        resp = get(_NEWSAPI_URL, params=params, timeout=15)
        if hasattr(resp, "raise_for_status"):
            resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — igual que fetch_rss: fuente rota, no fatal
        print(f"[topics] fetch_newsapi error para {query!r}: {exc}")
        return []

    articulos = (data.get("articles") or [])[:_NEWSAPI_TOP]
    return [{
        "titulo": (a.get("title") or "").strip(),
        "resumen": _texto_plano(a.get("description") or ""),
        "url": a.get("url") or None,
        "publicado_en": a.get("publishedAt") or None,
    } for a in articulos]


def guardar(cx, account_id: int, items: list[dict[str, Any]], fuente: str) -> int:
    """Inserta `items` en `topic_suggestions` (INSERT OR IGNORE por `(account_id,url)`).

    Devuelve cuántos son nuevos (los duplicados por URL no cuentan).
    """
    nuevos = 0
    for it in items:
        titulo = (it.get("titulo") or "").strip()
        if not titulo:
            continue
        cur = cx.execute(
            "INSERT OR IGNORE INTO topic_suggestions "
            "(account_id, titulo, resumen, url, fuente, publicado_en) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, titulo, it.get("resumen"), it.get("url"), fuente,
             it.get("publicado_en")),
        )
        nuevos += cur.rowcount
    cx.commit()
    return nuevos


def listar(cx, account_id: int, *, incluir_usados: bool = False) -> list[dict[str, Any]]:
    """Bandeja de temas de la marca: descartados fuera siempre; usados fuera salvo `incluir_usados`."""
    sql = "SELECT * FROM topic_suggestions WHERE account_id = ? AND descartado = 0"
    if not incluir_usados:
        sql += " AND usado_en_queue_id IS NULL"
    sql += " ORDER BY id DESC"
    return db.rows(cx, sql, (account_id,))


def descartar(cx, topic_id: int) -> None:
    db.update(cx, "topic_suggestions", topic_id, descartado=1)
