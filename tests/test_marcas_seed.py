"""Seeds de marca: gdlscene brandeado + pensión+ completo, idempotente."""
from __future__ import annotations

from src import db, marcas, marcas_seed


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_sembrar_crea_pensionmas_completo(tmp_path) -> None:
    cx = _cx(tmp_path)
    marcas_seed.sembrar(cx)
    m = marcas.cargar(cx, "pensionmas")
    assert m.fuentes == ["pinterest", "pexels"]
    assert m.formatos == ["libre", "listicle"]
    assert "pensionmas" in m.estilos
    assert m.estilos["pensionmas"]["chrome"]["handle"] == "@pensionmas"
    assert "estimad" in m.voz.lower()          # regla legal presente
    assert m.posting_slots == ["10:00", "18:00"]


def test_sembrar_brandea_gdlscene(tmp_path) -> None:
    cx = _cx(tmp_path)
    marcas_seed.sembrar(cx)
    m = marcas.cargar(cx, "gdlscene")
    assert "gdlscene_clasico" in m.estilos
    assert m.estilos["gdlscene_clasico"]["chrome"]["handle"] == "@gdlscene"
    assert m.fuentes == ["banco", "covers", "pexels"]


def test_sembrar_es_idempotente_y_no_pisa_manual(tmp_path) -> None:
    cx = _cx(tmp_path)
    marcas_seed.sembrar(cx)
    db.update(cx, "accounts", marcas.cargar(cx, "pensionmas").id,
              voz="VOZ EDITADA A MANO")
    marcas_seed.sembrar(cx)
    assert marcas.cargar(cx, "pensionmas").voz == "VOZ EDITADA A MANO"
    assert len([m for m in marcas.listar(cx, solo_activas=False)
                if m.slug == "pensionmas"]) == 1


def test_sembrar_crea_melaquecapital_completo(tmp_path) -> None:
    cx = _cx(tmp_path)
    marcas_seed.sembrar(cx)
    m = marcas.cargar(cx, "melaquecapital")
    assert m.ig_handle == "@melaquecapital"
    assert m.color_marca == "#223124"
    assert m.formatos == ["listicle", "libre"]
    assert m.fuentes == ["pexels", "pinterest"]
    p = m.estilos["melaquecapital"]
    assert p["chrome"]["handle"] == "@melaquecapital"
    assert p["caja"] == "olivo" and p["overlay"] == "olivo"
    assert p["roles"]["hook"]["font"] == "Marcellus"
    voz = m.voz.lower()
    assert "moneda" in voz and "ejido" in voz          # reglas de copy
    assert "sin gente" in voz or "personas reconocibles" in voz
