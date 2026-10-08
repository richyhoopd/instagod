"""quitar_fondo y job asset.recorte. El modelo real solo corre con -m lento."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from src import assets, db, jobs
from src.assets import biblioteca, recorte
from src.jobs import handlers


def _png_con_alfa() -> bytes:
    im = Image.new("RGBA", (40, 30), (0, 0, 0, 0))
    for x in range(10, 20):
        for y in range(5, 25):
            im.putpixel((x, y), (255, 0, 0, 255))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _png(w=40, h=30) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), "blue").save(b, "PNG")
    return b.getvalue()


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(recorte, "_remover", lambda datos: _png_con_alfa())
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def _cuenta(cx, slug) -> int:
    return db.insert(cx, "accounts", slug=slug, ig_handle=f"@{slug}", nombre=slug, ciudad="GDL")


def test_quitar_fondo_recorta_al_contenido(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(recorte, "_remover", lambda datos: _png_con_alfa())
    origen = tmp_path / "o.png"
    origen.write_bytes(_png())
    destino = recorte.quitar_fondo(origen, tmp_path / "d" / "o-recorte.png")
    with Image.open(destino) as im:
        assert im.mode == "RGBA" and im.size == (10, 20)
    assert not list((tmp_path / "d").glob("*.part"))


def test_quitar_fondo_vacio(tmp_path, monkeypatch) -> None:
    vacio = io.BytesIO()
    Image.new("RGBA", (5, 5), (0, 0, 0, 0)).save(vacio, "PNG")
    monkeypatch.setattr(recorte, "_remover", lambda datos: vacio.getvalue())
    origen = tmp_path / "o.png"
    origen.write_bytes(_png())
    with pytest.raises(ValueError):
        recorte.quitar_fondo(origen, tmp_path / "x.png")


def test_job_recorte_guarda_y_actualiza_fila(cx) -> None:
    aid = _cuenta(cx, "m1")
    fila, _ = biblioteca.guardar_bytes(cx, aid, "m1", _png(), proveedor="subida")
    jid = jobs.crear(cx, "asset.recorte", aid, {"asset_id": fila["id"]}, creado_por=None)
    res = handlers.HANDLERS["asset.recorte"](cx, db.get(cx, "jobs", jid))
    esperado = fila["archivo"].rsplit(".", 1)[0] + "-recorte.png"
    assert res == {"asset_id": fila["id"], "recorte_archivo": esperado,
                   "src": f"assets/{esperado}"}
    assert db.get(cx, "brand_assets", fila["id"])["recorte_archivo"] == esperado
    assert biblioteca.ruta_de("m1", esperado).is_file()


def test_recorte_rechaza_asset_de_otra_marca(cx) -> None:
    a1, a2 = _cuenta(cx, "m1"), _cuenta(cx, "m2")
    ajeno, _ = biblioteca.guardar_bytes(cx, a2, "m2", _png(), proveedor="subida")
    jid = jobs.crear(cx, "asset.recorte", a1, {"asset_id": ajeno["id"]}, creado_por=None)
    with pytest.raises(ValueError):
        handlers.asset_recorte(cx, db.get(cx, "jobs", jid))
    assert db.get(cx, "brand_assets", ajeno["id"])["recorte_archivo"] is None
    assert not list((assets.BRANDS_DIR / "m1").glob("**/*-recorte.png"))


def test_opencv_sigue_cargando_haar() -> None:
    """rembg trae opencv-python-headless: el clasificador de caras v1 debe seguir vivo."""
    import cv2
    ruta = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    assert not cv2.CascadeClassifier(ruta).empty()


@pytest.mark.lento
def test_modelo_real_birefnet(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(recorte, "_remover", recorte._remover_real)
    origen = tmp_path / "o.png"
    im = Image.new("RGB", (256, 256), "white")
    for x in range(80, 176):
        for y in range(80, 176):
            im.putpixel((x, y), (200, 30, 30))
    im.save(origen)
    destino = recorte.quitar_fondo(origen, tmp_path / "r.png")
    with Image.open(destino) as r:
        assert r.mode == "RGBA" and r.size[0] < 256
