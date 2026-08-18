"""Secretos por marca cifrados en `brand_secrets` (Fernet con INSTAGOD_MASTER_KEY).

Reglas: el valor jamás se loguea ni se devuelve en metadatos (solo últimos 4);
sin master key el módulo está apagado (habilitado() False) y la resolución de
credenciales cae a env. Las claves permitidas son cerradas (CLAVES).
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

import config
from src import db

CLAVES: tuple[str, ...] = (
    "IG_USER_ID", "IG_ACCESS_TOKEN",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL",
    "PEXELS_API_KEY", "UNSPLASH_ACCESS_KEY", "NEWSAPI_KEY",
    "SHEET_ID",
)


class SinMasterKey(RuntimeError):
    """INSTAGOD_MASTER_KEY no está configurada."""


def habilitado() -> bool:
    return bool(config.INSTAGOD_MASTER_KEY)


def _fernet() -> Fernet:
    if not config.INSTAGOD_MASTER_KEY:
        raise SinMasterKey("Falta INSTAGOD_MASTER_KEY: los secretos en DB están apagados")
    return Fernet(config.INSTAGOD_MASTER_KEY.encode())


def cifrar(valor: str) -> str:
    return _fernet().encrypt(valor.encode("utf-8")).decode("ascii")


def descifrar(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def guardar(cx: sqlite3.Connection, account_id: int, clave: str, valor: str,
            *, user_id: int | None = None) -> None:
    """Upsert cifrado. KeyError si la clave no es de CLAVES; ValueError si vacía."""
    if clave not in CLAVES:
        raise KeyError(f"Clave de secreto no permitida: {clave}")
    if not valor or not valor.strip():
        raise ValueError(f"El valor de {clave} no puede estar vacío")
    cx.execute(
        "INSERT INTO brand_secrets(account_id, clave, valor_cifrado, updated_by, updated_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(account_id, clave) DO UPDATE SET valor_cifrado=excluded.valor_cifrado, "
        "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        (account_id, clave, cifrar(valor.strip()), user_id, _ahora()))
    cx.commit()


def borrar(cx: sqlite3.Connection, account_id: int, clave: str) -> bool:
    cur = cx.execute("DELETE FROM brand_secrets WHERE account_id=? AND clave=?",
                     (account_id, clave))
    cx.commit()
    return cur.rowcount > 0


def leer(cx: sqlite3.Connection, account_id: int, clave: str) -> str | None:
    if not habilitado():
        return None
    fila = cx.execute("SELECT valor_cifrado FROM brand_secrets WHERE account_id=? AND clave=?",
                      (account_id, clave)).fetchone()
    return descifrar(fila[0]) if fila else None


def leer_todos(cx: sqlite3.Connection, account_id: int) -> dict[str, str]:
    """{clave: valor} de la marca. Un token indescifrable (llave rotada) se salta con aviso."""
    if not habilitado():
        return {}
    out: dict[str, str] = {}
    for f in db.rows(cx, "SELECT clave, valor_cifrado FROM brand_secrets WHERE account_id=?",
                     (account_id,)):
        try:
            out[f["clave"]] = descifrar(f["valor_cifrado"])
        except InvalidToken:
            print(f"[secretos] {f['clave']} de account {account_id} no descifra "
                  "(¿cambió INSTAGOD_MASTER_KEY?)", file=sys.stderr)
    return out


def listar_meta(cx: sqlite3.Connection, account_id: int) -> list[dict]:
    """Metadatos de TODAS las claves posibles, sin valores."""
    filas = {f["clave"]: f for f in db.rows(
        cx, "SELECT clave, valor_cifrado, updated_at FROM brand_secrets WHERE account_id=?",
        (account_id,))}
    out = []
    for clave in CLAVES:
        f = filas.get(clave)
        if not f:
            out.append({"clave": clave, "configurada": False, "ultimos4": None,
                        "updated_at": None})
            continue
        if not habilitado():
            # Sin master key, mostrar que existe pero sin intentar descifrar
            out.append({"clave": clave, "configurada": True, "ultimos4": None,
                        "updated_at": f["updated_at"]})
            continue
        try:
            val = descifrar(f["valor_cifrado"])
            ultimos4 = val[-4:] if len(val) >= 4 else "*" * len(val)
        except InvalidToken:
            ultimos4 = "????"
        out.append({"clave": clave, "configurada": True, "ultimos4": ultimos4,
                    "updated_at": f["updated_at"]})
    return out


def creds_de_slug(slug: str) -> dict[str, str]:
    """Secretos de la marca por slug, con conexión propia. {} si el módulo está
    apagado, la DB/tabla no existe (worker sin DB) o la marca no existe."""
    if not habilitado():
        return {}
    try:
        cx = db.connect()
    except sqlite3.Error:
        return {}
    try:
        fila = cx.execute("SELECT id FROM accounts WHERE slug=?", (slug,)).fetchone()
        if not fila:
            return {}
        return leer_todos(cx, int(fila[0]))
    except sqlite3.Error as e:  # tabla ausente en una DB vieja: no es fatal
        print(f"[secretos] no pude leer brand_secrets: {e}", file=sys.stderr)
        return {}
    finally:
        cx.close()


def version_marcas(cx: sqlite3.Connection) -> dict[int, str]:
    """{account_id: max(updated_at)} — huella barata para detectar cambios."""
    return {int(f["account_id"]): f["v"] for f in db.rows(
        cx, "SELECT account_id, MAX(updated_at) AS v FROM brand_secrets GROUP BY account_id")}


def actualizar_si_existe(slug: str, clave: str, valor: str) -> bool:
    """Actualiza secreto de cuenta por slug. False si disabled, no account, o no row para clave.
    Abre su propia conexión como creds_de_slug. Nunca lanza por errores sqlite (return False,
    print aviso a stderr)."""
    if not habilitado():
        return False
    try:
        cx = db.connect()
    except sqlite3.Error:
        return False
    try:
        fila = cx.execute("SELECT id FROM accounts WHERE slug=?", (slug,)).fetchone()
        if not fila:
            return False
        account_id = int(fila[0])
        # Verificar que ya existe una fila para esta clave
        existe = cx.execute(
            "SELECT 1 FROM brand_secrets WHERE account_id=? AND clave=?",
            (account_id, clave)).fetchone()
        if not existe:
            return False
        guardar(cx, account_id, clave, valor)
        return True
    except (sqlite3.Error, ValueError, KeyError) as e:
        print(f"[secretos] no pude actualizar {clave} de {slug}: {e}", file=sys.stderr)
        return False
    finally:
        cx.close()


def slugs_con_clave(clave: str) -> list[str]:
    """Slugs de cuentas que tienen row para clave. [] si disabled o DB error, ordenados por account_id."""
    if not habilitado():
        return []
    try:
        cx = db.connect()
    except sqlite3.Error:
        return []
    try:
        filas = cx.execute(
            "SELECT DISTINCT a.slug FROM accounts a "
            "JOIN brand_secrets s ON a.id = s.account_id WHERE s.clave = ? "
            "ORDER BY a.id",
            (clave,)).fetchall()
        return [f[0] for f in filas]
    except sqlite3.Error as e:
        print(f"[secretos] no pude listar slugs con {clave}: {e}", file=sys.stderr)
        return []
    finally:
        cx.close()
