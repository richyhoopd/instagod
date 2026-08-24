"""Asigna (o cambia) la contraseña de un usuario del portal.

Uso:
    python scripts/portal_password.py correo@x.com 'contraseña'
    python scripts/portal_password.py correo@x.com 'contraseña' --crear --nombre "Nombre"

Lee .env (+ .env.portal-demo si existe) para DB_PATH.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.portal-demo", override=True)

from src import db, users  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("email")
    ap.add_argument("password")
    ap.add_argument("--crear", action="store_true", help="crea el usuario si no existe")
    ap.add_argument("--nombre")
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
    users.set_password(cx, u["id"], a.password)
    print(f"Contraseña asignada a {u['email']} (id {u['id']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
