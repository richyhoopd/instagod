"""Dispatcher idempotente del registro de segmentos.

Dispara los segmentos cuya cadencia toca hoy y que NO se han corrido en su
ventana actual (segment_runs). Un generador que truena no tumba a los demás.
CLI:  python -m src.segment_runner [--cuenta gdlscene] [--force]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

import pytz

import config
from src import db, segments
from src.segments import Segment


def _ya_corrio(cx, seg: Segment, ventana: str, account_id: int) -> bool:
    return bool(db.rows(cx,
        "SELECT 1 FROM segment_runs WHERE segmento=? AND account_id=? AND ventana=?",
        (seg.clave, account_id, ventana)))


def dispatch(cx, registro: list[Segment], *, ahora: datetime | None = None,
             account_id: int = 1, force: bool = False) -> list[str]:
    # Hora de la ESCENA (CST), no la del reloj de la máquina: si la Mac está en
    # otro huso, "toca_hoy" (martes/viernes/día 1) debe evaluarse en Mexico_City,
    # o el segmento se dispararía en la fecha equivocada.
    ahora = ahora or datetime.now(pytz.timezone(config.TIMEZONE))
    corridos = []
    for seg in registro:
        if not seg.activo or not segments.toca_hoy(seg, ahora):
            continue
        ventana = segments.ventana_de(seg.clave, ahora)
        if not force and _ya_corrio(cx, seg, ventana, account_id):
            continue
        try:
            seg.generador(cx, account_id)
            db.insert(cx, "segment_runs", segmento=seg.clave,
                      account_id=account_id, ventana=ventana)
            corridos.append(seg.clave)
        except Exception as exc:  # un segmento roto no tumba la tanda
            print(f"⚠️ segmento {seg.clave} falló: {exc}", file=sys.stderr)
    return corridos


def main() -> int:
    from src.catalogo import (
        REGISTRO,  # catálogo real (Task G); import tardío para no romper tests
    )
    parser = argparse.ArgumentParser(description="Dispatcher de segmentos")
    parser.add_argument("--cuenta", default="gdlscene")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    cx = db.connect()
    try:
        db.init_db(cx)
        acc = db.get_account(cx, args.cuenta)
        account_id = acc["id"] if acc else 1
        hechos = dispatch(cx, REGISTRO, account_id=account_id, force=args.force)
        print(f"Segmentos disparados: {hechos or 'ninguno (no tocaba o ya corrieron)'}")
    finally:
        cx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
