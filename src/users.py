"""Usuarios del portal: alta, membresías por marca, magic links y sesiones.

Tokens (magic link, sesión) se generan con `secrets.token_urlsafe(32)` y se
guardan hasheados (sha256): una fuga de la DB no regala sesiones vivas.
Fechas ISO en UTC ("YYYY-MM-DD HH:MM:SS"), comparables como texto.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from src import db

ROLES = ("manager", "editor")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LinkInvalido(ValueError):
    """Magic link inexistente, usado, expirado o de usuario inactivo."""


class CredencialesInvalidas(ValueError):
    """Email inexistente, contraseña incorrecta, sin contraseña o usuario inactivo."""


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _ahora(ahora: datetime | None) -> datetime:
    return ahora or datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _norm_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not _EMAIL_RE.match(e):
        raise ValueError(f"Email inválido: {email!r}")
    return e


# ---------- usuarios ----------

def crear_usuario(cx: sqlite3.Connection, email: str, nombre: str | None = None,
                  *, is_admin: bool = False) -> int:
    e = _norm_email(email)
    if por_email(cx, e):
        raise ValueError(f"Ya existe un usuario con email {e}")
    return db.insert(cx, "users", email=e, nombre=(nombre or "").strip() or None,
                     is_admin=1 if is_admin else 0)


def por_email(cx: sqlite3.Connection, email: str) -> dict | None:
    r = db.rows(cx, "SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),))
    return r[0] if r else None


def por_id(cx: sqlite3.Connection, uid: int) -> dict | None:
    return db.get(cx, "users", uid)


def listar(cx: sqlite3.Connection) -> list[dict]:
    out = []
    for u in db.rows(cx, "SELECT * FROM users ORDER BY id"):
        u["marcas"] = marcas_de(cx, u["id"])
        out.append(u)
    return out


# ---------- membresías ----------

def asignar_marca(cx: sqlite3.Connection, user_id: int, account_id: int, rol: str) -> None:
    if rol not in ROLES:
        raise ValueError(f"Rol inválido: {rol!r} (válidos: {', '.join(ROLES)})")
    cx.execute("INSERT INTO brand_members(user_id, account_id, rol) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, account_id) DO UPDATE SET rol = excluded.rol",
               (user_id, account_id, rol))
    cx.commit()


def quitar_marca(cx: sqlite3.Connection, user_id: int, account_id: int) -> None:
    cx.execute("DELETE FROM brand_members WHERE user_id=? AND account_id=?",
               (user_id, account_id))
    cx.commit()


def marcas_de(cx: sqlite3.Connection, user_id: int) -> list[dict]:
    return db.rows(cx, """
        SELECT a.id AS account_id, a.slug, a.nombre, a.ig_handle, a.color_marca,
               a.activa, m.rol
          FROM brand_members m JOIN accounts a ON a.id = m.account_id
         WHERE m.user_id = ? ORDER BY a.id""", (user_id,))


def rol_en(cx: sqlite3.Connection, user: dict, account_id: int) -> str | None:
    """'admin' para admins globales; si no, el rol de la membresía o None."""
    if user.get("is_admin"):
        return "admin"
    r = cx.execute("SELECT rol FROM brand_members WHERE user_id=? AND account_id=?",
                   (user["id"], account_id)).fetchone()
    return r[0] if r else None


# ---------- contraseñas ----------

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}   # parámetros recomendados para login interactivo
PASSWORD_MIN = 8


def _hash_password(password: str, salt: bytes) -> str:
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${h.hex()}"


def set_password(cx: sqlite3.Connection, user_id: int, password: str) -> None:
    if len(password) < PASSWORD_MIN:
        raise ValueError(f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres")
    db.update(cx, "users", user_id, password_hash=_hash_password(password, secrets.token_bytes(16)))


def verificar_password(cx: sqlite3.Connection, email: str, password: str) -> dict:
    """Usuario si las credenciales son válidas; CredencialesInvalidas si no."""
    u = por_email(cx, email)
    guardado = (u or {}).get("password_hash") or ""
    try:
        _algo, salt_hex, _ = guardado.split("$")
    except ValueError:
        salt_hex = "00" * 16   # hash igual de caro aunque no haya contraseña: sin oráculo de timing
    calculado = _hash_password(password, bytes.fromhex(salt_hex))
    if not (u and u["activo"] and guardado and secrets.compare_digest(calculado, guardado)):
        raise CredencialesInvalidas("Correo o contraseña incorrectos")
    return u


# ---------- magic links ----------

def crear_magic_link(cx: sqlite3.Connection, user_id: int, *, ttl_min: int = 15,
                     ahora: datetime | None = None) -> str:
    tok = secrets.token_urlsafe(32)
    db.insert(cx, "magic_links", token_hash=hash_token(tok), user_id=user_id,
              expira=_fmt(_ahora(ahora) + timedelta(minutes=ttl_min)))
    return tok


def consumir_magic_link(cx: sqlite3.Connection, token: str, *,
                        ahora: datetime | None = None) -> int:
    """Marca el link como usado y devuelve el user_id. LinkInvalido si no aplica."""
    now = _fmt(_ahora(ahora))
    fila = cx.execute("""
        SELECT l.token_hash, l.user_id, l.expira, l.usado_at, u.activo
          FROM magic_links l JOIN users u ON u.id = l.user_id
         WHERE l.token_hash = ?""", (hash_token(token),)).fetchone()
    if not fila or fila["usado_at"] or fila["expira"] < now or not fila["activo"]:
        raise LinkInvalido("Link inválido, usado o expirado")
    cx.execute("UPDATE magic_links SET usado_at=? WHERE token_hash=?", (now, fila["token_hash"]))
    cx.execute("UPDATE users SET last_login=? WHERE id=?", (now, fila["user_id"]))
    cx.commit()
    return int(fila["user_id"])


# ---------- sesiones ----------

def crear_sesion(cx: sqlite3.Connection, user_id: int, *, dias: int = 30,
                 ua: str | None = None, ahora: datetime | None = None) -> str:
    tok = secrets.token_urlsafe(32)
    now = _fmt(_ahora(ahora))
    db.insert(cx, "sessions", token_hash=hash_token(tok), user_id=user_id,
              expira=_fmt(_ahora(ahora) + timedelta(days=dias)), ua=(ua or "")[:200] or None)
    cx.execute("UPDATE users SET last_login=? WHERE id=?", (now, user_id))
    cx.commit()
    return tok


def usuario_de_sesion(cx: sqlite3.Connection, token: str, *,
                      ahora: datetime | None = None) -> dict | None:
    if not token:
        return None
    r = db.rows(cx, """
        SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
         WHERE s.token_hash = ? AND s.expira > ? AND u.activo = 1""",
                (hash_token(token), _fmt(_ahora(ahora))))
    return r[0] if r else None


def cerrar_sesion(cx: sqlite3.Connection, token: str) -> None:
    cx.execute("DELETE FROM sessions WHERE token_hash=?", (hash_token(token),))
    cx.commit()


def cerrar_sesiones_de(cx: sqlite3.Connection, user_id: int) -> int:
    cur = cx.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    cx.commit()
    return cur.rowcount
