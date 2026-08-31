"""Le pide a DeepSeek los campos que declara el contrato de una plantilla.

Es el gemelo genérico de src/caption.py, que tiene el prompt de gdlscene
hardcodeado y devuelve un string suelto. Aquí el prompt se arma desde la voz
de la marca y el contrato, y la respuesta es un objeto JSON con exactamente
las claves que la plantilla sabe dibujar.

Módulo puro salvo por la llamada al LLM: no toca DB ni Playwright.
"""
from __future__ import annotations

import json
import re
from typing import Any

import config

from . import contrato as _contrato

_JSON = re.compile(r"\{.*\}", re.S)

_SISTEMA = (
    "Eres el redactor de una cuenta de Instagram. Escribes en español de México, "
    "directo y sin relleno. Devuelves SIEMPRE un único objeto JSON con exactamente "
    "las claves que se te piden, sin texto alrededor y sin claves de más."
)


def describir_contrato(contrato: dict[str, Any]) -> str:
    """El contrato en prosa, para que el LLM sepa qué debe devolver."""
    lineas = ["- titular (texto): el titular principal de la pieza."]
    for extra in contrato.get("extras", []) or []:
        eid, tipo = extra.get("id"), extra.get("tipo", "texto")
        desc = extra.get("desc") or ""
        opc = " OPCIONAL, puedes omitirlo" if extra.get("opcional") else ""
        if tipo == "lista":
            minimo, maximo = extra.get("min", 1), extra.get("max", 10)
            rango = (f"exactamente {minimo}" if minimo == maximo
                     else f"entre {minimo} y {maximo}")
            lineas.append(f"- {eid} (lista de textos, {rango} elementos){opc}. {desc}")
        else:
            lineas.append(f"- {eid} ({tipo}){opc}. {desc}")
    return "\n".join(lineas)


def extraer_campos(texto: str) -> dict[str, Any] | None:
    m = _JSON.search(texto or "")
    if not m:
        return None
    try:
        valor = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return valor if isinstance(valor, dict) else None


def _construir_prompt(contrato, *, marca, tema, entidad, rechazados,
                      errores_previos) -> str:
    partes = [_SISTEMA, "", f"MARCA: {marca.nombre} (@{(marca.ig_handle or '').lstrip('@')})"]
    if getattr(marca, "voz", None):
        partes += ["", "VOZ DE LA MARCA:", marca.voz]
    extra = (getattr(marca, "prompts", None) or {}).get("caption_extra")
    if extra:
        partes += ["", "REGLAS ADICIONALES:", extra]
    if entidad:
        partes += ["", f"SUJETO: {entidad.get('nombre')} ({entidad.get('tipo')})"]
    partes += ["", f"TEMA: {tema}", "", "DEVUELVE UN JSON CON ESTAS CLAVES:",
               describir_contrato(contrato)]
    if rechazados:
        partes += ["", "TITULARES YA RECHAZADOS, no los repitas:",
                   *(f"- {r}" for r in rechazados)]
    if errores_previos:
        partes += ["", "TU RESPUESTA ANTERIOR TUVO ESTOS ERRORES, corrígelos:",
                   *(f"- {e}" for e in errores_previos)]
    return "\n".join(partes)


def generar_campos(contrato: dict[str, Any], *, marca, tema: str,
                   entidad: dict[str, Any] | None = None,
                   rechazados: list[str] | None = None,
                   intentos: int = 3) -> dict[str, Any]:
    errores: list[str] = []
    for _ in range(intentos):
        prompt = _construir_prompt(contrato, marca=marca, tema=tema,
                                   entidad=entidad, rechazados=rechazados,
                                   errores_previos=errores)
        campos = extraer_campos(_pedir_al_llm(prompt))
        if campos is None:
            errores = ["no devolviste un objeto JSON válido"]
            continue
        errores = _contrato.validar_campos(campos, contrato)
        if not errores:
            return campos
    raise RuntimeError(
        f"el LLM no produjo campos válidos en {intentos} intentos: {'; '.join(errores)}")


def _pedir_al_llm(prompt: str) -> str:
    """IO: la única llamada real al proveedor configurado. Monkeypatch-eable.

    Delega en `_via_deepseek`/`_via_anthropic` de `src/slideshow_script.py`
    para no duplicar el manejo de DeepSeek/Claude. Ese módulo separa
    `system_prompt` de `user_prompt`, pero aquí el rol y las instrucciones ya
    viven dentro de `prompt` (ver `_SISTEMA`), así que se delega con
    `system_prompt=""` para no repetir el mismo texto dos veces.

    NO acepta `temperature`. La de `slideshow_script` se lee de `config`, y
    ajustarla por llamada obligaba a pisar `config.SLIDESHOW_TEMPERATURE` y
    restaurarla en un `finally`. El worker corre hasta WORKER_MAX_JOBS a la
    vez, así que ese estado global mutable es una carrera esperando a pasar,
    y nadie estaba pidiendo una temperatura distinta. Si algún día hace
    falta, se agrega el parámetro en slideshow_script, no un swap global.
    """
    from src import slideshow_script as _ss

    if config.LLM_PROVIDER == "claude":
        return _ss._via_anthropic(prompt, system_prompt="")
    return _ss._via_deepseek(prompt, system_prompt="")
