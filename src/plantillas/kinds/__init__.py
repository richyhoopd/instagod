"""Kinds: diseños Jinja hechos a mano que el chat llena con un `spec`.

El modelo elige kind y spec; el navegador pone las coordenadas
(`plantillas/extraer.py`). Todos se diseñan en 4x5 (1080×1350).
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jinja2

from ... import compose
from .. import escena as escena_mod
from ._esquema import errores

KINDS = ("side", "stat", "vs", "compare", "list", "cta", "meme", "historia", "cita", "propiedad")
_DIR = Path(__file__).parent


class SpecInvalido(ValueError):
    pass


_STICKER = {"type": "object", "additionalProperties": False, "required": ["texto"],
            "properties": {"texto": {"type": "string", "minLength": 1, "maxLength": 24},
                           "color": {"type": "string", "enum": ["acento", "destacado", "profundo"]}}}

COMUNES: dict[str, dict] = {
    "tema": {"type": "string", "enum": ["claro", "oscuro", "marca"], "default": "claro",
             "description": "claro = fondo blanco; oscuro = fondo casi negro; marca = fondo del color de la marca"},
    "etiqueta": {"type": "string", "maxLength": 40, "description": "píldora corta arriba"},
    "titulo": {"type": "array", "minItems": 1, "maxItems": 4,
               "items": {"type": "string", "minLength": 1, "maxLength": 40},
               "description": "una línea por elemento; el salto lo decides tú"},
    "acento": {"type": "string", "maxLength": 40,
               "description": "fragmento literal del título que se pinta en color de acento"},
    "bajada": {"type": "string", "maxLength": 220},
    "cta": {"type": "string", "maxLength": 40},
    "stickers": {"type": "array", "maxItems": 3, "items": _STICKER, "default": []},
    "grano": {"type": "boolean", "default": False, "description": "textura de grano sobre el fondo"},
}


@lru_cache(maxsize=None)
def _propio(kind: str) -> dict:
    return json.loads((_DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))


def esquema(kind: str) -> dict:
    if kind not in KINDS:
        raise SpecInvalido(f"kind desconocido: {kind!r}")
    propio = _propio(kind)
    props = {**COMUNES, **propio.get("properties", {})}
    return {"type": "object", "description": propio["description"], "properties": props,
            "required": sorted({"titulo", *propio.get("required", [])}),
            "additionalProperties": False, "x-slots": propio.get("x-slots", [])}


def _limpio(nodo: Any) -> Any:
    if isinstance(nodo, dict):
        return {k: _limpio(v) for k, v in nodo.items()
                if not k.startswith("x-") and k != "default"}
    if isinstance(nodo, list):
        return [_limpio(v) for v in nodo]
    return nodo


def esquema_para_llm(kind: str) -> dict:
    return _limpio(esquema(kind))


def catalogo() -> list[dict]:
    return [{"kind": k, "descripcion": _propio(k)["description"], "esquema": esquema_para_llm(k)}
            for k in KINDS]


def _con_defaults(spec: dict, props: dict) -> dict:
    out = copy.deepcopy(spec)
    for k, p in props.items():
        if k not in out and "default" in p:
            out[k] = copy.deepcopy(p["default"])
    return out


def validar_spec(kind: str, spec: dict) -> dict:
    e = esquema(kind)
    if not isinstance(spec, dict):
        raise SpecInvalido("spec debe ser un objeto")
    errs = errores(spec, e)
    if errs:
        raise SpecInvalido("; ".join(errs[:8]))
    return _con_defaults(spec, e["properties"])


def slots(kind: str, spec: dict) -> list[dict]:
    out = []
    for s in esquema(kind)["x-slots"]:
        if s.get("por"):
            for i, _ in enumerate(spec.get(s["por"]) or []):
                out.append({"id": f"{s['id']}_{i}", "recorte": bool(s.get("recorte")),
                            "requerido": bool(s.get("requerido"))})
            continue
        requerido = bool(s.get("requerido")) or bool(
            s.get("requerido_si") and spec.get(s["requerido_si"]))
        out.append({"id": s["id"], "recorte": bool(s.get("recorte")), "requerido": requerido})
    return out


def _sobre(hexa: str) -> str:
    h = hexa.lstrip("#")
    if len(h) != 6:
        return "#FFFFFF"
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#1C1A23" if lum > 0.6 else "#FFFFFF"


def tokens_de(marca, tema: str = "claro") -> dict[str, str]:
    acento = (marca.color_marca or "#7A4CFF").upper()
    base = {
        "claro": {"fondo": "#FFFFFF", "tinta": "#1C1A23", "suave": "#5B5866", "panel": "#F3F1F6"},
        "oscuro": {"fondo": "#1C1A23", "tinta": "#FFFFFF", "suave": "#C9C6D1", "panel": "#2A2733"},
        "marca": {"fondo": acento, "tinta": _sobre(acento), "suave": _sobre(acento),
                  "panel": "rgba(255,255,255,0.14)"},
    }[tema]
    t = {**base, "acento": acento, "sobre_acento": _sobre(acento),
         "destacado": "#F5C842", "sobre_destacado": "#3B2C00",
         "profundo": "#1C1A23", "sobre_profundo": "#FFFFFF"}
    if tema == "marca":
        # Sobre fondo de marca el acento sería invisible: se usa el destacado.
        t["acento"], t["sobre_acento"] = t["destacado"], t["sobre_destacado"]
    t.update((getattr(marca, "estilos", None) or {}).get("tokens", {}))
    t.pop("marca", None)   # nombre reservado por escena.validar
    return t


_TITULO_KIND = {"meme": "Anton-Regular"}


def fuentes_de(marca, familias: set[str], kind: str) -> dict[str, str]:
    propia = (marca.fuentes or [None])[0]
    titulo = _TITULO_KIND.get(kind) or (propia if propia in familias else "Poppins-Bold")
    if titulo not in familias:
        titulo = "Poppins-Bold"
    return {"titulo": titulo, "texto": "Poppins-SemiBold"}


def css_fuentes(familias_usadas: set[str], catalogo_fuentes: list[dict]) -> str:
    capas = [{"tipo": "text", "estilo": {"fontFamily": f}} for f in sorted(familias_usadas)]
    css = escena_mod._font_faces(capas, catalogo_fuentes)
    return css.replace("{{ fonts_dir }}", compose.FONTS_DIR.as_uri())


_ENV = jinja2.Environment(loader=jinja2.FileSystemLoader(str(_DIR)), autoescape=True,
                          undefined=jinja2.StrictUndefined, trim_blocks=True, lstrip_blocks=True)


def render(kind: str, spec: dict, *, tokens: dict, fuentes: dict, assets: dict,
           font_faces: str = "", handle: str = "", logo: str = "") -> str:
    e = esquema(kind)
    completo = {k: spec.get(k) for k in e["properties"]}
    completo["stickers"] = completo.get("stickers") or []
    a = {s["id"]: assets.get(s["id"]) for s in slots(kind, completo)}
    return _ENV.get_template(f"{kind}.html.j2").render(
        spec=completo, t=tokens, f=fuentes, a=a, font_faces=font_faces,
        handle=handle, logo=logo)
