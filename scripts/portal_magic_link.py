"""Genera un magic link del portal sin pasar por correo (útil sin RESEND_API_KEY).

Uso:
    python scripts/portal_magic_link.py correo@x.com            # usuario existente
    python scripts/portal_magic_link.py correo@x.com --crear --nombre "Nombre"
    python scripts/portal_magic_link.py correo@x.com --ttl 120  # minutos de validez

Lee .env (+ .env.portal-demo si existe) para API_URL y DB_PATH; imprime la URL.
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
load_dotenv(ROOT / ".env.portal-demo", override=True)

import config  # noqa: E402
from src import db, users  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("email")
    ap.add_argument("--crear", action="store_true", help="crea el usuario si no existe")
    ap.add_argument("--nombre")
    ap.add_argument("--ttl", type=int, default=60, help="minutos de validez (default 60)")
    a = ap.parse_args()
    cx = db.connect()
    db.init_db(cx)
    u = users.por_email(cx, a.email)
    if not u:
        if not a.crear:
            print(f"No existe {a.email}. Usa --crear (y asígnale marcas en /admin/users).")
            return 1
        users.crear_usuario(cx, a.email, a.nombre)
        u = users.por_email(cx, a.email)
    tok = users.crear_magic_link(cx, u["id"], ttl_min=a.ttl)
    cx.commit()
    print(f"{config.API_URL}/auth/callback?token={tok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
