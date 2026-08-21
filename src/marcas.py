"""Perfil de marca: resolución de la fila `accounts` a un objeto usable.

Los SECRETOS jamás viven aquí: van en .env por sufijo (config.account_creds).
JSON malformado en el perfil cae a defaults con warning — la generación nunca
truena por un perfil a medias.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass

import config
from src import db

# Vars de entorno que una marca necesita para operar completa (con sufijo).
CRED_VARS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "IG_USER_ID",
             "IG_ACCESS_TOKEN", "SHEET_ID")


@dataclass
class Marca:
    id: int
    slug: str
    nombre: str
    ig_handle: str
    color_marca: str
    voz: str
    fuentes: list[str]
    formatos: list[str]
    estilos: dict
    logo_path: str | None
    posting_slots: list[str] | None
    activa: bool
    prompts: dict


def _formatos_default() -> list[str]:
    """Default de `formatos` cuando la marca no lo define (gdlscene incluida).

    listicle primero: es el default editorial histórico del motor v1, y
    generar() usa formatos[0] cuando no se pasa --formato explícito — el
    resto se ordena alfabético, sin importancia de orden.
    """
    return ["listicle"] + sorted(f for f in config.SLIDESHOW_FORMATOS if f != "listicle")


# Fase 3 (spec 2026-08-21): base de prompts.por_formato/caption_extra/hashtags
# cuando la marca no define nada (o define solo una parte).
_PROMPTS_BASE = {"caption_extra": "", "por_formato": {}, "hashtags": []}


def _json_o(default, crudo, *, slug: str, campo: str):
    """Parsea JSON tolerante: vacío/malformado/tipo equivocado → default."""
    if not crudo:
        return default
    try:
        val = json.loads(crudo)
    except ValueError:
        print(f"[marcas] {slug}.{campo}: JSON malformado, uso default",
              file=sys.stderr)
        return default
    return val if isinstance(val, type(default)) else default


def _prompts_de(crudo, *, slug: str) -> dict:
    """`prompts_json` tolerante: base con cada clave pisada si el tipo calza."""
    parsed = _json_o({}, crudo, slug=slug, campo="prompts_json")
    prompts = dict(_PROMPTS_BASE)
    for clave, default in _PROMPTS_BASE.items():
        valor = parsed.get(clave)
        if isinstance(valor, type(default)):
            prompts[clave] = valor
    return prompts


def _fila_a_marca(fila: dict) -> Marca:
    slug = fila["slug"]
    slots_raw = (fila.get("posting_slots") or "").strip()
    ig_handle = (fila.get("ig_handle") or "").strip()
    if ig_handle:
        # El seed de Fase A (gdlscene) guardó ig_handle sin "@"; normaliza
        # aquí para que todos los consumidores vean el mismo formato.
        ig_handle = "@" + ig_handle.lstrip("@")
    return Marca(
        id=fila["id"],
        slug=slug,
        nombre=fila.get("nombre") or slug,
        ig_handle=ig_handle,
        color_marca=fila.get("color_marca") or "#1b5e3f",
        voz=(fila.get("voz") or "").strip(),
        fuentes=_json_o(["pexels"], fila.get("fuentes_imagen"),
                        slug=slug, campo="fuentes_imagen"),
        formatos=_json_o(_formatos_default(), fila.get("formatos"),
                         slug=slug, campo="formatos"),
        estilos=_json_o({}, fila.get("estilos_json"),
                        slug=slug, campo="estilos_json"),
        logo_path=fila.get("logo_path") or None,
        posting_slots=[s.strip() for s in slots_raw.split(",") if s.strip()] or None
                      if slots_raw else None,
        activa=bool(fila.get("activa", 1)),
        prompts=_prompts_de(fila.get("prompts_json"), slug=slug),
    )


def cargar(cx, slug: str) -> Marca:
    filas = db.rows(cx, "SELECT * FROM accounts WHERE slug = ?", (slug,))
    if not filas:
        raise ValueError(f"No existe la marca {slug!r} en accounts")
    return _fila_a_marca(filas[0])


def cargar_por_id(cx, account_id: int) -> Marca:
    filas = db.rows(cx, "SELECT * FROM accounts WHERE id = ?", (account_id,))
    if not filas:
        raise ValueError(f"No existe la marca con id={account_id}")
    return _fila_a_marca(filas[0])


def listar(cx, solo_activas: bool = True) -> list[Marca]:
    sql = "SELECT * FROM accounts"
    if solo_activas:
        sql += " WHERE activa = 1"
    return [_fila_a_marca(f) for f in db.rows(cx, sql + " ORDER BY id")]


def estilos_de(marca: Marca) -> dict:
    """Presets disponibles para la marca: los suyos PISAN a los globales."""
    return {**config.SLIDESHOW_ESTILOS, **marca.estilos}


def slots_de(marca: Marca) -> list[str]:
    return marca.posting_slots or config.POSTING_SLOTS


def creds_faltantes(slug: str) -> list[str]:
    """Nombres EXACTOS (con sufijo) de las vars de .env que le faltan a la marca.

    Para gdlscene el fallback sin sufijo cuenta como presente (account_creds
    ya lo resuelve).
    """
    creds = config.account_creds(slug)
    sufijo = f"__{slug.upper()}"
    return [v + sufijo for v in CRED_VARS if not creds.get(v)]


# Portal: obligatorias para operar (SHEET_ID ya no lo es: la cola vive en DB).
CRED_OBLIGATORIAS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "IG_USER_ID", "IG_ACCESS_TOKEN")


def claves_faltantes(slug: str) -> list[str]:
    """Claves (sin sufijo) que la marca aún no tiene ni en DB ni en env."""
    creds = config.account_creds(slug)
    return [k for k in CRED_OBLIGATORIAS if not creds.get(k)]
