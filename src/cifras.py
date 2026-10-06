"""Validación de cifras contra `facts` (spec 2026-10-06 feeds/recetas, punto 5).

Regla: toda cifra que aparezca en el texto generado debe existir en los
`facts` del item del feed. Formatos equivalentes se normalizan antes de
comparar: 3,000,000 · 3'000,000 · 3.000.000 · 3 millones · 3 mdp · 3M.

Además: si el texto menciona algo listado en `unverified` (una clave de facts
o un tema libre) se devuelve como advertencia para poner ⚠️ en la tarjeta de
aprobación — no bloquea, la decisión es humana.

Todo PURO: sin DB ni red.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

# URLs, correos y @handles llevan dígitos que no son cifras del inmueble.
_RUIDO_RE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+|@\w[\w.]*|\b[\w-]+\.(?:com|mx|net|org)\S*",
                       re.IGNORECASE)
# Unidades con dígito pegado (m2, km2) — el "2" es exponente, no cifra.
_UNIDAD_RE = re.compile(r"(?<=[a-zA-Z])[23²³]\b")
# Enumerador al inicio de un slide ("1. ", "2) ") que mete el formato listicle.
_ENUMERADOR_RE = re.compile(r"^\s*\d{1,2}\s*[.)]\s+")

# Número: grupos de miles con , ' ’ . o espacio fino; decimal con . o , y 1-2 dígitos.
_NUM_RE = re.compile(
    r"(?<![\w.,'’])"
    r"(?P<entero>\d{1,3}(?:[,'’.]\d{3})+|\d+)"
    r"(?:[.,](?P<dec>\d{1,2}))?(?!\d)"
    r"(?:\s*(?P<mult>millones|mill[oó]n|mdp|mil|MDP|M|K|k)(?![a-zA-ZáéíóúÁÉÍÓÚ]))?"
)
_MULT = {"millones": 1e6, "millon": 1e6, "millón": 1e6, "mdp": 1e6, "m": 1e6,
         "mil": 1e3, "k": 1e3}


def _quitar_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def numeros(texto: str) -> list[float]:
    """Cifras del texto, normalizadas a float. PURO."""
    if not texto:
        return []
    t = _RUIDO_RE.sub(" ", str(texto))
    t = _UNIDAD_RE.sub("", t)
    out: list[float] = []
    for m in _NUM_RE.finditer(t):
        entero = re.sub(r"[,'’.]", "", m.group("entero"))
        valor = float(entero)
        if m.group("dec"):
            valor += float("0." + m.group("dec"))
        mult = (m.group("mult") or "").lower()
        if mult:
            valor *= _MULT.get(mult, 1)
        out.append(round(valor, 2))
    return out


def numeros_de_facts(facts: Any) -> set[float]:
    """Todas las cifras citables de `facts` (recursivo sobre dict/list). PURO."""
    out: set[float] = set()

    def _recorrer(v: Any) -> None:
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            out.add(round(float(v), 2))
        elif isinstance(v, str):
            out.update(numeros(v))
        elif isinstance(v, dict):
            for x in v.values():
                _recorrer(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                _recorrer(x)

    _recorrer(facts)
    return out


def textos_de_guion(guion: dict) -> list[str]:
    """Los textos que el LLM escribió y que se publican (no image_hint)."""
    textos = [str(guion.get(k) or "") for k in ("tema", "hook", "caption", "cta")]
    for sl in guion.get("slides") or []:
        if isinstance(sl, dict):
            textos.append(_ENUMERADOR_RE.sub("", str(sl.get("text") or "")))
    return [t for t in textos if t]


def cifras_fuera(textos: Iterable[str], facts: Any) -> list[str]:
    """Cifras del texto que NO están en facts, como aparecen formateadas. PURO.

    [] = el texto es citable.
    """
    permitidas = numeros_de_facts(facts or {})
    fuera: list[str] = []
    for texto in textos:
        t = _UNIDAD_RE.sub("", _RUIDO_RE.sub(" ", str(texto or "")))
        for m in _NUM_RE.finditer(t):
            valor = numeros(m.group(0))
            if valor and valor[0] not in permitidas and m.group(0).strip() not in fuera:
                fuera.append(m.group(0).strip())
    return fuera


def menciones_no_verificadas(textos: Iterable[str], facts: Any,
                             unverified: Iterable[str] | None) -> list[str]:
    """Elementos de `unverified` que el texto menciona. PURO.

    Una clave cuenta como mencionada si aparece su nombre (sin acentos,
    `_`→espacio) o el valor que tiene en facts.
    """
    cuerpo = _quitar_acentos(" ".join(str(t or "") for t in textos)).lower()
    facts = facts if isinstance(facts, dict) else {}
    out: list[str] = []
    for clave in unverified or []:
        nombre = _quitar_acentos(str(clave)).lower().replace("_", " ").strip()
        candidatos = [nombre] if nombre else []
        valor = facts.get(clave)
        if isinstance(valor, str) and valor.strip():
            candidatos.append(_quitar_acentos(valor).lower().strip())
        if any(c and re.search(r"(?<!\w)" + re.escape(c) + r"(?!\w)", cuerpo)
               for c in candidatos):
            out.append(str(clave))
    return out
