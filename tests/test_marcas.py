"""Perfil de marca: carga, defaults, merges y checklist de credenciales."""
from __future__ import annotations

import json

import pytest

import config
from src import db, marcas


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _alta_pensionmas(cx, **extra):
    campos = dict(slug="pensionmas", ig_handle="@pensionmas", nombre="Pensión+",
                  ciudad="CDMX", voz="Reglas: montos estimados.",
                  fuentes_imagen=json.dumps(["pinterest", "pexels"]),
                  formatos=json.dumps(["listicle", "libre"]),
                  estilos_json=json.dumps({"pensionmas": {"texto": "blanco"}}),
                  posting_slots="10:00,18:00")
    campos.update(extra)
    return db.insert(cx, "accounts", **campos)


def test_cargar_marca_completa(tmp_path) -> None:
    cx = _cx(tmp_path)
    _alta_pensionmas(cx)
    m = marcas.cargar(cx, "pensionmas")
    assert m.slug == "pensionmas"
    assert m.fuentes == ["pinterest", "pexels"]
    assert m.formatos == ["listicle", "libre"]
    assert m.estilos == {"pensionmas": {"texto": "blanco"}}
    assert m.posting_slots == ["10:00", "18:00"]
    assert m.voz == "Reglas: montos estimados."


def test_cargar_defaults_sin_json(tmp_path) -> None:
    """gdlscene (seed de Fase A) no tiene columnas nuevas pobladas → defaults."""
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    assert m.fuentes == ["pexels"]
    assert m.formatos == marcas._formatos_default()
    assert m.estilos == {}
    assert m.posting_slots is None
    assert m.voz == ""


def test_cargar_inexistente_lanza(tmp_path) -> None:
    cx = _cx(tmp_path)
    with pytest.raises(ValueError):
        marcas.cargar(cx, "noexiste")


def test_json_malformado_cae_a_default(tmp_path) -> None:
    cx = _cx(tmp_path)
    _alta_pensionmas(cx, fuentes_imagen="esto no es json", formatos="[1,")
    m = marcas.cargar(cx, "pensionmas")
    assert m.fuentes == ["pexels"]
    assert m.formatos == marcas._formatos_default()


def test_cargar_por_id_y_listar(tmp_path) -> None:
    cx = _cx(tmp_path)
    mid = _alta_pensionmas(cx)
    assert marcas.cargar_por_id(cx, mid).slug == "pensionmas"
    slugs = [m.slug for m in marcas.listar(cx)]
    assert "gdlscene" in slugs and "pensionmas" in slugs


def test_listar_excluye_inactivas(tmp_path) -> None:
    cx = _cx(tmp_path)
    _alta_pensionmas(cx, activa=0)
    assert "pensionmas" not in [m.slug for m in marcas.listar(cx)]
    assert "pensionmas" in [m.slug for m in marcas.listar(cx, solo_activas=False)]


def test_estilos_de_hace_merge_con_prioridad_marca(tmp_path) -> None:
    cx = _cx(tmp_path)
    _alta_pensionmas(cx, estilos_json=json.dumps(
        {"tiktok_bold": {"texto": "negro"}, "pensionmas": {"texto": "blanco"}}))
    m = marcas.cargar(cx, "pensionmas")
    fusion = marcas.estilos_de(m)
    assert fusion["tiktok_bold"] == {"texto": "negro"}       # marca pisa global
    assert fusion["pensionmas"] == {"texto": "blanco"}       # propio presente
    assert "editorial" in fusion                             # global sobrevive


def test_slots_de(tmp_path) -> None:
    cx = _cx(tmp_path)
    _alta_pensionmas(cx)
    assert marcas.slots_de(marcas.cargar(cx, "pensionmas")) == ["10:00", "18:00"]
    assert marcas.slots_de(marcas.cargar(cx, "gdlscene")) == config.POSTING_SLOTS


def test_marca_nueva_no_hereda_creds_de_gdlscene(monkeypatch) -> None:
    """REGLA DE ORO: sin sufijo __PENSIONMAS, las creds son None (no fallback)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-gdl")
    monkeypatch.setenv("SHEET_ID", "sheet-gdl")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN__PENSIONMAS", raising=False)
    creds = config.account_creds("pensionmas")
    assert creds["TELEGRAM_BOT_TOKEN"] is None
    assert creds["SHEET_ID"] is None
    # gdlscene SÍ cae al global:
    assert config.account_creds("gdlscene")["TELEGRAM_BOT_TOKEN"] == "token-gdl"


def test_creds_faltantes(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN__PENSIONMAS", "t")
    for var in ("TELEGRAM_CHAT_ID__PENSIONMAS", "IG_USER_ID__PENSIONMAS",
                "IG_ACCESS_TOKEN__PENSIONMAS", "SHEET_ID__PENSIONMAS"):
        monkeypatch.delenv(var, raising=False)
    faltan = marcas.creds_faltantes("pensionmas")
    assert "TELEGRAM_BOT_TOKEN__PENSIONMAS" not in faltan
    assert "SHEET_ID__PENSIONMAS" in faltan and "IG_ACCESS_TOKEN__PENSIONMAS" in faltan
