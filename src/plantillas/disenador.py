"""OBSOLETO desde editor v2 (lo reemplaza plantillas/chat.py). Se borra cuando v2 esté en prod.

El diseñador con LLM: convierte una instrucción en capas.

Antes el LLM escribía HTML libre y el motor lo renderizaba sin sandbox. Ahora
devuelve `layout_json`, que se valida contra un esquema cerrado antes de tocar
nada: lo peor que puede pasar es que el diseño se vea feo, no que ejecute algo.

`_pedir_al_llm` es el único punto que habla con el proveedor. Los tests lo
monkeypatchean; **la suite nunca llama al LLM de verdad**.
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import layout as _layout
from .contrato import ASPECTOS, ContratoInvalido, variables_declaradas

_BLOQUE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def _pedir_al_llm(prompt: str) -> str:
    """IO: la única llamada real al proveedor configurado. Monkeypatch-eable.

    Espejo de `generador._pedir_al_llm` (src/plantillas/generador.py): delega
    en `_via_deepseek`/`_via_anthropic` de `src/slideshow_script.py` con
    `system_prompt=""` porque el rol y las instrucciones ya viajan dentro de
    `prompt`. Import perezoso a propósito, igual que el gemelo.

    NO acepta `temperature`: pisar `config.SLIDESHOW_TEMPERATURE` por llamada
    sería una carrera con los varios jobs que corren a la vez en el worker.
    """
    import config
    from src import slideshow_script as _ss

    if config.LLM_PROVIDER == "claude":
        return _ss._via_anthropic(prompt, system_prompt="")
    return _ss._via_deepseek(prompt, system_prompt="")


def _json_de(crudo: str) -> dict[str, Any]:
    """El LLM a veces envuelve el JSON en un bloque de código o lo rodea de prosa."""
    texto = (crudo or "").strip()
    bloque = _BLOQUE.search(texto)
    if bloque:
        texto = bloque.group(1)
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fin <= inicio:
        raise ContratoInvalido("la respuesta no trae un diseño")
    try:
        return json.loads(texto[inicio:fin + 1])
    except json.JSONDecodeError as exc:
        raise ContratoInvalido(f"el diseño no es JSON válido: {exc}") from exc


def _prompt(*, marca: dict[str, Any], contrato: dict[str, Any], instruccion: str,
           base: dict[str, Any] | None, familias: set[str] | None,
           stickers: list[str] | None, error: str | None) -> str:
    ancho, alto = ASPECTOS[contrato["aspecto"]]
    datos = ", ".join(sorted(variables_declaradas(contrato)))
    tipos = ", ".join(sorted(familias or []))
    stk = ", ".join(stickers or []) or "(ninguno)"
    partes = [
        f"Eres director de arte de la marca {marca.get('nombre')}. "
        f"Su color es {marca.get('color_marca')}.",
        f"Diseña una publicación de {ancho}x{alto} píxeles.",
        "Responde SOLO con un objeto JSON, sin explicaciones ni bloques de código.",
        "",
        "Formato exacto del JSON:",
        json.dumps(_layout.vacio(contrato["aspecto"]), ensure_ascii=False, indent=1),
        "",
        f"Tipos de capa: {list(_layout.TIPOS_CAPA)}.",
        "Una capa de texto lleva 'campo' (un dato del diseño) o 'texto' (fijo), "
        "nunca los dos. Una capa de imagen lleva 'campo' o 'archivo', nunca los dos.",
        f"Datos disponibles para 'campo': {datos}.",
        f"Tipografías permitidas: {tipos}. No inventes otras.",
        f"Stickers disponibles para 'archivo': {stk}.",
        "Los colores son #rrggbb o la palabra 'marca'.",
        f"Todo debe caber en {ancho}x{alto}. Máximo {_layout.MAX_CAPAS} capas.",
        "",
        f"Lo que se pide: {instruccion}",
    ]
    if base:
        partes += ["", "Parte de este diseño y modifícalo:",
                   json.dumps(base, ensure_ascii=False)]
    if error:
        partes += ["", f"Tu respuesta anterior no sirvió: {error}. Corrígelo."]
    return "\n".join(partes)


def disenar(*, marca: dict[str, Any], contrato: dict[str, Any], instruccion: str,
            base: dict[str, Any] | None = None, familias: set[str] | None = None,
            stickers: list[str] | None = None, intentos: int = 3) -> dict[str, Any]:
    """Una instrucción en español entra, un diseño válido sale.

    Reintenta pasándole al modelo el error exacto: en la práctica corrige a la
    segunda. Si no, lanza ContratoInvalido con el último problema, que ya está
    redactado para que lo lea una persona.
    """
    error: str | None = None
    for _ in range(max(1, intentos)):
        crudo = _pedir_al_llm(_prompt(
            marca=marca, contrato=contrato, instruccion=instruccion, base=base,
            familias=familias, stickers=stickers, error=error))
        try:
            propuesta = _json_de(crudo)
            _layout.validar(propuesta, contrato, familias=familias)
            return propuesta
        except (ContratoInvalido, TypeError, KeyError) as exc:
            error = str(exc)
    raise ContratoInvalido(f"no se pudo armar el diseño: {error}")
