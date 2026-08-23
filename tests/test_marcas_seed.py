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
    assert m.fuentes == ["carpeta", "pexels", "pinterest"]
    p = m.estilos["melaquecapital"]
    assert p["chrome"]["handle"] == "@melaquecapital"
    assert p["caja"] == "olivo" and p["overlay"] == "olivo"
    assert p["roles"]["hook"]["font"] == "Marcellus"
    voz = m.voz.lower()
    assert "moneda" in voz and "ejido" in voz          # reglas de copy
    assert "sin gente" in voz or "personas reconocibles" in voz


def test_pensionmas_tiene_estilos_alternos(tmp_path) -> None:
    cx = _cx(tmp_path)
    marcas_seed.sembrar(cx)
    m = marcas.cargar(cx, "pensionmas")
    assert set(m.estilos) == {"pensionmas", "pension_postal", "pension_solido"}
    assert m.estilos["pension_postal"]["roles"]["cta"]["color"] == "oro"
    assert m.estilos["pension_solido"]["background_opacity"] >= 0.8


def test_sembrar_agrega_presets_nuevos_sin_pisar_los_editados(tmp_path) -> None:
    """DB viva: estilos_json ya poblado gana nuevas claves, las suyas intactas."""
    import json
    cx = _cx(tmp_path)
    marcas_seed.sembrar(cx)
    m = marcas.cargar(cx, "melaquecapital")
    editado = dict(m.estilos["melaquecapital"], background_opacity=0.77)
    db.update(cx, "accounts", m.id,
              estilos_json=json.dumps({"melaquecapital": editado}))
    marcas_seed.sembrar(cx)
    m2 = marcas.cargar(cx, "melaquecapital")
    assert m2.estilos["melaquecapital"]["background_opacity"] == 0.77  # no pisado
    assert "melaque_postal" in m2.estilos                              # agregado


def test_melaquecapital_tiene_estilos_alternos(tmp_path) -> None:
    cx = _cx(tmp_path)
    marcas_seed.sembrar(cx)
    m = marcas.cargar(cx, "melaquecapital")
    assert set(m.estilos) == {"melaquecapital", "melaque_postal", "melaque_solido"}
    postal = m.estilos["melaque_postal"]
    assert postal["roles"]["hook"]["text_style"] == "text"
    assert postal["roles"]["hook"]["text_align"] == "left"
    assert postal["roles"]["cta"]["color"] == "laton"
    assert m.estilos["melaque_solido"]["background_opacity"] >= 0.8
