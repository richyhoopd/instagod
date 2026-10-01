"""Fuentes de contenido por marca (`brand_sources`): imágenes y temas.

Fase 3 (spec 2026-08-21): el portal arma/reordena la cascada de sourcing de
imágenes y las fuentes de temas (RSS/NewsAPI) por marca, sin tocar código.
`orden_imagen` es el puente hacia `generate_slideshow.generar`: si la marca
no tiene filas en `brand_sources`, cae al `fuentes_imagen` legacy del perfil
(compat con marcas creadas antes de esta fase).
"""
from __future__ import annotations

import json
import re

from src import db, topics

PROVIDERS_IMAGEN = ("carpeta", "ig_accounts", "pinterest", "pexels", "unsplash", "banco", "covers")
# 'reddit' (motor de video, spec 2026-10-01): historias narrables vía el RSS
# público de un subreddit. Mismo kind='info' que rss/newsapi: alimenta
# `topic_suggestions`, pero su `resumen` trae la historia completa.
PROVIDERS_INFO = ("rss", "newsapi", "reddit")

_CATALOGO = {"imagen": PROVIDERS_IMAGEN, "info": PROVIDERS_INFO}

# Ruta de fuente de Reddit: path relativo (no URL) para que el host quede
# fijado en `topics.fetch_reddit` y una fuente no pueda redirigir el fetch.
# Se importa de `topics` (fuente única) para que lo que valida esta capa sea
# exactamente lo que el fetch acepta después.
from src.topics import RUTA_REDDIT_RE as _RUTA_REDDIT_RE  # noqa: E402

# @handle de Instagram: solo letras/dígitos/punto/guion bajo (charset real de IG),
# 1-30 chars tras la @ — un `startswith("@")` a secas dejaba pasar cosas como
# "@../../evil" que luego se usan para construir un path de archivo (H1).
_CUENTA_IG_RE = re.compile(r"^@[A-Za-z0-9._]{1,30}\Z")


def _es_entero(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _cada_horas_valido(config: dict) -> bool:
    """`cada_horas` es opcional; si viene, debe ser int >= 6 (el scheduler no
    admite corridas más frecuentes). Ausente = ok, el default de 24 lo pone
    `worker.encolar_fuentes_vencidas`."""
    cada_horas = config.get("cada_horas")
    return cada_horas is None or (_es_entero(cada_horas) and cada_horas >= 6)


def validar_config(kind: str, provider: str, config: dict | None) -> None:
    """ValueError("config") si `config` no cumple el esquema del provider.

    ig_accounts/rss/newsapi tienen esquema obligatorio; el resto de providers
    (carpeta/pinterest/pexels/unsplash/banco/covers) aceptan config opcional
    sin más validación. `kind` no cambia las reglas (los nombres de provider
    ya son únicos por kind) pero se recibe para que `crear`/`actualizar`
    llamen siempre con el contexto completo de la fuente.
    """
    config = config or {}
    if provider == "ig_accounts":
        cuentas = config.get("cuentas")
        if not isinstance(cuentas, list) or not cuentas or not all(
            isinstance(c, str) and _CUENTA_IG_RE.match(c) for c in cuentas
        ):
            raise ValueError("config")
        max_por_cuenta = config.get("max_por_cuenta")
        if max_por_cuenta is not None and not (_es_entero(max_por_cuenta) and 1 <= max_por_cuenta <= 50):
            raise ValueError("config")
        if not _cada_horas_valido(config):
            raise ValueError("config")
    elif provider == "rss":
        urls = config.get("urls")
        if not isinstance(urls, list) or not urls or not all(
            isinstance(u, str) and topics.url_segura(u) for u in urls
        ):
            raise ValueError("config")
        if not _cada_horas_valido(config):
            raise ValueError("config")
    elif provider == "newsapi":
        query = config.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("config")
        for campo in ("idioma", "pais"):
            valor = config.get(campo)
            if valor is not None and not isinstance(valor, str):
                raise ValueError("config")
        if not _cada_horas_valido(config):
            raise ValueError("config")
    elif provider == "reddit":
        rutas = config.get("rutas")
        if not isinstance(rutas, list) or not rutas or not all(
            isinstance(r, str) and _RUTA_REDDIT_RE.match(r) for r in rutas
        ):
            raise ValueError("config")
        min_palabras = config.get("min_palabras")
        if min_palabras is not None and not (_es_entero(min_palabras) and 20 <= min_palabras <= 400):
            raise ValueError("config")
        if not _cada_horas_valido(config):
            raise ValueError("config")


def crear(cx, account_id, kind, provider, config: dict | None = None, *, orden=None) -> int:
    """Alta de una fuente de la marca. `kind`: 'imagen'|'info'.

    ValueError("provider") si `provider` no está en el catálogo de `kind`;
    ValueError("config") si `config` no cumple el esquema del provider.
    Sin `orden` explícito, se agrega al final de la cascada de ese `kind`.
    """
    catalogo = _CATALOGO.get(kind)
    if catalogo is None or provider not in catalogo:
        raise ValueError("provider")
    validar_config(kind, provider, config)
    if orden is None:
        fila = db.rows(
            cx, "SELECT COALESCE(MAX(orden), -1) AS m FROM brand_sources "
            "WHERE account_id = ? AND kind = ?", (account_id, kind))
        orden = int(fila[0]["m"]) + 1
    return db.insert(
        cx, "brand_sources", account_id=account_id, kind=kind, provider=provider,
        config_json=json.dumps(config) if config else None, orden=orden)


def listar(cx, account_id, kind=None) -> list[dict]:
    """Fuentes de la marca, orden asc, con `config` ya parseado de `config_json`."""
    sql = "SELECT * FROM brand_sources WHERE account_id = ?"
    params: list = [account_id]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY orden ASC, id ASC"
    filas = db.rows(cx, sql, params)
    for f in filas:
        raw = f.get("config_json")
        try:
            f["config"] = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            f["config"] = {}
    return filas


def actualizar(cx, source_id, *, config=None, activa=None) -> None:
    """Actualiza config y/o el flag `activa` de una fuente existente.

    ValueError("fuente") si `source_id` no existe; ValueError("config") si el
    `config` nuevo no cumple el esquema del provider de esa fuente (misma
    validación que `crear`).
    """
    campos: dict = {}
    if config is not None:
        campos["config_json"] = json.dumps(config)
    if activa is not None:
        campos["activa"] = 1 if activa else 0
    if not campos:
        return
    fila = db.get(cx, "brand_sources", source_id)
    if fila is None:
        raise ValueError("fuente")
    if config is not None:
        validar_config(fila["kind"], fila["provider"], config)
    db.update(cx, "brand_sources", source_id, **campos)


def borrar(cx, source_id) -> None:
    cx.execute("DELETE FROM brand_sources WHERE id = ?", (source_id,))
    cx.commit()


def reordenar(cx, account_id, ids: list[int]) -> None:
    """Reasigna `orden` según la posición en `ids`.

    ValueError("ids") si `ids` no son EXACTAMENTE las fuentes de la marca
    (ni de más, ni de menos, ni de otra cuenta).
    """
    actuales = {f["id"] for f in db.rows(
        cx, "SELECT id FROM brand_sources WHERE account_id = ?", (account_id,))}
    if set(ids) != actuales or len(ids) != len(actuales):
        raise ValueError("ids")
    for pos, sid in enumerate(ids):
        db.update(cx, "brand_sources", sid, orden=pos)


def orden_imagen(cx, marca) -> list[str]:
    """Cascada de providers de imagen de la marca: filas activas de `kind='imagen'`
    en orden; si la marca no tiene filas en `brand_sources`, cae a `marca.fuentes`
    (perfil legacy, compat con marcas creadas antes de esta fase)."""
    filas = db.rows(
        cx, "SELECT provider FROM brand_sources WHERE account_id = ? AND kind = 'imagen' "
        "AND activa = 1 ORDER BY orden ASC, id ASC", (marca.id,))
    if filas:
        return [f["provider"] for f in filas]
    return list(marca.fuentes)
