"""Usuarios del portal: alta, roles por marca, magic links y sesiones."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src import db, users


@pytest.fixture()
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    db.insert(c, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    yield c
    c.close()


T0 = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def test_crear_usuario_normaliza_email_y_rechaza_duplicado(cx) -> None:
    uid = users.crear_usuario(cx, "  Ana@X.com ", "Ana")
    assert users.por_email(cx, "ana@x.com")["id"] == uid
    with pytest.raises(ValueError):
        users.crear_usuario(cx, "ANA@x.com")
    with pytest.raises(ValueError):
        users.crear_usuario(cx, "no-es-email")


def test_roles_por_marca(cx) -> None:
    uid = users.crear_usuario(cx, "a@x.com")
    admin = users.crear_usuario(cx, "r@x.com", is_admin=True)
    users.asignar_marca(cx, uid, 2, "editor")
    assert users.rol_en(cx, users.por_id(cx, uid), 2) == "editor"
    assert users.rol_en(cx, users.por_id(cx, uid), 1) is None
    users.asignar_marca(cx, uid, 2, "manager")          # upsert
    assert users.marcas_de(cx, uid) == [{
        "account_id": 2, "slug": "pensionmas", "nombre": "P", "ig_handle": "@p",
        "color_marca": "#1b5e3f", "activa": 1, "rol": "manager"}]
    assert users.rol_en(cx, users.por_id(cx, admin), 2) == "admin"
    with pytest.raises(ValueError):
        users.asignar_marca(cx, uid, 2, "dios")
    users.quitar_marca(cx, uid, 2)
    assert users.marcas_de(cx, uid) == []


def test_magic_link_un_uso_y_expira(cx) -> None:
    uid = users.crear_usuario(cx, "a@x.com")
    tok = users.crear_magic_link(cx, uid, ahora=T0)
    assert len(tok) >= 32
    assert cx.execute("SELECT token_hash FROM magic_links").fetchone()[0] != tok
    assert users.consumir_magic_link(cx, tok, ahora=T0 + timedelta(minutes=5)) == uid
    with pytest.raises(users.LinkInvalido):
        users.consumir_magic_link(cx, tok, ahora=T0 + timedelta(minutes=6))  # ya usado
    tok2 = users.crear_magic_link(cx, uid, ahora=T0)
    with pytest.raises(users.LinkInvalido):
        users.consumir_magic_link(cx, tok2, ahora=T0 + timedelta(minutes=16))  # expiró
    with pytest.raises(users.LinkInvalido):
        users.consumir_magic_link(cx, "inventado", ahora=T0)


def test_magic_link_usuario_inactivo(cx) -> None:
    uid = users.crear_usuario(cx, "a@x.com")
    tok = users.crear_magic_link(cx, uid, ahora=T0)
    db.update(cx, "users", uid, activo=0)
    with pytest.raises(users.LinkInvalido):
        users.consumir_magic_link(cx, tok, ahora=T0)


def test_sesiones(cx) -> None:
    uid = users.crear_usuario(cx, "a@x.com")
    s = users.crear_sesion(cx, uid, dias=30, ua="pytest", ahora=T0)
    u = users.usuario_de_sesion(cx, s, ahora=T0 + timedelta(days=1))
    assert u["id"] == uid and u["email"] == "a@x.com"
    assert users.usuario_de_sesion(cx, s, ahora=T0 + timedelta(days=31)) is None
    assert users.usuario_de_sesion(cx, "otra", ahora=T0) is None
    s2 = users.crear_sesion(cx, uid, ahora=T0)
    users.cerrar_sesion(cx, s2)
    assert users.usuario_de_sesion(cx, s2, ahora=T0) is None
    assert users.cerrar_sesiones_de(cx, uid) == 1
    assert users.usuario_de_sesion(cx, s, ahora=T0) is None
    assert users.por_id(cx, uid)["last_login"] is not None
