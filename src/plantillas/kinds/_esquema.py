"""Subconjunto de JSON Schema que usan los kinds. Nada más.

type, properties, required, additionalProperties(False), items, enum,
minLength/maxLength, pattern, minItems/maxItems, minimum/maximum.
"""
from __future__ import annotations

import re
from typing import Any

_TIPOS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


def errores(valor: Any, esquema: dict, ruta: str = "$") -> list[str]:
    tipo = esquema.get("type")
    if tipo and not _TIPOS[tipo](valor):
        return [f"{ruta}: se esperaba {tipo}"]
    out: list[str] = []
    if "enum" in esquema and valor not in esquema["enum"]:
        out.append(f"{ruta}: debe ser uno de {esquema['enum']}")
    if tipo == "string":
        if len(valor) < esquema.get("minLength", 0):
            out.append(f"{ruta}: mínimo {esquema['minLength']} caracteres")
        if "maxLength" in esquema and len(valor) > esquema["maxLength"]:
            out.append(f"{ruta}: máximo {esquema['maxLength']} caracteres")
        if "pattern" in esquema and not re.search(esquema["pattern"], valor):
            out.append(f"{ruta}: no cumple {esquema['pattern']}")
    if tipo in ("integer", "number"):
        if "minimum" in esquema and valor < esquema["minimum"]:
            out.append(f"{ruta}: mínimo {esquema['minimum']}")
        if "maximum" in esquema and valor > esquema["maximum"]:
            out.append(f"{ruta}: máximo {esquema['maximum']}")
    if tipo == "array":
        if len(valor) < esquema.get("minItems", 0):
            out.append(f"{ruta}: mínimo {esquema['minItems']} elementos")
        if "maxItems" in esquema and len(valor) > esquema["maxItems"]:
            out.append(f"{ruta}: máximo {esquema['maxItems']} elementos")
        if "items" in esquema:
            for i, v in enumerate(valor):
                out += errores(v, esquema["items"], f"{ruta}[{i}]")
    if tipo == "object":
        props = esquema.get("properties", {})
        for req in esquema.get("required", []):
            if req not in valor:
                out.append(f"{ruta}.{req}: obligatorio")
        if esquema.get("additionalProperties") is False:
            for k in valor:
                if k not in props:
                    out.append(f"{ruta}.{k}: propiedad no permitida")
        for k, v in valor.items():
            if k in props:
                out += errores(v, props[k], f"{ruta}.{k}")
    return out
