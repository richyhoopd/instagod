"""Arranque del portal desde CLI.

  python -m api.bootstrap --nueva-master-key
  python -m api.bootstrap --admin tu@email.com [--nombre "Ricardo"]
  python -m api.bootstrap --importar-env [--forzar]
"""
from __future__ import annotations

import argparse
import os
import sys

from cryptography.fernet import Fernet

import config
from src import db, users
from src import secrets_store as ss


def nueva_master_key() -> str:
    return Fernet.generate_key().decode()


def asegurar_admin(cx, email: str, nombre: str | None = None) -> tuple[int, str]:
    """Crea (o promueve) al admin y devuelve (uid, token de magic link)."""
    u = users.por_email(cx, email)
    if u:
        uid = u["id"]
        db.update(cx, "users", uid, is_admin=1, activo=1)
    else:
        uid = users.crear_usuario(cx, email, nombre, is_admin=True)
    return uid, users.crear_magic_link(cx, uid, ttl_min=60)


def importar_env(cx, environ, *, forzar: bool = False) -> dict[str, list[str]]:
    """Copia secretos KEY__SLUG (y globales para gdlscene) del entorno a brand_secrets."""
    res: dict[str, list[str]] = {}
    for a in db.list_accounts(cx, solo_activas=True):
        slug, importadas = a["slug"], []
        ya = set(ss.leer_todos(cx, a["id"]))
        for clave in ss.CLAVES:
            val = environ.get(f"{clave}__{slug.upper()}")
            if val is None and slug == "gdlscene":
                val = environ.get(clave)
            if not val or (clave in ya and not forzar):
                continue
            ss.guardar(cx, a["id"], clave, val)
            importadas.append(clave)
        res[slug] = importadas
    return res


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--nueva-master-key", action="store_true")
    p.add_argument("--admin", metavar="EMAIL")
    p.add_argument("--nombre")
    p.add_argument("--importar-env", action="store_true")
    p.add_argument("--forzar", action="store_true")
    a = p.parse_args(argv)
    if a.nueva_master_key:
        print(nueva_master_key())
        return 0
    cx = db.connect()
    try:
        db.init_db(cx)
        if a.admin:
            uid, tok = asegurar_admin(cx, a.admin, a.nombre)
            print(f"Admin listo (id={uid}). Entra con:\n"
                  f"  {config.API_URL}/auth/callback?token={tok}")
        if a.importar_env:
            if not ss.habilitado():
                print("Falta INSTAGOD_MASTER_KEY en .env", file=sys.stderr)
                return 2
            for slug, claves in importar_env(cx, os.environ, forzar=a.forzar).items():
                print(f"{slug}: {', '.join(claves) or '(nada nuevo)'}")
        if not (a.admin or a.importar_env):
            p.print_help()
    finally:
        cx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
