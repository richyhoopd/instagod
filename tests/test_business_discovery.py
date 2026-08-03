"""Tests de Business Discovery (API oficial de Meta) — sin red.

El HTTP de Graph se mockea vía `business_discovery._get`; las descargas del CDN
se inyectan con `_descargador`. La DB vive en tmp_path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src import business_discovery as bd
from src import db


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def _mock_get(monkeypatch, payload):
    monkeypatch.setattr(bd, "_get", lambda url, params: _Resp(payload))


def _perfil(handle="kabala_oficial", medias=None):
    return {"business_discovery": {
        "id": "17841400000000000", "username": handle, "name": "Kabala",
        "biography": " punk gdl ", "website": "https://kabala.mx",
        "followers_count": 1234, "media_count": 90,
        "media": {"data": medias or []},
    }}


# ---------- clasificación de errores (pura) ----------

def test_sin_error_devuelve_none() -> None:
    assert bd.clasificar_error({"data": []}) is None


@pytest.mark.parametrize("msg,code,esperado", [
    ("(#110) The user is not a Business or Creator account", 110, bd.NoEsBusiness),
    ("Application request limit reached", 4, bd.GraphRateLimited),
    ("(#17) User request limit reached", 17, bd.GraphRateLimited),
    ("(#200) Requires instagram_basic permission", 200, bd.BusinessDiscoveryNoDisponible),
    ("Invalid user id", 110, LookupError),
    ("Algo raro", 999, RuntimeError),
])
def test_clasificar_error(msg, code, esperado) -> None:
    exc = bd.clasificar_error({"error": {"message": msg, "code": code}})
    assert isinstance(exc, esperado)


def test_cuota_gana_sobre_business() -> None:
    """Un 'rate limit' que además mencione business se trata como cuota, no como personal."""
    exc = bd.clasificar_error(
        {"error": {"message": "Application request limit reached for business account", "code": 4}})
    assert isinstance(exc, bd.GraphRateLimited)


# ---------- parseo (puro) ----------

@pytest.mark.parametrize("link,esperado", [
    ("https://www.instagram.com/p/DKxYz-1/", "DKxYz-1"),
    ("https://www.instagram.com/reel/ABC123/?igsh=xx", "ABC123"),
    ("https://www.instagram.com/tv/QQQ/", "QQQ"),
    (None, None),
    ("https://www.instagram.com/kabala_oficial/", None),
])
def test_shortcode_de_permalink(link, esperado) -> None:
    assert bd.shortcode_de_permalink(link) == esperado


def test_urls_imagen_simple() -> None:
    assert bd.urls_de_media({"media_type": "IMAGE", "media_url": "u"}) == [(0, "u")]


def test_urls_video_se_ignora() -> None:
    assert bd.urls_de_media({"media_type": "VIDEO", "media_url": "u"}) == []


def test_urls_carrusel_solo_imagenes() -> None:
    media = {"media_type": "CAROUSEL_ALBUM", "children": {"data": [
        {"media_type": "IMAGE", "media_url": "a"},
        {"media_type": "VIDEO", "media_url": "b"},
        {"media_type": "IMAGE", "media_url": "c"},
    ]}}
    # El índice es la posición ORIGINAL en el carrusel (los videos dejan hueco),
    # igual que ingest_ig._image_urls → el mismo post baja con el mismo nombre
    # de archivo por cualquiera de los dos caminos.
    assert bd.urls_de_media(media) == [(0, "a"), (2, "c")]


# ---------- resolución del ig-user-id ----------

def test_ig_user_id_sin_vinculo_explica(monkeypatch) -> None:
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", None)
    monkeypatch.setattr(bd.config, "FB_PAGE_ID", "123")
    monkeypatch.setattr(bd.config, "FB_PAGE_ACCESS_TOKEN", "tok")
    _mock_get(monkeypatch, {"id": "123"})  # sin instagram_business_account
    with pytest.raises(bd.BusinessDiscoveryNoDisponible, match="instagram_basic"):
        bd.ig_user_id()


def test_ig_user_id_cacheado_no_llama(monkeypatch) -> None:
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", "999")

    def _boom(url, params):
        raise AssertionError("no debió llamar a Graph")

    monkeypatch.setattr(bd, "_get", _boom)
    assert bd.ig_user_id() == "999"


# ---------- registro de banda ----------

def test_registrar_banda_alta_como_candidata(cx, monkeypatch) -> None:
    bid = bd.registrar_banda(cx, _perfil()["business_discovery"])
    fila = db.get(cx, "bands", bid)
    assert fila["activa"] == 0 and "candidata" in fila["notas"]
    assert fila["followers_ig"] == 1234
    assert fila["bio"] == "punk gdl"  # trimmed
    assert fila["ig_user_id"] == "17841400000000000"


def test_registrar_banda_activar(cx) -> None:
    bid = bd.registrar_banda(cx, _perfil()["business_discovery"], activar=True)
    assert db.get(cx, "bands", bid)["activa"] == 1


def test_registrar_no_pisa_curacion(cx) -> None:
    """Una banda ya curada (activa + prioridad) no debe degradarse al refrescarla."""
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial",
                    activa=1, prioridad=1, tipo="banda")
    mismo = bd.registrar_banda(cx, _perfil()["business_discovery"])
    fila = db.get(cx, "bands", mismo)
    assert mismo == bid
    assert fila["activa"] == 1 and fila["prioridad"] == 1 and fila["tipo"] == "banda"
    assert fila["followers_ig"] == 1234  # los datos sí se refrescan


# ---------- guardado de fotos ----------

def _media(shortcode="ABC", tipo="IMAGE", **extra):
    return {"id": "1", "media_type": tipo, "media_url": "https://cdn/x.jpg",
            "permalink": f"https://www.instagram.com/p/{shortcode}/",
            "caption": "hola", "timestamp": "2026-07-18T16:02:21+0000",
            "like_count": 10, "comments_count": 2, **extra}


def test_guardar_media_inserta_y_baja(cx, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bd.config, "resolve_photos_dir", lambda: tmp_path)
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    bajados = []

    def _fake(url, dest):
        bajados.append(url)
        dest.write_bytes(b"jpg")
        return True

    bid = db.insert(cx, "bands", nombre="K", ig_handle="k")
    filas = bd.guardar_media(cx, bid, "k", [_media()], _descargador=_fake)
    assert len(filas) == 1 and bajados == ["https://cdn/x.jpg"]
    foto = db.rows(cx, "SELECT * FROM photos WHERE band_id = ?", (bid,))[0]
    assert foto["source_post_id"] == "ABC"
    assert foto["caption_original"] == "hola"
    assert foto["fecha"].startswith("2026-07-18")


def test_path_relativo_a_base_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    assert bd._path_guardable(tmp_path / "data" / "photos" / "a.jpg") == "data/photos/a.jpg"


def test_path_fuera_de_base_dir_no_truena(monkeypatch, tmp_path) -> None:
    """PHOTOS_DIR apuntado afuera del repo → ruta absoluta, no ValueError a media descarga."""
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path / "repo")
    fuera = tmp_path / "otro" / "a.jpg"
    assert bd._path_guardable(fuera) == str(fuera)


def test_guardar_media_dedup_por_shortcode(cx, tmp_path, monkeypatch) -> None:
    """Un post ya ingestado (por el scraper o por una corrida previa) no se repite."""
    monkeypatch.setattr(bd.config, "resolve_photos_dir", lambda: tmp_path)
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k")
    db.insert(cx, "photos", band_id=bid, path="x.jpg", source_post_id="ABC")
    filas = bd.guardar_media(cx, bid, "k", [_media()],
                             _descargador=lambda u, d: pytest.fail("no debió bajar"))
    assert filas == []


def test_guardar_media_descarga_fallida_no_inserta(cx, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bd.config, "resolve_photos_dir", lambda: tmp_path)
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k")
    filas = bd.guardar_media(cx, bid, "k", [_media()], _descargador=lambda u, d: False)
    assert filas == []
    assert db.rows(cx, "SELECT 1 FROM photos WHERE band_id = ?", (bid,)) == []


# ---------- orquestación ----------

def test_traer_registra_y_cuenta(cx, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", "999")
    monkeypatch.setattr(bd.config, "FB_PAGE_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(bd.config, "resolve_photos_dir", lambda: tmp_path)
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(bd, "_descargar", lambda u, d: (d.write_bytes(b"j"), True)[1])
    _mock_get(monkeypatch, _perfil(medias=[_media()]))

    res = bd.traer(["@kabala_oficial"], _cx=cx)
    assert res["fotos"] == 1
    assert res["ok"][0]["handle"] == "kabala_oficial"
    assert db.rows(cx, "SELECT scraped_at FROM bands")[0]["scraped_at"]


def test_traer_personal_no_tumba_lote(cx, monkeypatch) -> None:
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", "999")
    monkeypatch.setattr(bd.config, "FB_PAGE_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(bd, "_get", lambda url, params: _Resp(
        {"error": {"message": "(#110) not a Business or Creator account", "code": 110}}))

    res = bd.traer(["personal_uno", "personal_dos"], _cx=cx)
    assert res["personales"] == ["personal_uno", "personal_dos"]
    assert res["ok"] == [] and not res["cortado_por_cuota"]


def test_traer_corta_en_seco_por_cuota(cx, monkeypatch) -> None:
    """Agotada la cuota, insistir solo empeora: el lote se corta al primer 429."""
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", "999")
    monkeypatch.setattr(bd.config, "FB_PAGE_ACCESS_TOKEN", "tok")
    llamadas = []

    def _get(url, params):
        llamadas.append(url)
        return _Resp({"error": {"message": "Application request limit reached", "code": 4}})

    monkeypatch.setattr(bd, "_get", _get)
    res = bd.traer(["a", "b", "c"], _cx=cx)
    assert res["cortado_por_cuota"] is True
    assert len(llamadas) == 1  # no siguió con b ni c
