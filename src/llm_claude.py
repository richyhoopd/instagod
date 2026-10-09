"""Cliente mínimo de Claude para el diseñador v2.

Una sola forma de llamar: herramienta forzada (`tool_choice`), con imágenes
opcionales. Devuelve el `input` de la herramienta tal cual; validar es
trabajo de quien llama.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import config


class LLMNoDisponible(RuntimeError):
    """Falta la API key o el paquete `anthropic`."""


class LLMSinHerramienta(RuntimeError):
    """El modelo respondió sin llamar a la herramienta pedida."""


class LLMTruncado(RuntimeError):
    """La respuesta se cortó por `max_tokens`: el input de la herramienta está incompleto."""


_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".webp": "image/webp"}


def _cliente():
    if not config.ANTHROPIC_API_KEY:
        raise LLMNoDisponible("falta ANTHROPIC_API_KEY")
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover - depende del venv
        raise LLMNoDisponible("falta el paquete anthropic") from e
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _bloque_imagen(ruta: Path) -> dict[str, Any]:
    media = _MEDIA.get(ruta.suffix.lower())
    if media is None:
        raise ValueError(f"imagen no soportada: {ruta.suffix.lstrip('.')}")
    datos = base64.b64encode(ruta.read_bytes()).decode("ascii")
    return {"type": "image",
            "source": {"type": "base64", "media_type": media, "data": datos}}


def _con_imagenes(mensajes: list[dict], imagenes) -> list[dict]:
    mensajes = [dict(m) for m in mensajes]
    if not imagenes:
        return mensajes
    for i in range(len(mensajes) - 1, -1, -1):
        if mensajes[i].get("role") != "user":
            continue
        contenido = mensajes[i]["content"]
        if isinstance(contenido, str):
            contenido = [{"type": "text", "text": contenido}]
        mensajes[i]["content"] = [_bloque_imagen(Path(p)) for p in imagenes] + list(contenido)
        return mensajes
    raise ValueError("no hay mensaje de usuario al cual adjuntar imágenes")


def pedir_herramienta(*, system: str, mensajes: list[dict], herramienta: dict,
                      imagenes=(), modelo: str | None = None,
                      uso: list[dict] | None = None, max_tokens: int = 8192) -> dict:
    modelo = modelo or config.DISENO_MODELO
    enviados = _con_imagenes(mensajes, imagenes)
    cli = _cliente()
    resp = cli.messages.create(
        model=modelo, max_tokens=max_tokens, system=system, messages=enviados,
        tools=[herramienta], tool_choice={"type": "tool", "name": herramienta["name"]})
    if uso is not None:
        u = getattr(resp, "usage", None)
        uso.append({"modelo": modelo,
                    "entrada": int(getattr(u, "input_tokens", 0) or 0),
                    "salida": int(getattr(u, "output_tokens", 0) or 0)})
    for bloque in resp.content:
        if getattr(bloque, "type", None) == "tool_use" and bloque.name == herramienta["name"]:
            if resp.stop_reason == "max_tokens":
                raise LLMTruncado(f"{herramienta['name']} cortada por max_tokens={max_tokens}")
            return dict(bloque.input)
    raise LLMSinHerramienta(f"sin llamada a {herramienta['name']} (stop_reason={resp.stop_reason})")
