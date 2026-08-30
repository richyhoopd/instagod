"""Seeds de H1: bandas -> entidades, y HTML -> plantillas. Idempotentes."""
from __future__ import annotations

from src import db, entidades, plantillas
from src.plantillas import contrato as c
from src.seeds import entidades_gdlscene, plantillas_gdlscene


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_siembra_las_cuatro_plantillas(tmp_path) -> None:
    cx = _cx(tmp_path)
    r = plantillas_gdlscene.sembrar(cx, 1)
    assert r["creadas"] == 4
    slugs = {t["slug"] for t in plantillas.listar(cx, 1)}
    assert slugs == {"clasica", "verde", "onion", "anuncio"}


def test_las_sembradas_quedan_activas_y_con_origen_seed(tmp_path) -> None:
    cx = _cx(tmp_path)
    plantillas_gdlscene.sembrar(cx, 1)
    for t in plantillas.listar(cx, 1):
        assert t["estado"] == "activa"
        assert t["origen"] == "seed"
        assert t["version_actual"] == 1


def test_el_html_sembrado_pasa_su_propio_contrato(tmp_path) -> None:
    cx = _cx(tmp_path)
    plantillas_gdlscene.sembrar(cx, 1)
    for t in plantillas.listar(cx, 1):
        c.validar_html(t["html"], plantillas.contrato_de(t))


def test_el_html_ya_no_usa_los_nombres_viejos(tmp_path) -> None:
    cx = _cx(tmp_path)
    plantillas_gdlscene.sembrar(cx, 1)
    for t in plantillas.listar(cx, 1):
        for viejo in ("{{ caption }}", "{{ foto_url }}", "{{ badge_text }}",
                      "{{ foto_inset_url }}", "{{ caption_html }}", "{{ tag_text }}"):
            assert viejo not in t["html"], f"{t['slug']} conserva {viejo}"


def test_onion_usa_el_filtro_resaltar(tmp_path) -> None:
    cx = _cx(tmp_path)
    plantillas_gdlscene.sembrar(cx, 1)
    onion = plantillas.por_slug(cx, 1, "onion")
    assert "resaltar" in onion["html"]


def test_siembra_de_plantillas_es_idempotente(tmp_path) -> None:
    cx = _cx(tmp_path)
    plantillas_gdlscene.sembrar(cx, 1)
    r2 = plantillas_gdlscene.sembrar(cx, 1)
    assert r2["creadas"] == 0 and r2["existentes"] == 4
    assert len(plantillas.listar(cx, 1)) == 4


def test_siembra_una_entidad_por_banda(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "bands", nombre="Los Ejemplo", ig_handle="losejemplo",
              tipo="banda", account_id=1)
    db.insert(cx, "bands", nombre="Foro X", ig_handle="forox",
              tipo="foro", account_id=1)
    r = entidades_gdlscene.sembrar(cx, 1)
    assert r["creadas"] == 2
    assert {e["tipo"] for e in entidades.listar(cx, 1)} == {"banda", "foro"}


def test_siembra_es_idempotente(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "bands", nombre="Los Ejemplo", ig_handle="losejemplo",
              tipo="banda", account_id=1)
    entidades_gdlscene.sembrar(cx, 1)
    r2 = entidades_gdlscene.sembrar(cx, 1)
    assert r2["creadas"] == 0 and r2["existentes"] == 1
    assert len(entidades.listar(cx, 1, solo_activas=False)) == 1


def test_atributos_llevan_el_dato_musical(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Los Ejemplo", ig_handle="losejemplo",
                    tipo="banda", account_id=1, spotify_id="abc123",
                    genero_principal="punk")
    entidades_gdlscene.sembrar(cx, 1)
    ent = entidades.por_band_id(cx, bid)
    attrs = entidades.atributos_de(ent)
    assert attrs["spotify_id"] == "abc123"
    assert attrs["genero_principal"] == "punk"
    assert attrs["ig_handle"] == "losejemplo"


def test_backfill_liga_las_fotos(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Los Ejemplo", ig_handle="losejemplo",
                    tipo="banda", account_id=1)
    db.insert(cx, "photos", band_id=bid, path="/tmp/a.jpg", source_post_id="m1")
    db.insert(cx, "photos", band_id=bid, path="/tmp/b.jpg", source_post_id="m2")
    r = entidades_gdlscene.sembrar(cx, 1)
    ent = entidades.por_band_id(cx, bid)
    assert r["fotos_ligadas"] == 2
    ligadas = db.rows(cx, "SELECT count(*) c FROM photos WHERE entity_id = ?",
                      (ent["id"],))[0]["c"]
    assert ligadas == 2


def test_no_pierde_fotos_al_resembrar(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Los Ejemplo", ig_handle="losejemplo",
                    tipo="banda", account_id=1)
    db.insert(cx, "photos", band_id=bid, path="/tmp/a.jpg", source_post_id="m1")
    antes = db.rows(cx, "SELECT count(*) c FROM photos")[0]["c"]
    entidades_gdlscene.sembrar(cx, 1)
    entidades_gdlscene.sembrar(cx, 1)
    assert db.rows(cx, "SELECT count(*) c FROM photos")[0]["c"] == antes
