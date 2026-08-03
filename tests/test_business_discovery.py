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


# ---------- modo selectivo ----------

def test_traer_selectivo_borra_lo_que_no_entra(cx, tmp_path, monkeypatch) -> None:
    """Las fotos que no entran al banco se borran del disco y de la DB."""
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", "999")
    monkeypatch.setattr(bd.config, "FB_PAGE_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(bd.config, "resolve_photos_dir", lambda: tmp_path)
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(bd, "_descargar", lambda u, d: (d.write_bytes(b"j"), True)[1])
    medias = [_media(shortcode=f"S{i}") for i in range(3)]
    _mock_get(monkeypatch, _perfil(medias=medias))

    # El banco solo deja la primera; las demás SÍ se juzgaron (nitidez seteada).
    def fake_procesar(conn, band_id, **kw):
        ids = [r["id"] for r in db.rows(conn, "SELECT id FROM photos ORDER BY id")]
        for pid in ids[1:]:
            db.update(conn, "photos", pid, usable_meme=0, nitidez=1.0)
        db.update(conn, "photos", ids[0], usable_meme=1, nitidez=9.0)
        return {"personas": 1, "fotos_dentro": 1, "fotos_fuera": len(ids) - 1,
                "duplicadas": 0}

    monkeypatch.setattr(bd.banco, "procesar_banda", fake_procesar)
    res = bd.traer(["kabala_oficial"], _cx=cx, selectivo=True)

    assert res["fotos"] == 1
    assert len(db.rows(cx, "SELECT id FROM photos")) == 1
    assert len(list((tmp_path / "kabala_oficial").glob("*.jpg"))) == 1


def test_traer_no_selectivo_conserva_todo(cx, tmp_path, monkeypatch) -> None:
    """El modo por defecto no borra nada: compatible con lo ya traído."""
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", "999")
    monkeypatch.setattr(bd.config, "FB_PAGE_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(bd.config, "resolve_photos_dir", lambda: tmp_path)
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(bd, "_descargar", lambda u, d: (d.write_bytes(b"j"), True)[1])
    _mock_get(monkeypatch, _perfil(medias=[_media(shortcode=f"S{i}") for i in range(3)]))
    res = bd.traer(["kabala_oficial"], _cx=cx)
    assert res["fotos"] == 3
    assert len(db.rows(cx, "SELECT id FROM photos")) == 3


def test_selectivo_limite_cubre_todas_las_vivas(cx, tmp_path, monkeypatch) -> None:
    """El `limite` que recibe `procesar_banda` debe cubrir TODAS las fotos
    vivas de la banda (viejas conservadas + recién bajadas), no el default
    de 40 — si no, las nuevas con `nitidez` NULL nunca competirían por el
    cupo (se quedarían en el limbo: el guard de `_podar_fuera_del_banco`
    las salva del borrado, pero nunca las juzga)."""
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", "999")
    monkeypatch.setattr(bd.config, "FB_PAGE_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(bd.config, "resolve_photos_dir", lambda: tmp_path)
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(bd, "_descargar", lambda u, d: (d.write_bytes(b"j"), True)[1])

    # 45 fotos viejas ya conservadas: por sí solas ya rebasan el default
    # de `procesar_banda` (`limite=40`), barato de sembrar (sin descarga real).
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    for i in range(45):
        db.insert(cx, "photos", band_id=bid, path=f"vieja_{i}.jpg",
                 source_post_id=f"OLD{i}", usable_meme=0, nitidez=3.0)

    medias = [_media(shortcode=f"NEW{i}") for i in range(3)]
    _mock_get(monkeypatch, _perfil(medias=medias))

    limites_recibidos: list[int] = []

    def fake_procesar(conn, band_id, *, limite=40, **kw):
        limites_recibidos.append(limite)
        for r in db.rows(conn, "SELECT id FROM photos WHERE band_id = ?", (band_id,)):
            db.update(conn, "photos", r["id"], usable_meme=1, nitidez=1.0)
        return {"personas": 1, "fotos_dentro": 48, "fotos_fuera": 0, "duplicadas": 0}

    monkeypatch.setattr(bd.banco, "procesar_banda", fake_procesar)
    bd.traer(["kabala_oficial"], _cx=cx, selectivo=True)

    # 45 viejas + 3 nuevas = 48: inequívocamente distinto del default (40),
    # así que este test falla si alguien revierte a la llamada sin `limite`.
    assert limites_recibidos == [48]


def test_selectivo_no_borra_fotos_no_juzgadas(cx, tmp_path, monkeypatch) -> None:
    """Invariante: NO SE BORRA LO QUE NO SE JUZGÓ (nitidez NULL nunca se borra).

    Simula un banco que, pese al `limite` que recibió, solo alcanza a
    escribir `nitidez` en 2 de las 3 fotos vivas (p. ej. porque el `limite`
    seguía siendo insuficiente en algún punto del flujo). La 3a nunca
    compitió por el cupo — se queda con `usable_meme=0` de default de
    columna pero `nitidez` en NULL — y debe sobrevivir a la poda.
    """
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", "999")
    monkeypatch.setattr(bd.config, "FB_PAGE_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(bd.config, "resolve_photos_dir", lambda: tmp_path)
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(bd, "_descargar", lambda u, d: (d.write_bytes(b"j"), True)[1])
    medias = [_media(shortcode=f"S{i}") for i in range(3)]
    _mock_get(monkeypatch, _perfil(medias=medias))

    def fake_procesar(conn, band_id, **kw):
        ids = [r["id"] for r in db.rows(conn, "SELECT id FROM photos ORDER BY id")]
        db.update(conn, "photos", ids[0], usable_meme=1, nitidez=9.0)   # entra
        db.update(conn, "photos", ids[1], usable_meme=0, nitidez=1.0)   # pierde el cupo
        # ids[2] no se toca: usable_meme=0 (default), nitidez=NULL — nunca juzgada
        return {"personas": 1, "fotos_dentro": 1, "fotos_fuera": 1, "duplicadas": 0}

    monkeypatch.setattr(bd.banco, "procesar_banda", fake_procesar)
    bd.traer(["kabala_oficial"], _cx=cx, selectivo=True)

    filas = db.rows(cx, "SELECT source_post_id, nitidez FROM photos")
    codigos = {f["source_post_id"] for f in filas}
    assert codigos == {"S0", "S2"}   # S1 sí se borró (perdió, juzgada); S2 sobrevive
    assert len(list((tmp_path / "kabala_oficial").glob("*.jpg"))) == 2


def test_selectivo_no_infla_conteo_en_banda_ya_poblada(cx, tmp_path, monkeypatch) -> None:
    """resumen['fotos'] cuenta solo lo de ESTA corrida, no el total vivo de la banda."""
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", "999")
    monkeypatch.setattr(bd.config, "FB_PAGE_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(bd.config, "resolve_photos_dir", lambda: tmp_path)
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(bd, "_descargar", lambda u, d: (d.write_bytes(b"j"), True)[1])

    # La banda ya traía 5 fotos viejas conservadas (fuera del cupo, nunca borradas).
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    for i in range(5):
        db.insert(cx, "photos", band_id=bid, path=f"vieja_{i}.jpg",
                 source_post_id=f"OLD{i}", usable_meme=0, nitidez=3.0)

    _mock_get(monkeypatch, _perfil(medias=[_media(shortcode="NEW1")]))

    def fake_procesar(conn, band_id, **kw):
        fila = db.rows(conn,
            "SELECT id FROM photos WHERE band_id = ? AND source_post_id = 'NEW1'",
            (band_id,))[0]
        db.update(conn, "photos", fila["id"], usable_meme=1, nitidez=9.0)
        return {"personas": 1, "fotos_dentro": 1, "fotos_fuera": 0, "duplicadas": 0}

    monkeypatch.setattr(bd.banco, "procesar_banda", fake_procesar)
    res = bd.traer(["kabala_oficial"], _cx=cx, selectivo=True)

    assert res["fotos"] == 1                                   # no cuenta las 5 viejas
    assert len(db.rows(cx, "SELECT id FROM photos")) == 6       # 5 viejas + 1 nueva, nada se borró


def test_selectivo_banco_truena_no_tumba_lote(cx, tmp_path, monkeypatch) -> None:
    """Si el banco truena analizando una cuenta, el lote sigue con las demás."""
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", "999")
    monkeypatch.setattr(bd.config, "FB_PAGE_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(bd.config, "resolve_photos_dir", lambda: tmp_path)
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(bd, "_descargar", lambda u, d: (d.write_bytes(b"j"), True)[1])

    def _get(url, params):
        if "banda1" in params["fields"]:
            return _Resp(_perfil(handle="banda1", medias=[_media(shortcode="S1")]))
        return _Resp(_perfil(handle="banda2", medias=[_media(shortcode="S2")]))

    monkeypatch.setattr(bd, "_get", _get)

    llamadas: list[int] = []

    def fake_procesar(conn, band_id, **kw):
        llamadas.append(band_id)
        if len(llamadas) == 1:
            raise RuntimeError("imagen corrupta")
        fila = db.rows(conn, "SELECT id FROM photos WHERE band_id = ?", (band_id,))[0]
        db.update(conn, "photos", fila["id"], usable_meme=1, nitidez=5.0)
        return {"personas": 1, "fotos_dentro": 1, "fotos_fuera": 0, "duplicadas": 0}

    monkeypatch.setattr(bd.banco, "procesar_banda", fake_procesar)
    res = bd.traer(["banda1", "banda2"], _cx=cx, selectivo=True)

    assert res["errores"] == ["banda1"]
    assert [o["handle"] for o in res["ok"]] == ["banda2"]
    assert res["fotos"] == 1
    assert len(llamadas) == 2   # el banco sí se intentó para las dos cuentas
