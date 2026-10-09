"""Chat del diseñador v2: crear (kind + spec) y editar (ops).

El modelo nunca pone coordenadas ni HTML. Todo lo que devuelve pasa por
kinds.validar_spec / ops.aplicar / escena.validar antes de salir de aquí.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Callable

from .. import compose, llm_claude
from ..assets import biblioteca, buscar, recorte
from . import contrato as contrato_mod
from . import escena as escena_mod
from . import extraer, fuentes_tipograficas, kinds, ops


class ChatError(RuntimeError):
    """El modelo no produjo algo usable tras su reintento, o falta un asset."""


# Fallos que se reintentan una vez con el error en texto. Una respuesta cortada por
# max_tokens trae el input de la herramienta incompleto: nunca se usa.
_RECUPERABLES = (kinds.SpecInvalido, escena_mod.EscenaInvalida, ops.OpInvalida, ChatError,
                 llm_claude.LLMTruncado, llm_claude.LLMSinHerramienta)


HERRAMIENTA_DISENAR = {
    "name": "disenar",
    "description": "Elige un kind del catálogo y llena su spec. Para cada slot de imagen, "
                   "da una búsqueda corta en inglés (2 a 4 palabras) en `assets`.",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(kinds.KINDS)},
            "spec": {"type": "object", "description": "cumple el esquema del kind elegido"},
            "assets": {"type": "object", "additionalProperties": {"type": "string"},
                       "description": "slot -> búsqueda de foto en inglés"},
            "respuesta": {"type": "string", "description": "una frase para la persona, en español"},
        },
        "required": ["kind", "spec", "respuesta"],
    },
}

HERRAMIENTA_REVISAR = {
    "name": "revisar",
    "description": "Revisa el render. ok=true si se lee bien y nada se encima ni se corta. "
                   "Si no, da los problemas y un spec corregido del MISMO kind.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "problemas": {"type": "array", "items": {"type": "string"}},
            "spec": {"type": "object"},
        },
        "required": ["ok"],
    },
}


def _system_crear(marca, formato: str) -> str:
    catalogo = json.dumps(kinds.catalogo(), ensure_ascii=False)
    return (
        f"Diseñas posts de Instagram para la marca {marca.nombre}"
        f"{' (@' + marca.ig_handle + ')' if marca.ig_handle else ''}.\n"
        f"Voz de la marca: {marca.voz or 'sin definir'}\n"
        f"Formato final: {formato} (se diseña en 4x5 y se adapta).\n\n"
        "Reglas:\n"
        "- Elige el kind que mejor cuente el mensaje. No inventes kinds.\n"
        "- `titulo` es una lista de líneas cortas: tú decides dónde se parte.\n"
        "- `acento` es un fragmento LITERAL de una línea del título.\n"
        "- No inventes cifras ni datos médicos: si el mensaje no trae una cifra, no uses `stat`.\n"
        "- Español de México, sin emojis.\n\n"
        f"Catálogo de kinds (JSON): {catalogo}"
    )


def _pedir_valido(*, system: str, mensajes: list[dict], herramienta: dict,
                  validar: Callable[[dict], Any], uso: list, imagenes=()) -> tuple[dict, Any]:
    salida = {}
    try:
        salida = llm_claude.pedir_herramienta(system=system, mensajes=mensajes,
                                              herramienta=herramienta, imagenes=imagenes, uso=uso)
        return salida, validar(salida)
    except _RECUPERABLES as e:
        error = e
    reintento = mensajes + [
        {"role": "assistant",
         "content": f"Propuesta anterior:\n{json.dumps(salida, ensure_ascii=False)[:6000]}"},
        {"role": "user",
         "content": f"La propuesta no es válida: {error}. Corrígela y vuelve a llamar a "
                    f"{herramienta['name']}."},
    ]
    try:
        salida = llm_claude.pedir_herramienta(system=system, mensajes=reintento,
                                              herramienta=herramienta, uso=uso)
        return salida, validar(salida)
    except _RECUPERABLES as e:
        raise ChatError(f"el modelo no corrigió su propuesta: {e}") from e


def _recortar(cx, marca, fila: dict) -> str:
    """Mismo nombre y misma columna que el job asset.recorte del plan 3."""
    nombre = fila["archivo"].rsplit(".", 1)[0] + "-recorte.png"
    recorte.quitar_fondo(biblioteca.ruta_de(marca.slug, fila["archivo"]),
                         biblioteca.ruta_de(marca.slug, nombre))
    cx.execute("UPDATE brand_assets SET recorte_archivo = ? WHERE id = ? AND account_id = ?",
               (nombre, fila.get("id"), marca.id))
    cx.commit()
    return nombre


def asset_para(cx, marca, consulta: str, *, recortar: bool) -> dict | None:
    # §3: «el primer resultado viable». Una candidata que no se descarga no tumba el post.
    fila = None
    for cand in buscar.buscar(cx, marca.id, marca.slug, consulta, tipo="imagen", n=5):
        try:
            fila = biblioteca.importar(cx, marca.id, marca.slug, cand)
            break
        except biblioteca.AssetInvalido:
            continue
    if fila is None:
        return None
    archivo = fila["archivo"]
    if recortar:
        archivo = fila.get("recorte_archivo") or _recortar(cx, marca, fila)
    fuente = {"proveedor": fila.get("proveedor"), "autor": fila.get("autor"),
              "licencia": fila.get("licencia"), "url": fila.get("url_origen"),
              "ig_handle": fila.get("ig_handle")}
    return {"src": biblioteca.ruta_de(marca.slug, archivo).as_uri(),
            "archivo": f"assets/{archivo}",
            "fuente_asset": {k: (str(v)[:500] if v is not None else None)
                             for k, v in fuente.items()}}


def _resolver_assets(cx, marca, kind: str, spec: dict, consultas: dict) -> dict:
    resueltos: dict[str, dict] = {}
    for slot in kinds.slots(kind, spec):
        consulta = str(consultas.get(slot["id"]) or "").strip()
        if not consulta:
            if slot["requerido"]:
                raise ChatError(f"falta búsqueda para el slot {slot['id']}")
            continue
        asset = asset_para(cx, marca, consulta, recortar=slot["recorte"])
        if asset is None:
            if slot["requerido"]:
                raise ChatError(f"sin resultados para {consulta!r} ({slot['id']})")
            continue
        resueltos[slot["id"]] = asset
    return resueltos


def _componer(cx, marca, kind: str, spec: dict, assets: dict,
              catalogo: list[dict]) -> tuple[bytes, dict, dict]:
    tokens = kinds.tokens_de(marca, spec["tema"])
    fuentes = kinds.fuentes_de(marca, {f["familia"] for f in catalogo}, kind)
    logo = compose._to_src(marca.logo_path) if marca.logo_path else ""
    html = kinds.render(kind, spec, tokens=tokens, fuentes=fuentes, assets=assets,
                        font_faces=kinds.css_fuentes(set(fuentes.values()), catalogo),
                        handle=f"@{marca.ig_handle}" if marca.ig_handle else "", logo=logo)
    return extraer.extraer(html, slug=marca.slug, tokens=tokens, fuente=fuentes["texto"])


def contrato_de(escena: dict, formato: str) -> dict:
    campos = {c["campo"] for c in escena["capas"] if c.get("campo")}
    extras = [{"id": c, "tipo": "texto"}
              for c in sorted(campos - set(contrato_mod.CAMPOS_BASE))]
    return {"aspecto": escena_mod.ASPECTO_DE_FORMATO[formato],
            "base": list(contrato_mod.CAMPOS_BASE), "extras": extras}


def _revisar(png: bytes, kind: str, spec: dict, uso: list) -> dict | None:
    ruta = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            ruta = Path(f.name)
            f.write(png)
        salida = llm_claude.pedir_herramienta(
            system="Eres director de arte. Revisas un post de Instagram ya renderizado.",
            mensajes=[{"role": "user", "content":
                       f"Kind: {kind}\nSpec: {json.dumps(spec, ensure_ascii=False)}\n"
                       f"Esquema: {json.dumps(kinds.esquema_para_llm(kind), ensure_ascii=False)}"}],
            herramienta=HERRAMIENTA_REVISAR, imagenes=[ruta], uso=uso, max_tokens=2048)
    except (llm_claude.LLMTruncado, llm_claude.LLMSinHerramienta):
        return None
    finally:
        if ruta is not None:
            ruta.unlink(missing_ok=True)
    if salida.get("ok") or not isinstance(salida.get("spec"), dict):
        return None
    try:
        return kinds.validar_spec(kind, salida["spec"])
    except kinds.SpecInvalido:
        return None


def crear(cx, marca, mensaje: str, *, formato: str = "4x5",
          uso: list | None = None) -> tuple[dict, dict, dict]:
    uso = [] if uso is None else uso
    if formato not in escena_mod.FORMATOS:
        raise ChatError(f"formato desconocido: {formato!r}")
    catalogo = fuentes_tipograficas.catalogo(cx, marca.id)

    def validar(salida: dict) -> tuple[str, dict]:
        kind = salida.get("kind")
        spec = kinds.validar_spec(kind, salida.get("spec") or {})
        consultas = salida.get("assets") or {}
        faltan = [s["id"] for s in kinds.slots(kind, spec)
                  if s["requerido"] and not str(consultas.get(s["id"]) or "").strip()]
        if faltan:
            raise ChatError(f"faltan búsquedas para los slots {faltan}")
        return kind, spec

    salida, (kind, spec) = _pedir_valido(
        system=_system_crear(marca, formato), mensajes=[{"role": "user", "content": mensaje}],
        herramienta=HERRAMIENTA_DISENAR, validar=validar, uso=uso)
    consultas = salida.get("assets") or {}
    assets = _resolver_assets(cx, marca, kind, spec, consultas)
    png, escena, muestras = _componer(cx, marca, kind, spec, assets, catalogo)

    corregido = _revisar(png, kind, spec, uso)
    if corregido is not None:
        # La crítica es de mejor esfuerzo: si su spec no resuelve assets, se queda el primer render.
        try:
            faltantes = {s["id"] for s in kinds.slots(kind, corregido)} - set(assets)
            nuevos = dict(assets)
            if faltantes:
                nuevos |= _resolver_assets(cx, marca, kind, corregido,
                                           {k: v for k, v in consultas.items() if k in faltantes})
        except ChatError:
            corregido = None
        else:
            assets, spec = nuevos, corregido
            png, escena, muestras = _componer(cx, marca, kind, spec, assets, catalogo)

    if formato != "4x5":
        escena = escena_mod.reformatear(escena, formato)
    contrato = contrato_de(escena, formato)
    escena_mod.validar(escena, contrato, familias={f["familia"] for f in catalogo})
    return escena, contrato, {"kind": kind, "spec": spec, "respuesta": salida["respuesta"],
                              "muestras": muestras, "revisado": corregido is not None}
