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
from src import db

# La Graph API devuelve `2026-08-24T21:22:15+0000`: un offset SIN dos puntos que
# SQLite no sabe parsear → julianday() daba NULL en las 154 filas de prod, así que
# `dias_desde_ultimo` era SIEMPRE None y la penalización anti-repetición de
# `_clave_banda` nunca se aplicó. Normalizamos `±HHMM` a `±HH:MM` antes de medir,
# con fallback a la parte naive por si algún día llega otro formato.
_JULIANDAY_TS = """
        COALESCE(
          julianday(CASE
            WHEN timestamp GLOB '*[+-][0-9][0-9][0-9][0-9]'
              THEN substr(timestamp, 1, length(timestamp) - 2) || ':' || substr(timestamp, -2)
            ELSE timestamp
          END),
          julianday(substr(timestamp, 1, 19))
        )
"""


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


def rerank_cola(items: list[dict[str, Any]], *, pesos_formato: dict[str, float]) -> list[dict[str, Any]]:
    """Reasigna los slots futuros a los items mejor puntuados (formato×banda).

    Los slots (scheduled) se mantienen como conjunto; se reparten al orden nuevo:
    el item de mayor score toma el slot más temprano. PURO.
    """
    slots = sorted(i["scheduled"] for i in items)
    # multiplicativo puro con piso chico: sin el piso, band_score=0 anularía el
    # formato; sin multiplicar, el formato taparía a la banda (bug original).
    rank = sorted(items, key=lambda i: -(pesos_formato.get(i["patron"], 1.0)
                                         * max(i.get("band_score") or 0.0, 0.01)))
    return [{**it, "scheduled": slot} for it, slot in zip(rank, slots)]


def score_plan(bandas: list[dict[str, Any]], *,
               peso_engagement: float | None = None,
               peso_recencia: float | None = None,
               techo_dias: int | None = None,
               techo_coldstart: float | None = None) -> dict[int, float]:
    """{band_id: score 0..1} para planear un mes entero. PURO.

    Mezcla los dos ejes que importan al armar un mes: cómo le fue a la banda EN
    NUESTRA CUENTA (ER + shares, igual que `_clave_banda`) y cuánto llevamos sin
    publicarla.

    Difiere de `score_bandas` —que ordena para el motor de segmentos— en dos
    cosas deliberadas:

    - Normaliza AMBOS ejes a 0..1 antes de mezclarlos. En `_clave_banda` la
      penalización de recencia llega a 1.0 mientras el ER de la cuenta vive
      entre 0.016 y 0.188, así que la recencia aplastaba al engagement.
    - Una banda que NUNCA hemos publicado no es "hace mucho que no la
      publicamos": no hay historial que premiar. Entra con recencia neutra (0.5)
      y con el eje de engagement topado a `techo_coldstart`, para que no
      desplace a una que ya demostró funcionar.
    """
    peso_engagement = config.PLAN_PESO_ENGAGEMENT if peso_engagement is None else peso_engagement
    peso_recencia = config.PLAN_PESO_RECENCIA if peso_recencia is None else peso_recencia
    techo_dias = config.PLAN_RECENCIA_TECHO_DIAS if techo_dias is None else techo_dias
    techo_coldstart = config.PLAN_COLDSTART_TECHO if techo_coldstart is None else techo_coldstart

    # Eje ENGAGEMENT: misma señal que _clave_banda (ER + shares ponderados).
    inter = {b["band_id"]: b["er"] + config.SHARES_PESO * 0.001 * (b.get("shares") or 0)
             for b in bandas if b.get("er") is not None}
    techo_inter = max(inter.values(), default=0.0) or 1.0
    techo_fol = max((b.get("followers_ig") or 0) for b in bandas) if bandas else 0

    out: dict[int, float] = {}
    for b in bandas:
        bid = b["band_id"]
        if bid in inter:
            eng = inter[bid] / techo_inter
        else:  # cold-start: followers como proxy, topado para no ganarle al dato real
            eng = techo_coldstart * ((b.get("followers_ig") or 0) / techo_fol) if techo_fol else 0.0
        dd = b.get("dias_desde_ultimo")
        rec = 0.5 if dd is None else min(max(dd, 0), techo_dias) / techo_dias
        out[bid] = peso_engagement * eng + peso_recencia * rec
    return out


# ---------- Capa IO (queries; separada del núcleo PURO de arriba) ----------

def _cargar_bandas(cx, account_id: int) -> list[dict[str, Any]]:
    """Filas por banda para score_bandas: extiende ig_insights.band_stats con
    `shares` y `dias_desde_ultimo` por banda, e incluye `followers_ig`.

    band_stats solo regresa bandas CON posts; aquí partimos de TODAS las bandas
    activas de la cuenta (para que las cold-start sin posts también compitan) y
    fusionamos las métricas calculadas. PURO sobre lectura: solo SELECTs.
    """
    from src import ig_insights

    stats = {s["band_id"]: s for s in ig_insights.band_stats(cx)}
    # shares + última fecha de publicación por banda (vía ig_posts del bot).
    extra = {r["band_id"]: r for r in db.rows(cx, f"""
        SELECT band_id,
               SUM(COALESCE(shares, 0))            AS shares,
               julianday('now') - MAX({_JULIANDAY_TS}) AS dias_desde_ultimo
          FROM ig_posts
         WHERE band_id IS NOT NULL
         GROUP BY band_id
    """)}

    out: list[dict[str, Any]] = []
    for b in db.list_bands(cx, solo_activas=True):
        if b.get("account_id") not in (None, account_id):
            continue
        s = stats.get(b["id"], {})
        e = extra.get(b["id"], {})
        dd = e.get("dias_desde_ultimo")
        out.append({
            "band_id": b["id"],
            "nombre": b["nombre"],
            "prioridad": b.get("prioridad") or 3,
            "followers_ig": b.get("followers_ig"),
            "n_posts": s.get("n_posts", 0),
            "er": s.get("er"),
            "shares": e.get("shares") or 0,
            "dias_desde_ultimo": int(dd) if dd is not None else None,
        })
    return out


def _cargar_formatos(cx) -> list[dict[str, Any]]:
    """Filas de desempeño por formato para score_formatos (vía format_tags)."""
    from src import format_tags

    return format_tags.atributos_por_post(cx)


def _foto_no_usada(cx, band_id: int) -> int | None:
    """id de una foto usable, no descartada y no usada de la banda (o None)."""
    filas = db.rows(cx, """
        SELECT id FROM photos
         WHERE band_id = ? AND usable_meme = 1 AND descartada = 0 AND usada = 0
         ORDER BY id LIMIT 1
    """, (band_id,))
    return filas[0]["id"] if filas else None


def elegir_candidatos(cx, n: int, *, account_id: int = 1) -> list[dict[str, Any]]:
    """Cruza ambos ejes y devuelve hasta `n` candidatos a generar.

    Eje BANDA: ordena con score_bandas; toma las mejores que tengan una foto
    usable sin usar. Eje FORMATO: adjunta el patrón de mayor peso disponible
    (score_formatos). La capa IO vive aquí; el scoring de arriba es PURO.
    """
    bandas = score_bandas(_cargar_bandas(cx, account_id),
                          min_posts=config.ENGAGEMENT_MIN_POSTS)
    pesos = score_formatos(_cargar_formatos(cx), min_posts=config.ENGAGEMENT_MIN_POSTS)
    patron_top = max(pesos, key=pesos.get)

    candidatos: list[dict[str, Any]] = []
    for b in bandas:
        if len(candidatos) >= n:
            break
        foto_id = _foto_no_usada(cx, b["band_id"])
        if foto_id is None:
            continue
        # Misma señal que _clave_banda: con datos usa ER; cold-start usa followers/1M
        tiene_datos = (b.get("n_posts") or 0) >= config.ENGAGEMENT_MIN_POSTS and b.get("er") is not None
        band_score: float = (
            b["er"] + config.SHARES_PESO * 0.001 * (b.get("shares") or 0)
            if tiene_datos
            else (b.get("followers_ig") or 0) / 1e6
        )
        candidatos.append({
            "band_id": b["band_id"],
            "nombre": b["nombre"],
            "photo_id": foto_id,
            "formato_patron": patron_top,
            "band_score": band_score,
        })
    return candidatos
