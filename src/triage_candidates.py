"""Triage de candidatas: clasifica cada cuenta en un TIPO de actor.

Lee el perfil (categoría IG + bio) de cada banda candidata (activa=0) y le asigna
uno de los cinco tipos que definen el ángulo del chiste y el filtro de fotos:

  banda · solista · foro · evento · colectivo

Si la cuenta no es ninguno (fotógrafo, tienda, persona random, fan), la deja
candidata con nota "🔴 prob. borrar: <motivo>". Las que no se pueden clasificar
por categoría quedan "🟡 dudosa: <pista>" para que tú decidas el tipo en la GUI.

Las que SÍ son actores claros se activan solas (reversible) con su tipo. Guarda
bio, followers y category_ig de paso. Es RESUMIBLE (salta las que ya tienen
category_ig), así que si IG limita la sesión, reanudas y continúa.

Uso:
    python -m src.triage_candidates           # candidatas sin triage
    python -m src.triage_candidates --redo     # re-procesa todas (re-fetch)
    python -m src.triage_candidates --limit 30
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Any

from src import db
from src.ingest_ig import IngestRateLimited, _sleep, fetch_profile, get_session

# Categoría IG (lowercase, por PALABRA completa) → tipo de actor.
# El orden importa: se evalúa de arriba a abajo, primer match gana.
_CAT_A_TIPO: list[tuple[tuple[str, ...], str]] = [
    (("record label", "music production", "producer", "production"), "colectivo"),
    (("musician", "band", "artist", "singer", "composer", "rapper",
      "songwriter", "dj", "music video"), "banda"),
    (("bar", "pub", "night club", "nightclub", "club", "live music venue",
      "concert venue", "performance & event venue", "concert room",
      "cultural center", "cultural", "art", "arts & entertainment"), "foro"),
    (("event planner", "event", "festival"), "evento"),
    (("community", "media", "magazine", "radio", "blog", "non-profit",
      "organization", "society"), "colectivo"),
]
# Categorías que NO son un actor de la escena → recomendar borrar.
_CAT_BORRAR = {
    "photographer": "fotografía", "photography": "fotografía", "videography": "video",
    "clothing": "tienda", "shopping": "tienda", "store": "tienda",
    "restaurant": "restaurante", "product/service": "marca",
    "personal blog": "persona", "digital creator": "creador",
    "public figure": "figura pública", "writer": "persona",
}
# Pistas de bio cuando no hay categoría (asignan tipo tentativo, quedan 🟡).
_BIO_TIPO: list[tuple[tuple[str, ...], str]] = [
    (("foro", "venue", "sala de ensayo", "escenario", "espacio cultural"), "foro"),
    (("festival", "live session", "sessions", "ciclo", "edición", "line up", "lineup"), "evento"),
    (("sello", "promotora", "booking", "colectivo", "gestión cultural",
      "radio", "podcast", "revista", "medios"), "colectivo"),
    (("banda", "vocalista", "guitarrista", "baterista", "bajista", "powertrío",
      "power trío", "trío", "cuarteto", "quinteto"), "banda"),
    (("solista", "cantautor", "cantautora", "productor musical", "beatmaker"), "solista"),
]
_BIO_MUSICA = ("ep ", "álbum", "single", "sencillo", "spotify", "escúchanos",
               "nuevo disco", "rock", "punk", "metal", "indie", "shoegaze", "post-punk")


def _palabra_en(claves, texto: str) -> bool:
    """True si alguna clave aparece como PALABRA completa en `texto`.

    Match por límite de palabra (no substring): evita que 'bar' active "Bartender",
    'pub' a "Public Figure" o 'club' a "nightclub". Las claves multipalabra (p. ej.
    "live music venue") se buscan con sus espacios como frase, también con bordes.
    """
    return any(re.search(rf"\b{re.escape(k)}\b", texto) for k in claves)


def clasificar(categoria: str | None, bio: str | None) -> tuple[str | None, str, str]:
    """(tipo|None, decision, motivo). decision ∈ {'activar','borrar','dudosa'}."""
    cat = (categoria or "").lower()
    low = (bio or "").lower()

    # BORRAR antes que ACTIVAR: las señales de "no es un actor de la escena"
    # (photographer, store, personal blog, public figure…) son más específicas y
    # deben descalificar primero, sin que una palabra genérica de actor las pise.
    for clave, etiqueta in _CAT_BORRAR.items():
        if re.search(rf"\b{re.escape(clave)}\b", cat):
            return None, "borrar", etiqueta
    for claves, tipo in _CAT_A_TIPO:
        if _palabra_en(claves, cat):
            return tipo, "activar", f"categoría IG: {categoria}"

    # Sin categoría útil → heurística de bio (queda dudosa, tipo tentativo).
    for claves, tipo in _BIO_TIPO:
        if any(k in low for k in claves):
            return tipo, "dudosa", f"bio sugiere {tipo} (confirma)"
    if any(k in low for k in _BIO_MUSICA):
        return "banda", "dudosa", "bio suena musical (banda/solista, confirma)"
    if categoria:
        return None, "dudosa", f"categoría: {categoria}"
    return None, "dudosa", "sin categoría ni pistas en bio"


def _aplicar(cx, band: dict[str, Any], categoria, bio, followers, link) -> str:
    tipo, decision, motivo = clasificar(categoria, bio)
    base = dict(category_ig=categoria, bio=bio, followers_ig=followers,
                link_externo=link or None)
    if decision == "activar":
        db.update(cx, "bands", band["id"], activa=1, tipo=tipo, notas=None, **base)
        return f"✅ {tipo.upper()} ({motivo}) → activada"
    if decision == "borrar":
        db.update(cx, "bands", band["id"], notas=f"🔴 prob. borrar: {motivo}", **base)
        return f"🔴 borrar ({motivo})"
    # dudosa: guarda tipo tentativo pero no activa
    if tipo:
        db.update(cx, "bands", band["id"], tipo=tipo, notas=f"🟡 dudosa: {motivo}", **base)
    else:
        db.update(cx, "bands", band["id"], notas=f"🟡 dudosa: {motivo}", **base)
    return f"🟡 dudosa ({motivo})"


def triage(limite: int | None = None, redo: bool = False) -> dict[str, int]:
    cx = db.connect()
    try:
        db.init_db(cx)
        cond = "" if redo else "AND category_ig IS NULL"
        pend = db.rows(cx, f"SELECT * FROM bands WHERE activa = 0 {cond} ORDER BY id")
        if limite:
            pend = pend[:limite]
        if not pend:
            print("No hay candidatas pendientes de triage.")
            return {}

        session = get_session()
        print(f"Triage de {len(pend)} candidata(s)…")
        conteo = {"activar": 0, "borrar": 0, "dudosa": 0}
        for b in pend:
            handle = b["ig_handle"]
            try:
                u = fetch_profile(session, handle)
            except IngestRateLimited as exc:
                print(f"\n❌ {exc} — guardo lo hecho y paro. Reanuda más tarde.")
                break
            except Exception as exc:  # noqa: BLE001
                db.update(cx, "bands", b["id"], notas="🟡 dudosa: perfil ilegible")
                print(f"  @{handle}: ⚠️ ilegible ({str(exc)[:40]})")
                continue
            etiqueta = _aplicar(cx, b, u.get("category_name"),
                                (u.get("biography") or "").strip() or None,
                                u.get("edge_followed_by", {}).get("count"),
                                u.get("external_url"))
            decision = "activar" if etiqueta.startswith("✅") else \
                       "borrar" if etiqueta.startswith("🔴") else "dudosa"
            conteo[decision] += 1
            print(f"  @{handle}: {etiqueta}")
            _sleep()

        print(f"\nResumen: {conteo['activar']} activadas con tipo · "
              f"{conteo['borrar']} a borrar (🔴) · {conteo['dudosa']} dudosas (🟡)")
        return conteo
    finally:
        cx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Triage de candidatas por tipo de actor")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--redo", action="store_true", help="re-procesa todas (re-fetch)")
    args = parser.parse_args()
    try:
        triage(args.limit, args.redo)
    except KeyboardInterrupt:
        sys.exit("\nTriage interrumpido.")
