"""Copia FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN globales del .env a brand_secrets de gdlscene.

Uso (VM):
    docker compose exec -T api python scripts/migrar_fb_gdlscene.py [--db ruta.db] [--forzar]

Desde que src/facebook.py usa credenciales explícitas por marca, el publisher
solo publica en FB con lo que diga account_creds(slug). gdlscene seguía
funcionando por el fallback a env global; esto lo deja cifrado en la DB como
cualquier otra marca. Idempotente: si ya hay valor en DB no lo pisa salvo
--forzar. Nunca imprime valores, solo los últimos 4 caracteres.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from src import db, secrets_store  # noqa: E402

CLAVES = ("FB_PAGE_ID", "FB_PAGE_ACCESS_TOKEN")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--slug", default="gdlscene")
    ap.add_argument("--forzar", action="store_true")
    a = ap.parse_args()

    cx = db.connect(a.db)
    fila = cx.execute("SELECT id FROM accounts WHERE slug=?", (a.slug,)).fetchone()
    if not fila:
        print(f"No existe la cuenta {a.slug}")
        return 1
    account_id = fila[0]

    for clave in CLAVES:
        valor = (os.getenv(clave) or "").strip()
        if not valor:
            print(f"{clave}: sin valor en el env global, nada que migrar")
            continue
        if secrets_store.leer(cx, account_id, clave) and not a.forzar:
            print(f"{clave}: ya está en brand_secrets, se deja (usa --forzar para pisar)")
            continue
        secrets_store.guardar(cx, account_id, clave, valor)
        print(f"{clave}: guardado en brand_secrets de {a.slug} (termina en {valor[-4:]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
