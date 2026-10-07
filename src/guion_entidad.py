"""Reglas del guion de una entidad del catálogo (recetas). Todo PURO.

- La URL del CTA la pone el código, no el LLM: cualquier URL/dominio/correo
  que el LLM escriba y no sea la de la entidad se quita (o se reemplaza por
  la correcta en el cta y el caption), y el último slide y el caption la
  llevan siempre.
- Las claves de `unverified` no las ve el LLM y no puede afirmar nada de esos
  temas (términos por clave en TERMINOS_NO_VERIFICADOS; extensible).
- Redundancias legales absurdas ("listo para escriturar") se rechazan.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

# Términos que, si aparecen, afirman algo sobre una clave sin confirmar.
# Regex sobre texto en minúsculas y sin acentos. Agregar claves aquí.
TERMINOS_NO_VERIFICADOS: dict[str, list[str]] = {
    "regimen": [r"escritur\w*", r"ejid\w*", r"fideicomis\w*",
                r"certeza juridica"],
    "tipo": [r"departamentos?", r"deptos?", r"casas?"],
}

_REDUNDANCIA_LEGAL_RE = re.compile(r"\blist[oa]s? para escritur", re.IGNORECASE)

_TLDS = (r"com|mx|net|org|io|co|info|biz|us|ca|lat|app|site|online|store|xyz|"
         r"realestate|homes|house|properties|property|inmuebles")
# Correos, URLs con esquema, www. y dominios desnudos con TLD conocido.
_URL_RE = re.compile(
    r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
    r"|https?://[^\s<>\"')]+"
    r"|www\.[^\s<>\"')]+"
    r"|\b(?:[a-z0-9-]+\.)+(?:" + _TLDS + r")\b(?:/[^\s<>\"')]*)?",
    re.IGNORECASE)


def _plano(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                   if unicodedata.category(c) != "Mn").lower()


def _norm_url(u: str) -> str:
    u = _plano(u).strip().rstrip(".,;:!?")
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def _limpiar(t: str) -> str:
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"[ \t]+([.,;:!?])", r"\1", t)
    t = re.sub(r"(?:\s+(?:en|a|:|-|–|—))+\s*$", "", t.rstrip())
    return t.strip()


def _fijar_url(texto: str, url: str, *, reemplazar: bool, asegurar: bool) -> str:
    """Quita (o reemplaza por `url`) toda URL ajena; deja la de la entidad
    una sola vez. Con `asegurar`, la agrega al final si no estaba."""
    objetivo = _norm_url(url)
    vista = False

    def _sub(m: re.Match) -> str:
        nonlocal vista
        bruto = m.group(0)
        cola = ""
        while bruto and bruto[-1] in ".,;:!?":
            cola = bruto[-1] + cola
            bruto = bruto[:-1]
        propia = _norm_url(bruto) == objetivo
        if (propia or reemplazar) and not vista:
            vista = True
            return url + cola
        return cola

    out = _limpiar(_URL_RE.sub(_sub, str(texto or "")))
    if asegurar and not vista:
        out = f"{out}\n{url}" if out else url
    return out


def fijar_url_entidad(guion: dict, url: str) -> dict:
    """La URL de la entidad, puesta por código. Muta y devuelve `guion`.

    Último slide (cta) y caption: URLs ajenas → la de la entidad, y si no
    había ninguna se agrega. Resto de textos: URLs ajenas se quitan.
    """
    slides = guion.get("slides") or []
    for i, sl in enumerate(slides):
        if isinstance(sl, dict):
            ultimo = i == len(slides) - 1
            sl["text"] = _fijar_url(sl.get("text"), url, reemplazar=ultimo,
                                    asegurar=ultimo)
    guion["caption"] = _fijar_url(guion.get("caption"), url, reemplazar=True,
                                  asegurar=True)
    for k in ("tema", "hook", "cta"):
        if guion.get(k):
            guion[k] = _fijar_url(guion[k], url, reemplazar=(k == "cta"),
                                  asegurar=False)
    return guion


def facts_visibles(facts: Any, unverified: Iterable[str] | None) -> dict:
    """`facts` sin las claves sin confirmar (lo único que ve el LLM)."""
    fuera = {_plano(k) for k in unverified or []}
    return {k: v for k, v in (facts or {}).items() if _plano(k) not in fuera}


def temas_no_verificados_afirmados(textos: Iterable[str],
                                   unverified: Iterable[str] | None,
                                   facts: Any = None) -> list[str]:
    """Claves de `unverified` sobre las que el texto afirma algo: aparece un
    término de TERMINOS_NO_VERIFICADOS o el valor que tenía en facts."""
    cuerpo = _plano(" ".join(str(t or "") for t in textos))
    facts = facts if isinstance(facts, dict) else {}
    out = []
    for clave in unverified or []:
        patrones = list(TERMINOS_NO_VERIFICADOS.get(_plano(clave), []))
        valor = facts.get(clave)
        if isinstance(valor, str) and valor.strip():
            patrones.append(re.escape(_plano(valor).strip()))
        if any(re.search(r"(?<!\w)" + p + r"(?!\w)", cuerpo) for p in patrones):
            out.append(str(clave))
    return out


def redundancias_legales(textos: Iterable[str]) -> list[str]:
    """Frases legales absurdas ("escriturado y listo para escriturar")."""
    return sorted({m.group(0).lower() for t in textos
                   for m in _REDUNDANCIA_LEGAL_RE.finditer(_plano(t))})


def reglas_prompt(facts: Any, unverified: Iterable[str] | None,
                  url: str | None) -> str:
    """Reglas duras de la ficha que el generador añade al contexto del LLM.
    Prevalecen sobre la receta (cuyo prompt vive en DB y puede ser viejo)."""
    unverified = [str(k) for k in unverified or []]
    sin = {_plano(k) for k in unverified}
    visibles = facts_visibles(facts, unverified)
    lineas = ["REGLAS DE LA FICHA (prevalecen sobre cualquier instrucción anterior):",
              "- No escribas URLs, dominios, correos ni @: la liga de la ficha "
              "la agrega el sistema al último slide y al caption."
              + (" Puedes decir 'ver la ficha completa'." if url else "")]
    if unverified:
        lineas.append(
            f"- TEMAS SIN CONFIRMAR: {', '.join(unverified)}. No afirmes NADA "
            "sobre ellos (ni el valor, ni que está 'en trámite', ni sinónimos); "
            "no los menciones.")
    reg = next((v for k, v in visibles.items() if _plano(k) == "regimen"), None)
    if reg:
        lineas.append(
            f"- Régimen legal: menciónalo UNA sola vez y textual: «{reg}». No lo "
            "parafrasees ni lo repitas: nada de 'listo para escriturar', "
            "'certeza jurídica', 'dentro del marco legal'.")
    elif "regimen" not in sin:
        lineas.append("- No inventes régimen legal ni frases como 'listo para "
                      "escriturar' o 'certeza jurídica'.")
    if "tipo" in sin:
        lineas.append("- El tipo de inmueble no está confirmado: di solo "
                      "«propiedad»; nunca casa, departamento ni depto.")
    return "\n".join(lineas)
