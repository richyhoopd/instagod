"""Carrusel de colab "Todo lo que sabemos de <evento>" (blueprint reutilizable).

Promo de un evento en colaboración + contenido estilo The Onion. Portada = el
cartel real; slides internos = titulares deadpan (fondo limpio) reusando el motor
de `compose.render_card`; cierre = CTA. Etiqueta a todos en el caption.

Cada colab = un brief `data/colabs/<slug>.json` con el copy ya escrito (para este
molde el texto es explícito; el spec contempla generarlo por LLM más adelante).
Flujo NO-bloqueante: encola pendiente + manda a Telegram (el daemon aprueba).
Al aprobar se publica de inmediato (tipo='anuncio', regla editorial).

    python -m src.generate_colab moshpit-summer-fest [--dry-run]

Spec: docs/superpowers/specs/2026-07-14-carrusel-colab-blueprint-design.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import approval, compose, db, host

COLABS_DIR = Path("data/colabs")
# Tope de IG: portada + interiores + CTA <= 10 → interiores <= 8.
MAX_INTERIOR = 8


def cargar_brief(slug: str) -> dict:
    path = COLABS_DIR / f"{slug}.json"
    brief = json.loads(path.read_text(encoding="utf-8"))
    for req in ("evento", "fecha_texto", "sede", "cta_handle", "slides"):
        if not brief.get(req):
            raise ValueError(f"Brief {slug}: falta el campo obligatorio '{req}'")
    if brief.get("portada", True):
        if not brief.get("cartel") or not Path(brief["cartel"]).exists():
            raise FileNotFoundError(f"Brief {slug}: portada activa pero falta el cartel")
    for s in brief["slides"]:
        if s.get("imagen") and not Path(s["imagen"]).exists():
            raise FileNotFoundError(f"Brief {slug}: no existe la imagen {s['imagen']}")
    return brief


def caption_colab(brief: dict) -> str:
    """Caption: intro Onion + info real + bloque de @handles únicos. PURO."""
    partes = [brief["caption_intro"].strip(), ""]
    info = f"📍 {brief['evento']} · {brief['fecha_texto']} · {brief['sede']}"
    if brief.get("sede_extra"):
        info += f" ({brief['sede_extra']})"
    partes.append(info)
    partes.append(f"🎟️ {brief['cta_handle']}")
    partes.append("")
    seen: set[str] = set()
    tags: list[str] = []
    for h in brief.get("tags", []):
        h = (h or "").strip()
        if h and h.lower() not in seen:
            seen.add(h.lower())
            tags.append(h)
    partes.append(" ".join(tags))
    return "\n".join(partes).strip()


def slides_interiores(brief: dict) -> list[dict]:
    """Los slides de texto que sí caben (tope MAX_INTERIOR). PURO."""
    return list(brief["slides"][:MAX_INTERIOR])


def render_slides(brief: dict) -> list[Path]:
    """Devuelve las rutas de los PNG del carrusel: portada + interiores + CTA."""
    slug = brief.get("slug", "colab")
    kicker = brief["evento"].upper()
    pngs: list[Path] = []
    if brief.get("portada", True):
        titulo = brief.get("portada_titulo") or f"Todo lo que sabemos sobre el {brief['evento']}"
        p = compose.render_card(
            "colab_portada.html",
            {"kicker": brief.get("portada_kicker", ""), "titulo": titulo,
             "imagen": Path(brief["cartel"]).resolve().as_uri()},
            prefix=f"colab_{slug}_portada",
        )
        pngs.append(p)

    for i, s in enumerate(slides_interiores(brief), 1):
        ctx = {"kicker": kicker, "texto": s["texto"], "handle": s.get("handle", "")}
        if s.get("imagen"):
            # ruta local → file:// absoluto (render corre con origen file://)
            ctx["imagen"] = Path(s["imagen"]).resolve().as_uri()
        p = compose.render_card("colab_slide.html", ctx, prefix=f"colab_{slug}_s{i}")
        pngs.append(p)

    datos = f"{brief['fecha_texto']} · {brief['sede']}"
    if brief.get("sede_extra"):
        datos += f" · {brief['sede_extra']}"
    cta = compose.render_card(
        "colab_cta.html",
        {"kicker": "todo lo que sabemos", "evento": brief["evento"],
         "datos": datos, "cta_texto": brief.get("cta_texto", ""),
         "cta_handle": brief["cta_handle"]},
        prefix=f"colab_{slug}_cta",
    )
    pngs.append(cta)
    return pngs


def generar_y_enviar(slug: str, *, dry_run: bool = False) -> int | None:
    brief = cargar_brief(slug)
    caption = caption_colab(brief)
    pngs = render_slides(brief)
    con_portada = brief.get("portada", True)
    internos = len(pngs) - (1 if con_portada else 0) - 1  # menos portada (si hay) y CTA
    portada_txt = "portada + " if con_portada else "sin portada, "
    print(f"Colab '{slug}': {len(pngs)} slides ({portada_txt}{internos} internos + CTA).")
    for p in pngs:
        print("  ·", p)
    print("\n--- CAPTION ---\n" + caption + "\n---------------")

    if dry_run:
        print("[dry-run] no subo ni mando a Telegram.")
        return None

    urls = [host.upload(str(p), public_id=f"colab_{slug}_{i}") for i, p in enumerate(pngs)]
    imagen = json.dumps(urls)
    cx = db.connect()
    try:
        qid = approval.encolar_pendiente(
            cx, tipo="anuncio", caption=caption, imagen_url=imagen,
            tema_semilla=f"colab {slug}")
        cx.commit()
    finally:
        cx.close()
    approval.enviar_a_telegram(caption, imagen, qid)
    print(f"\n✅ Enviado a Telegram (queue_id={qid}). Apruébalo y se publica de inmediato.")
    return qid


def main() -> int:
    ap = argparse.ArgumentParser(description="Carrusel de colab 'Todo lo que sabemos'")
    ap.add_argument("slug", help="nombre del brief en data/colabs/<slug>.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    generar_y_enviar(args.slug, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
