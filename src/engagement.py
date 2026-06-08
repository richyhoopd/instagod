"""Cerebro de engagement (núcleo PURO). Decide QUÉ generar y reordena la cola.

Dos ejes:
  - BANDA: a quién conviene (ER ya pondera saved×3 en ig_insights) + shares
    (crecimiento) + anti-repetición (repartir, no siempre las mismas). Cold-start
    por (prioridad, followers_ig) cuando la banda tiene < min_posts.
  - FORMATO: qué conviene. Aprende de reach+shares por patrón; cold-start con las
    reglas ya probadas por Ricardo (config.FORMATO_PESOS_COLDSTART).

Las funciones de scoring son PURAS (reciben listas de dicts, devuelven orden/pesos)
para testearse sin red. La capa IO (_cargar_bandas, _cargar_formatos) hace queries.
"""
from __future__ import annotations

from typing import Any

import config


def score_formatos(posts: list[dict[str, Any]], *, min_posts: int) -> dict[str, float]:
    """Peso por patrón de formato. Mezcla reglas (cold-start) con desempeño real.

    Desempeño de un patrón = promedio de (reach + SHARES_PESO*shares) de sus posts,
    normalizado. Si un patrón tiene < min_posts ejemplos, conserva su peso de regla.
    """
    base = dict(config.FORMATO_PESOS_COLDSTART)
    porp: dict[str, list[float]] = {}
    for p in posts:
        val = (p.get("reach") or 0) + config.SHARES_PESO * (p.get("shares") or 0)
        porp.setdefault(p["patron"], []).append(val)
    aprendidos = {k: sum(v) / len(v) for k, v in porp.items() if len(v) >= min_posts}
    if not aprendidos:
        return base
    techo = max(aprendidos.values()) or 1.0
    out = dict(base)
    for k, v in aprendidos.items():  # data manda donde hay; escala 0.5–2.0
        out[k] = 0.5 + 1.5 * (v / techo)
    return out


def _clave_banda(b: dict[str, Any], *, min_posts: int) -> tuple:
    """Clave de orden DESC: con datos usa engagement; sin datos, followers."""
    tiene_datos = (b.get("n_posts") or 0) >= min_posts and b.get("er") is not None
    if tiene_datos:
        score = b["er"] + config.SHARES_PESO * 0.001 * (b.get("shares") or 0)
    else:
        score = (b.get("followers_ig") or 0) / 1e6  # cold-start, escala chica
    # anti-repetición: penaliza si publicó hace poco
    dd = b.get("dias_desde_ultimo")
    pen = 0.0 if dd is None or dd >= config.ANTIREPEAT_DIAS else \
        (config.ANTIREPEAT_DIAS - dd) / config.ANTIREPEAT_DIAS
    return (-(score - pen), b.get("prioridad") or 3)


def score_bandas(bandas: list[dict[str, Any]], *, min_posts: int) -> list[dict[str, Any]]:
    """Ordena bandas por conveniencia (desc). PURO."""
    return sorted(bandas, key=lambda b: _clave_banda(b, min_posts=min_posts))
