"""Importa un plan de contenido renderizado afuera a content_queue (borradores).

Uso:
    # Mac: sube media a Cloudinary (dedup por sha1) y escribe el manifiesto
    python scripts/importar_plan.py manifiesto ~/ruta/plan --out plan.json
    # VM (o una copia de la DB): inserta las filas de la marca
    python scripts/importar_plan.py cargar plan.json --slug melaquecapital [--db ruta.db]

Ver src/plan_import.py. Nada queda programado ni aprobado: el publisher no lo toca.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import config  # noqa: E402
from src import db, plan_import  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifiesto")
    m.add_argument("plan", type=Path)
    m.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("cargar")
    c.add_argument("manifiesto", type=Path)
    c.add_argument("--slug", required=True)
    c.add_argument("--db", type=Path, default=None)
    a = ap.parse_args()

    if a.cmd == "manifiesto":
        from src import host
        filas = plan_import.manifiesto(
            a.plan.expanduser(), tz=config.TIMEZONE,
            subir_imagen=lambda p, pid: host.upload(p, public_id=pid),
            subir_video=lambda p, pid: host.upload_video(p, public_id=pid))
        a.out.write_text(json.dumps(filas, ensure_ascii=False, indent=1))
        print(f"{len(filas)} filas → {a.out}")
        return 0

    cx = db.connect(a.db)
    db.init_db(cx)
    marca = cx.execute("SELECT id FROM accounts WHERE slug=?", (a.slug,)).fetchone()
    if not marca:
        print(f"no existe la marca {a.slug}", file=sys.stderr)
        return 1
    filas = json.loads(a.manifiesto.read_text())
    nuevas, repetidas = plan_import.cargar(cx, marca["id"], filas)
    print(f"{a.slug}: {nuevas} insertadas, {repetidas} ya existían")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
