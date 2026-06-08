"""Re-ranker dinámico de la cola de contenido.

Lee los items FUTUROS aún no publicados (status='en_sheet' y scheduled_datetime
> ahora), calcula pesos por formato con engagement.score_formatos y un band_score
proxy por banda, llama rerank_cola (PURO) y actualiza scheduled_datetime en DB
y en el Sheet (sheets.update_row).

Por defecto corre en modo dry-run (imprime qué cambiaría sin tocar nada).
Para aplicar los cambios: pasar --no-dry-run.

CLI:
    python -m src.rerank_runner [--cuenta gdlscene] [--no-dry-run]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

import config
from src import db, engagement


def _items_futuros(cx, account_id: int) -> list[dict]:
    """Items en_sheet con scheduled_datetime en el futuro (tienen slot asignado)."""
    ahora = datetime.now().isoformat()
    return db.rows(cx, """
        SELECT id AS queue_id,
               formato_patron      AS patron,
               band_id,
               sheet_row_id,
               scheduled_datetime  AS scheduled
          FROM content_queue
         WHERE status        = 'en_sheet'
           AND scheduled_datetime > ?
           AND account_id   = ?
         ORDER BY scheduled_datetime
    """, (ahora, account_id))


def _band_score_map(cx, account_id: int) -> dict[int, float]:
    """Proxy de band_score: ER del último período por banda, o 0.0 si no hay datos.

    Usa _cargar_bandas que ya extiende band_stats con shares y dias_desde_ultimo.
    Devuelve {band_id: score} donde score = ER (o followers/1M en cold-start).
    Solo es un proxy para el reranker; lo que importa es el orden relativo.
    """
    bandas = engagement._cargar_bandas(cx, account_id)
    out: dict[int, float] = {}
    for b in bandas:
        er = b.get("er")
        if er is not None:
            out[b["band_id"]] = float(er)
        else:
            # cold-start: usa followers escalados (misma lógica que _clave_banda)
            out[b["band_id"]] = (b.get("followers_ig") or 0) / 1_000_000
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-ranker dinámico de la cola: reasigna slots por score de engagement."
    )
    parser.add_argument("--cuenta", default="gdlscene",
                        help="Slug de la cuenta (default: gdlscene)")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                        help="Aplicar los cambios en DB y Sheet (sin esta flag = solo imprime)")
    parser.set_defaults(dry_run=True)
    args = parser.parse_args()

    cx = db.connect()
    try:
        db.init_db(cx)
        acc = db.get_account(cx, args.cuenta)
        account_id = acc["id"] if acc else 1

        items = _items_futuros(cx, account_id)
        if not items:
            print("No hay items futuros en cola para reordenar.")
            return 0

        # Carga pesos de formato (data-driven o cold-start)
        posts_formato = engagement._cargar_formatos(cx)
        pesos = engagement.score_formatos(posts_formato, min_posts=config.ENGAGEMENT_MIN_POSTS)

        # Agrega band_score a cada item (proxy por ER o followers)
        bscore = _band_score_map(cx, account_id)
        for it in items:
            it["band_score"] = bscore.get(it["band_id"] or 0, 0.0)

        # Rerank PURO: reasigna slots por score
        reordenados = engagement.rerank_cola(items, pesos_formato=pesos)

        # Construye mapa de cambios: {queue_id: (scheduled_viejo, scheduled_nuevo)}
        viejo = {it["queue_id"]: it["scheduled"] for it in items}
        cambios = [
            (it["queue_id"], it["sheet_row_id"], viejo[it["queue_id"]], it["scheduled"])
            for it in reordenados
            if it["scheduled"] != viejo[it["queue_id"]]
        ]

        if not cambios:
            print("El rerank no produce cambios de slot (ya están en el orden óptimo).")
            return 0

        modo = "DRY-RUN" if args.dry_run else "APLICANDO"
        print(f"\n[{modo}] Cambios de scheduled_datetime para cuenta={args.cuenta}:\n")
        print(f"  {'queue_id':>10}  {'sheet_id':>10}  {'antes':>20}  {'después':>20}")
        print("  " + "-" * 66)
        for qid, sid, antes, despues in cambios:
            print(f"  {qid:>10}  {str(sid or '—'):>10}  {antes:>20}  {despues:>20}")

        if args.dry_run:
            print(f"\n  ({len(cambios)} cambio(s) — usa --no-dry-run para aplicar)")
            return 0

        # Aplicar: actualiza DB y Sheet
        from src import sheets
        for qid, sid, _, nuevo_slot in cambios:
            db.update(cx, "content_queue", qid, scheduled_datetime=nuevo_slot)
            if sid:
                # update_row recibe el id de columna del Sheet (sheet_row_id)
                try:
                    sheets.update_row(sid, scheduled_datetime=nuevo_slot)
                except Exception as exc:
                    print(f"  ⚠️  Sheet update falló para sheet_id={sid}: {exc}",
                          file=sys.stderr)

        print(f"\n  {len(cambios)} cambio(s) aplicados en DB y Sheet.")

    finally:
        cx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
