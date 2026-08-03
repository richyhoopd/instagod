from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from src import banco, db


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def test_migracion_crea_personas_y_firmas(cx) -> None:
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"personas", "face_signatures"} <= tablas
    assert "persona_id" in {r["name"] for r in cx.execute("PRAGMA table_info(photos)")}
    # Sin registro en TABLES, db.insert las rechaza.
    assert "personas" in db.TABLES and "face_signatures" in db.TABLES
    assert "persona_id" in db.TABLES["photos"]


def test_migracion_es_idempotente(cx) -> None:
    db.init_db(cx)
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k")
    pid = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    assert db.get(cx, "personas", pid)["band_id"] == bid


def _hash(bits: str) -> np.ndarray:
    v = np.zeros(64, dtype=bool)
    for i, c in enumerate(bits):
        v[i] = c == "1"
    return v


def _vec(*componentes: float) -> np.ndarray:
    v = np.zeros(128, dtype=np.float32)
    v[:len(componentes)] = componentes
    return v / np.linalg.norm(v)


def _analizador_falso(mapa):
    """Devuelve un analizador que consulta `mapa` por nombre de archivo."""
    def analizar(path):
        return mapa[str(path).split("/")[-1]]
    return analizar


def test_procesar_banda_crea_personas_y_marca_banco(cx, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    for n in ("a.jpg", "b.jpg", "c.jpg"):
        db.insert(cx, "photos", band_id=bid, path=n, source_post_id=n[0])
    # a y b son la MISMA persona; c es otra.
    mapa = {
        "a.jpg": (_hash("1" * 64), 90.0, [((0, 0, 50, 50), 0.99, 0.25, _vec(1, 0.01))]),
        "b.jpg": (_hash("0" * 64), 80.0, [((0, 0, 50, 50), 0.98, 0.25, _vec(1, 0.02))]),
        "c.jpg": (_hash("0101" * 16), 70.0, [((0, 0, 50, 50), 0.97, 0.25, _vec(0, 1))]),
    }
    res = banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    assert res["personas"] == 2
    personas = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))
    assert len(personas) == 2
    assert all(p["etiqueta_auto"].startswith("persona ") for p in personas)
    firmas = db.rows(cx, "SELECT * FROM face_signatures")
    assert len(firmas) == 3
    assert all(f["persona_id"] is not None for f in firmas)
    # Con cupo por defecto (5/persona) las tres entran al banco.
    assert res["fotos_dentro"] == 3
    assert all(p["usable_meme"] == 1
               for p in db.rows(cx, "SELECT usable_meme FROM photos"))


def test_procesar_banda_dedup_saca_la_copia(cx, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    for n in ("a.jpg", "b.jpg"):
        db.insert(cx, "photos", band_id=bid, path=n, source_post_id=n[0])
    igual = _hash("1" * 64)
    mapa = {
        "a.jpg": (igual, 50.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0))]),
        "b.jpg": (igual, 90.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0))]),
    }
    res = banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))
    assert res["duplicadas"] == 1
    # La menos nítida queda fuera del banco pero NO se borra ni se marca descartada.
    fila_a = db.rows(cx, "SELECT * FROM photos WHERE path = 'a.jpg'")[0]
    assert fila_a["usable_meme"] == 0 and fila_a["descartada"] == 0


def test_procesar_banda_sin_caras_degrada(cx, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="Foro", ig_handle="f", tipo="foro")
    for i in range(6):
        db.insert(cx, "photos", band_id=bid, path=f"{i}.jpg", source_post_id=str(i))
    # Bloque de 8 bits en cero desplazado por foto: distancia de Hamming 16
    # entre cualquier par (> DEDUP_HAMMING_MAX=8), así ninguna se deduplica.
    mapa = {}
    for i in range(6):
        bits = "1" * (8 * i) + "0" * 8 + "1" * (64 - 8 * i - 8)
        mapa[f"{i}.jpg"] = (_hash(bits), float(i * 10), [])
    res = banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))
    assert res["personas"] == 0
    assert res["fotos_dentro"] == 4  # FOTOS_MINIMO_SIN_CARAS


def test_procesar_banda_es_idempotente(cx, tmp_path, monkeypatch) -> None:
    """Correrla dos veces no duplica personas ni firmas."""
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a")
    mapa = {"a.jpg": (_hash("1" * 64), 90.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0))])}
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))
    assert len(db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))) == 1
    assert len(db.rows(cx, "SELECT * FROM face_signatures")) == 1


def test_reprocesar_conserva_el_nombre_capturado_a_mano(cx, tmp_path, monkeypatch) -> None:
    """El batch NUNCA pisa lo manual: si nombraste una cara, sigue nombrada."""
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a")
    mapa = {"a.jpg": (_hash("1" * 64), 90.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0.01))])}
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    # Ricardo la nombra en la GUI.
    persona = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))[0]
    mid = db.insert(cx, "members", band_id=bid, nombre="Fercho", rol="baterista")
    db.update(cx, "personas", persona["id"], member_id=mid)

    # Entra una foto nueva de la MISMA persona y se reprocesa.
    db.insert(cx, "photos", band_id=bid, path="b.jpg", source_post_id="b")
    mapa["b.jpg"] = (_hash("0" * 64), 80.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0.02))])
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    personas = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))
    assert len(personas) == 1
    assert personas[0]["member_id"] == mid  # el nombre sobrevivió al reproceso


def test_nombre_sobrevive_si_su_foto_se_vuelve_duplicada_no_representante(
        cx, tmp_path, monkeypatch) -> None:
    """El centroide vive en `personas.centroide`, no solo en las firmas: si la
    foto de un nombrado deja de ser la representante de su grupo de dedup (y
    su cara ya no entra a la agrupación), el member_id no debe perderse."""
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a")
    hash_a = _hash("1" * 64)
    mapa = {"a.jpg": (hash_a, 50.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0))])}
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    persona = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))[0]
    mid = db.insert(cx, "members", band_id=bid, nombre="Fercho", rol="baterista")
    db.update(cx, "personas", persona["id"], member_id=mid)

    # b.jpg: mismo hash que a.jpg (dedup los funde) pero MÁS nítida y de OTRA
    # persona → se vuelve la representante; la cara de "a" queda fuera del
    # todo y ningún grupo nuevo calza con el centroide nombrado.
    db.insert(cx, "photos", band_id=bid, path="b.jpg", source_post_id="b")
    mapa["b.jpg"] = (hash_a, 90.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(0, 1))])
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    personas = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))
    assert any(p["member_id"] == mid for p in personas)


def test_nombre_sobrevive_si_su_unica_foto_se_descarta(cx, tmp_path, monkeypatch) -> None:
    """Marcar `descartada` la única foto de un nombrado saca a la banda del
    early-return (sin fotos activas); el member_id debe sobrevivir igual."""
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    pid_foto = db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a")
    mapa = {"a.jpg": (_hash("1" * 64), 90.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0))])}
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    persona = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))[0]
    mid = db.insert(cx, "members", band_id=bid, nombre="Fercho", rol="baterista")
    db.update(cx, "personas", persona["id"], member_id=mid)

    db.update(cx, "photos", pid_foto, descartada=1)
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    personas = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))
    assert any(p["member_id"] == mid for p in personas)


def test_member_no_se_asigna_a_dos_personas_si_sus_caras_se_parten(
        cx, tmp_path, monkeypatch) -> None:
    """Asignación 1-a-1: si las caras de un nombrado se agrupan en DOS grupos
    nuevos (ambos parecidos al centroide), el member_id se queda en solo uno."""
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    pid_a = db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a")
    mapa = {"a.jpg": (_hash("1" * 64), 90.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0))])}
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    persona = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))[0]
    mid = db.insert(cx, "members", band_id=bid, nombre="Fercho", rol="baterista")
    db.update(cx, "personas", persona["id"], member_id=mid)

    # "a" sale de juego (descartada). Llegan b y c: cada una a 40° del
    # centroide nombrado (cos ≈ 0.766 ≥ 0.45, ambas calzarían) pero a 80°
    # entre sí (cos ≈ 0.174 < 0.45: NO se agrupan entre ellas).
    db.update(cx, "photos", pid_a, descartada=1)
    db.insert(cx, "photos", band_id=bid, path="b.jpg", source_post_id="b")
    db.insert(cx, "photos", band_id=bid, path="c.jpg", source_post_id="c")
    ang = math.radians(40)
    mapa["b.jpg"] = (_hash("0011" * 16), 80.0,
                     [((0, 0, 50, 50), 0.9, 0.2, _vec(math.cos(ang), math.sin(ang)))])
    mapa["c.jpg"] = (_hash("1100" * 16), 70.0,
                     [((0, 0, 50, 50), 0.9, 0.2, _vec(math.cos(ang), -math.sin(ang)))])
    res = banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    assert res["personas"] == 2  # b y c NO se fusionaron entre sí
    personas = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))
    con_nombre = [p for p in personas if p["member_id"] == mid]
    assert len(con_nombre) == 1  # el nombre no se duplicó


def test_foto_descartada_con_persona_id_previo_no_queda_colgando(
        cx, tmp_path, monkeypatch) -> None:
    """`photos.persona_id` no tiene FK (se agregó por ALTER): si la foto se
    descarta y su persona se recrea con otro id, el viejo no debe sobrevivir
    apuntando a nada (o peor, a la persona de otra banda)."""
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    for n in ("a.jpg", "b.jpg"):
        db.insert(cx, "photos", band_id=bid, path=n, source_post_id=n[0])
    mapa = {
        "a.jpg": (_hash("1" * 64), 90.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0))]),
        "b.jpg": (_hash("0101" * 16), 80.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(0, 1))]),
    }
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))
    fila_a = db.rows(cx, "SELECT * FROM photos WHERE path = 'a.jpg'")[0]
    assert fila_a["persona_id"] is not None

    db.update(cx, "photos", fila_a["id"], descartada=1)
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    fila_a2 = db.rows(cx, "SELECT * FROM photos WHERE path = 'a.jpg'")[0]
    ids_persona_banda = {p["id"] for p in
                         db.rows(cx, "SELECT id FROM personas WHERE band_id = ?", (bid,))}
    assert fila_a2["persona_id"] is None or fila_a2["persona_id"] in ids_persona_banda


def test_banda_sin_fotos_activas_no_deja_firmas_huerfanas(cx, tmp_path, monkeypatch) -> None:
    """Sin fotos activas (early-return), el limpiado corre igual: cero firmas
    huérfanas en la tabla y el nombre capturado a mano sigue existiendo."""
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    pid_foto = db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a")
    mapa = {"a.jpg": (_hash("1" * 64), 90.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0))])}
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))
    persona = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))[0]
    mid = db.insert(cx, "members", band_id=bid, nombre="Fercho", rol="baterista")
    db.update(cx, "personas", persona["id"], member_id=mid)
    assert len(db.rows(cx, "SELECT * FROM face_signatures")) == 1

    db.update(cx, "photos", pid_foto, descartada=1)
    res = banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    assert res == {"personas": 0, "fotos_dentro": 0, "fotos_fuera": 0, "duplicadas": 0}
    assert len(db.rows(cx, "SELECT * FROM face_signatures")) == 0
    personas = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))
    assert len(personas) == 1 and personas[0]["member_id"] == mid
