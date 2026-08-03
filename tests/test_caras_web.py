from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db


@pytest.fixture()
def cliente(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import importlib

    import config
    importlib.reload(config)
    from web import app as app_mod
    importlib.reload(app_mod)
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield TestClient(app_mod.app), conn
    conn.close()


def test_vista_caras_lista_personas(cliente) -> None:
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    pid = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    fid = db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a",
                    persona_id=pid, usable_meme=1)
    db.insert(cx, "face_signatures", photo_id=fid, persona_id=pid,
              bbox="[0,0,10,10]", det_score=0.9, embedding=b"\x00" * 512)
    r = cli.get(f"/banda/{bid}/caras")
    assert r.status_code == 200
    assert "persona A" in r.text


def test_una_sola_persona_no_muestra_el_form_de_fusionar(cliente) -> None:
    """Con una sola persona el <select name="otra_id"> quedaba VACÍO: el POST no
    mandaba el campo y el servidor respondía 422 sin ningún feedback."""
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    r = cli.get(f"/banda/{bid}/caras")
    assert r.status_code == 200
    assert "/fusionar" not in r.text
    assert 'name="otra_id"' not in r.text


def test_dos_personas_si_muestran_el_form_de_fusionar(cliente) -> None:
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona B")
    r = cli.get(f"/banda/{bid}/caras")
    assert "/fusionar" in r.text and 'name="otra_id"' in r.text


def test_vista_caras_da_feedback_visible(cliente) -> None:
    """Los tres formularios usan hx-swap="none": sin el zócalo de mensajes y el
    script de estado, el clic no produce NINGÚN cambio visible ni en error."""
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    r = cli.get(f"/banda/{bid}/caras")
    assert 'id="caras-msg"' in r.text
    assert "htmx:afterRequest" in r.text and "htmx:beforeRequest" in r.text


def test_nombrar_persona_crea_member(cliente) -> None:
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    pid = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    r = cli.post(f"/personas/{pid}/nombrar",
                 data={"nombre": "Fercho", "rol": "baterista"})
    assert r.status_code in (200, 303)
    miembros = db.rows(cx, "SELECT * FROM members WHERE band_id = ?", (bid,))
    assert len(miembros) == 1
    assert miembros[0]["nombre"] == "Fercho" and miembros[0]["rol"] == "baterista"
    assert db.get(cx, "personas", pid)["member_id"] == miembros[0]["id"]


def test_nombrar_dos_veces_actualiza_sin_duplicar(cliente) -> None:
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    pid = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    cli.post(f"/personas/{pid}/nombrar", data={"nombre": "Fercho", "rol": "bat"})
    cli.post(f"/personas/{pid}/nombrar", data={"nombre": "Fernando", "rol": "batería"})
    miembros = db.rows(cx, "SELECT * FROM members WHERE band_id = ?", (bid,))
    assert len(miembros) == 1 and miembros[0]["nombre"] == "Fernando"


def test_fusionar_personas(cliente) -> None:
    """Dos grupos que son la misma persona: se fusionan sin perder firmas."""
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    p1 = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    p2 = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona B")
    f1 = db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a",
                   persona_id=p2)
    db.insert(cx, "face_signatures", photo_id=f1, persona_id=p2,
              bbox="[0,0,1,1]", det_score=0.9, embedding=b"\x00" * 512)
    r = cli.post(f"/personas/{p1}/fusionar", data={"otra_id": str(p2)})
    assert r.status_code in (200, 303)
    assert db.get(cx, "personas", p2) is None
    assert db.rows(cx, "SELECT persona_id FROM face_signatures")[0]["persona_id"] == p1
    assert db.get(cx, "photos", f1)["persona_id"] == p1


def test_fusionar_persona_consigo_misma_falla(cliente) -> None:
    """Guard: otra_id == persona_id no debe borrar la persona activa (bug de la Task 6)."""
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    pid = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    fid = db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a",
                    persona_id=pid)
    db.insert(cx, "face_signatures", photo_id=fid, persona_id=pid,
              bbox="[0,0,1,1]", det_score=0.9, embedding=b"\x00" * 512)
    r = cli.post(f"/personas/{pid}/fusionar", data={"otra_id": str(pid)})
    assert r.status_code == 400
    assert db.get(cx, "personas", pid) is not None
    assert db.rows(cx, "SELECT * FROM face_signatures WHERE persona_id = ?", (pid,))
    assert db.get(cx, "photos", fid)["persona_id"] == pid


def test_fusionar_bandas_distintas_falla(cliente) -> None:
    """Guard: no se fusionan personas de bandas distintas (la API no debe permitirlo)."""
    cli, cx = cliente
    b1 = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    b2 = db.insert(cx, "bands", nombre="Otra Banda", ig_handle="otra_banda")
    p1 = db.insert(cx, "personas", band_id=b1, etiqueta_auto="persona A")
    p2 = db.insert(cx, "personas", band_id=b2, etiqueta_auto="persona B")
    r = cli.post(f"/personas/{p1}/fusionar", data={"otra_id": str(p2)})
    assert r.status_code == 400
    assert db.get(cx, "personas", p1) is not None
    assert db.get(cx, "personas", p2) is not None


def test_descartar_persona_saca_sus_fotos_del_banco(cliente) -> None:
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    pid = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    fid = db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a",
                    persona_id=pid, usable_meme=1)
    r = cli.post(f"/personas/{pid}/descartar")
    assert r.status_code in (200, 303)
    assert db.get(cx, "photos", fid)["usable_meme"] == 0
    assert db.get(cx, "personas", pid) is None
