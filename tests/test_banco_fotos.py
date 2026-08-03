from __future__ import annotations

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
