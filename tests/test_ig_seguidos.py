"""Fuente «Seguidos de IG» (plan 5 del editor v2). Sin red: IG se simula con fixtures."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from curl_cffi.requests.exceptions import HTTPError
from PIL import Image

import config
from src import assets, db, import_followees, ingest_ig, jobs
from src.assets import biblioteca, ig_seguidos
from src.jobs import handlers

FIX = Path(__file__).parent / "fixtures" / "assets" / "ig"


@pytest.fixture
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def cuadro_falso(request, monkeypatch):
    """Ninguna prueba rápida llama ffmpeg real: el cuadro sale de los bytes del video."""
    if request.node.get_closest_marker("lento"):
        return

    def falso(video, destino):
        destino.write_bytes(_png(video.read_bytes().decode("latin-1")))
        return destino

    monkeypatch.setattr(ig_seguidos, "primer_cuadro", falso)


@pytest.fixture
def ids(cx) -> dict[str, int]:
    """Ids reales devueltos por insert (init_db siembra gdlscene=1; no se asume nada)."""
    return {
        "a": db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p",
                       nombre="P", ciudad="CDMX"),
        "b": db.insert(cx, "accounts", slug="daisies", ig_handle="@d",
                       nombre="D", ciudad="CDMX"),
    }


def test_normalizar_handle_rechaza_no_ascii_que_minuscula_a_ascii() -> None:
    with pytest.raises(ValueError):
        ig_seguidos.normalizar_handle("\u212aafe")      # signo Kelvin: .lower() -> 'k'
    assert ig_seguidos.normalizar_handle("  @Cafe.Tacuba ") == "cafe.tacuba"


def test_precondicion_plan3_brand_assets_existe(cx) -> None:
    cols = {r[1] for r in cx.execute("PRAGMA table_info(brand_assets)")}
    assert {"account_id", "tipo", "archivo", "sha", "proveedor", "ig_handle",
            "source_post_id", "tags_json"} <= cols


def test_tabla_ig_cuentas_defaults(cx, ids) -> None:
    cid = db.insert(cx, "brand_ig_cuentas", account_id=ids["a"], ig_handle="cafe.tacuba")
    fila = db.get(cx, "brand_ig_cuentas", cid)
    assert fila["estado"] == "candidata"
    assert fila["origen"] == "manual"
    assert fila["privada"] == 0


def test_tabla_ig_cuentas_unica_por_marca(cx, ids) -> None:
    db.insert(cx, "brand_ig_cuentas", account_id=ids["a"], ig_handle="cafe.tacuba")
    db.insert(cx, "brand_ig_cuentas", account_id=ids["b"], ig_handle="cafe.tacuba")  # otra marca: OK
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_ig_cuentas", account_id=ids["a"], ig_handle="cafe.tacuba")


def test_tabla_ig_cuentas_estado_invalido(cx, ids) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_ig_cuentas", account_id=ids["a"], ig_handle="x", estado="aprobada")


def _following() -> list[dict]:
    return json.loads((FIX / "following.json").read_text())


@pytest.fixture
def following_falso(monkeypatch, tmp_path):
    """Following simulado sin red: pool temporal, perfil y paginación falsos.
    `llamadas` registra (semilla, limite) de cada listado."""
    pool = tmp_path / "ig_accounts.json"
    pool.write_text(json.dumps([
        {"label": "t1", "sessionid": "s1", "ua": "u", "quemada_hasta": None},
        {"label": "t2", "sessionid": "s2", "ua": "u", "quemada_hasta": None},
    ]))
    monkeypatch.setattr(config, "resolve_ig_accounts_path", lambda: pool)
    monkeypatch.setattr(ingest_ig, "get_session", lambda cuenta=None: object())
    llamadas: list[tuple] = []
    perfil = lambda session, handle: {"id": handle, "edge_follow": {"count": 4}}  # noqa: E731
    monkeypatch.setattr(ingest_ig, "fetch_profile", perfil)
    monkeypatch.setattr(import_followees, "fetch_profile", perfil)  # el flujo gdlscene lo importó por nombre
    monkeypatch.setattr(import_followees, "listar_following",
                        lambda session, uid, limite=None:
                        llamadas.append((uid, limite)) or _following())
    return llamadas


def test_normalizar_handle() -> None:
    assert ig_seguidos.normalizar_handle("  @Cafe.Tacuba ") == "cafe.tacuba"
    for malo in ("", "@", "../x", "a b", "x" * 31, "café", "a..b"):
        with pytest.raises(ValueError):
            ig_seguidos.normalizar_handle(malo)


def test_importar_seguidos_crea_candidatas(cx, ids, following_falso) -> None:
    a, b = ids["a"], ids["b"]
    r = ig_seguidos.importar_seguidos(cx, a, "@PensionMas", limite=50)
    assert following_falso == [("pensionmas", 50)]
    assert r == {"nuevas": 3, "ya": 0, "total": 4}          # el handle con "../" se salta
    filas = {f["ig_handle"]: f for f in ig_seguidos.listar(cx, a)}
    assert set(filas) == {"cafe.tacuba", "la_privada", "mercado.roma"}
    cafe = filas["cafe.tacuba"]
    assert cafe["estado"] == "candidata"
    assert cafe["origen"] == "seguido_de:pensionmas"
    assert cafe["nombre"] == "Café Tacuba Bar"
    assert cafe["avatar_url"].startswith("https://")
    assert cafe["privada"] == 0
    assert filas["la_privada"]["privada"] == 1
    assert filas["la_privada"]["nombre"] == "la_privada"   # full_name vacío => handle
    assert filas["mercado.roma"]["avatar_url"] is None     # solo https://
    assert ig_seguidos.listar(cx, b) == []                 # otra marca no ve nada


def test_reimportar_respeta_curaduria(cx, ids, following_falso) -> None:
    a = ids["a"]
    ig_seguidos.importar_seguidos(cx, a, "pensionmas")
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    ig_seguidos.fijar_estado(cx, a, "la_privada", "descartada")
    r = ig_seguidos.importar_seguidos(cx, a, "otra.semilla")
    assert r == {"nuevas": 0, "ya": 3, "total": 4}
    estados = {f["ig_handle"]: (f["estado"], f["origen"]) for f in ig_seguidos.listar(cx, a)}
    assert estados == {
        "cafe.tacuba": ("activa", "seguido_de:pensionmas"),
        "la_privada": ("descartada", "seguido_de:pensionmas"),
        "mercado.roma": ("candidata", "seguido_de:pensionmas"),
    }


def test_fijar_estado_upsert_manual(cx, ids) -> None:
    a = ids["a"]
    fila = ig_seguidos.fijar_estado(cx, a, "@Nueva.Cuenta", "activa")
    assert (fila["ig_handle"], fila["estado"], fila["origen"]) == ("nueva.cuenta", "activa", "manual")
    fila = ig_seguidos.fijar_estado(cx, a, "nueva.cuenta", "descartada")
    assert fila["estado"] == "descartada"
    assert fila["origen"] == "manual"
    filas = ig_seguidos.listar(cx, a)
    assert [(f["ig_handle"], f["estado"]) for f in filas] == [("nueva.cuenta", "descartada")]
    with pytest.raises(ValueError):
        ig_seguidos.fijar_estado(cx, a, "nueva.cuenta", "aprobada")
    assert ig_seguidos.listar(cx, a)[0]["estado"] == "descartada"   # el rechazo no mutó nada


def test_fijar_estado_no_cruza_marcas(cx, ids) -> None:
    ig_seguidos.fijar_estado(cx, ids["a"], "comun", "activa")
    ig_seguidos.fijar_estado(cx, ids["b"], "comun", "descartada")
    assert ig_seguidos.listar(cx, ids["a"])[0]["estado"] == "activa"
    assert ig_seguidos.listar(cx, ids["b"])[0]["estado"] == "descartada"


def test_listar_filtra_por_estado(cx, ids) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "a1", "activa")
    ig_seguidos.fijar_estado(cx, a, "c1", "candidata")
    ig_seguidos.fijar_estado(cx, a, "d1", "descartada")
    assert [f["ig_handle"] for f in ig_seguidos.listar(cx, a, estado="activa")] == ["a1"]
    assert [f["ig_handle"] for f in ig_seguidos.listar(cx, a)] == ["c1", "a1", "d1"]  # candidatas primero
    with pytest.raises(ValueError):
        ig_seguidos.listar(cx, a, estado="todas")


def test_importar_gdlscene_sigue_escribiendo_bands(cx, ids, tmp_path, following_falso, monkeypatch) -> None:
    """El flujo de gdlscene no cambia y no se cruza con brand_ig_cuentas."""
    real = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: real(tmp_path / "t.db"))
    r = import_followees.importar(cuenta="gdlscene", limite=10)
    assert following_falso == [("gdlscene", 10)]
    assert r == {"nuevas": 4, "ya": 0, "total": 4}   # importar no valida handles: el "../" entra a bands
    handles = {f["ig_handle"] for f in db.rows(cx, "SELECT ig_handle FROM bands", ())}
    assert "cafe.tacuba" in handles
    assert db.rows(cx, "SELECT id FROM brand_ig_cuentas", ()) == []


@pytest.mark.lento
@pytest.mark.ig_real
@pytest.mark.skipif(os.getenv("IG_REAL") != "1",
                    reason="usa una cookie real del pool; correr solo con aprobación de Ricardo")
def test_contrato_following_real() -> None:
    """Confirma las llaves que los fixtures inventaron. IG_REAL=1 pytest -m ig_real."""
    usuarios = import_followees._listar_con_pool("gdlscene", 5)
    assert usuarios, "following vacío"
    assert {"username", "full_name", "is_private", "profile_pic_url"} <= set(usuarios[0])


def _png(semilla: str) -> bytes:
    """PNG chico y distinto por semilla: sha distinto por medio."""
    h = hashlib.sha256(semilla.encode()).digest()
    buf = io.BytesIO()
    Image.new("RGB", (40, 50), (h[0], h[1], h[2])).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def ig_falso(monkeypatch, tmp_path):
    """IG simulado sin red: pool temporal, sesión falsa, _get_json con fixtures,
    _download escribe un PNG/MP4 local."""
    pool = tmp_path / "ig_accounts.json"
    pool.write_text(json.dumps([
        {"label": "t1", "sessionid": "s1", "ua": "u", "quemada_hasta": None},
        {"label": "t2", "sessionid": "s2", "ua": "u", "quemada_hasta": None},
    ]))
    monkeypatch.setattr(config, "resolve_ig_accounts_path", lambda: pool)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "data" / "brands")
    monkeypatch.setattr(ingest_ig, "get_session", lambda cuenta=None: object())
    monkeypatch.setattr(ingest_ig, "_sleep", lambda: None)
    estado = {"get_json": [], "descargas": [], "fallar": []}

    def get_json(session, url, params=None):
        estado["get_json"].append(url)
        if estado["fallar"]:
            raise estado["fallar"].pop(0)
        if "web_profile_info" in url:
            datos = json.loads((FIX / "web_profile_info.json").read_text())
            datos["data"]["user"]["username"] = params["username"]
            return datos
        if "/feed/user/" in url:
            return json.loads((FIX / "feed_user.json").read_text())
        raise AssertionError(f"URL inesperada {url}")

    def download(session, url, dest):
        estado["descargas"].append(url)
        dest.write_bytes(b"\x00\x00\x00\x18ftypmp42" + url.encode() if ".mp4" in url else _png(url))
        return True

    monkeypatch.setattr(ingest_ig, "_get_json", get_json)
    monkeypatch.setattr(ingest_ig, "_download", download)
    return estado


def _assets(cx, account_id) -> list[dict]:
    return [dict(r) for r in db.rows(
        cx, "SELECT * FROM brand_assets WHERE account_id = ? ORDER BY id", (account_id,))]


def _fotos_propias(cx, account_id) -> list[dict]:
    """Fotos del feed (no los cuadros que el Task 5 saca de los videos)."""
    return [a for a in _assets(cx, account_id)
            if a["tipo"] == "imagen" and "cuadro_de_video" not in (a["tags_json"] or "")]


def test_ingerir_baja_fotos_de_cuentas_activas(cx, ids, ig_falso) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    ig_seguidos.fijar_estado(cx, a, "candidata.sin.aprobar", "candidata")
    ig_seguidos.fijar_estado(cx, a, "descartada.x", "descartada")
    r = ig_seguidos.ingerir(cx, a, por_cuenta=12)
    assert r == {"cuentas": 1, "assets": 4, "errores": [], "cortado": False, "pendientes": 0}   # 2 fotos + 2 videos
    fotos = _fotos_propias(cx, a)
    assert len(fotos) == 2                                   # foto suelta + foto del carrusel
    f = fotos[0]
    assert f["proveedor"] == "ig_seguidos"
    assert f["autor"] == "@cafe.tacuba"
    assert f["licencia"] == "Instagram (terceros)"
    assert f["url_origen"] == "https://www.instagram.com/p/CfOtO1/"
    assert f["ig_handle"] == "cafe.tacuba"
    assert f["source_post_id"] == "9001"
    assert (f["ancho"], f["alto"]) == (40, 50)
    assert json.loads(f["tags_json"]) == {"fuente": "ig_seguidos",
                                          "caption": "Noche de vinilos en la terraza"}
    assert fotos[1]["url_origen"] == "https://www.instagram.com/p/CaRr-2_x/"
    assert fotos[1]["source_post_id"] == "9002"
    assert len(ig_falso["get_json"]) == 2                    # un perfil + un feed, solo de la activa
    assert not any(("candidata" in u) or ("descartada" in u) for u in ig_falso["get_json"])
    cuenta = ig_seguidos.listar(cx, a, estado="activa")[0]
    assert cuenta["bio"] == "Mezcal y vinilos · CDMX"
    assert cuenta["ig_user_id"] == "111"
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", cuenta["scraped_at"])
    assert _assets(cx, ids["b"]) == []                       # otra marca no recibe nada


def test_ingerir_es_idempotente(cx, ids, ig_falso) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    assert ig_seguidos.ingerir(cx, a)["assets"] == 4
    antes = _assets(cx, a)
    descargas = len(ig_falso["descargas"])
    r = ig_seguidos.ingerir(cx, a)
    assert r == {"cuentas": 1, "assets": 0, "errores": [], "cortado": False, "pendientes": 0}
    assert _assets(cx, a) == antes
    assert len(ig_falso["descargas"]) == descargas          # post ya ingerido: ni se baja


def test_nombre_de_archivo_sin_datos_de_ig(cx, ids, ig_falso, tmp_path) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    ig_seguidos.ingerir(cx, a)
    raiz = biblioteca.ruta_de("pensionmas", "x").parent.resolve()
    assert str(raiz).startswith(str(tmp_path.resolve()))
    filas = _assets(cx, a)
    assert len(filas) == 6                                  # 2 fotos + 2 cuadros + 2 videos
    for f in filas:
        assert re.fullmatch(r"ig_[0-9a-f]{20}\.(jpg|png|webp|mp4)", f["archivo"])
        assert f["archivo"].startswith(f"ig_{f['sha'][:20]}")
        ruta = biblioteca.ruta_de("pensionmas", f["archivo"]).resolve()
        assert ruta.parent == raiz and ruta.is_file()
        assert hashlib.sha256(ruta.read_bytes()).hexdigest() == f["sha"]
    assert sorted(p.name for p in raiz.iterdir()) == sorted(f["archivo"] for f in filas)


def test_perfil_privado_no_baja_nada(cx, ids, ig_falso, monkeypatch) -> None:
    real = ingest_ig._get_json

    def privado(session, url, params=None):
        datos = real(session, url, params)
        if "web_profile_info" in url:
            datos["data"]["user"]["is_private"] = True
        return datos

    monkeypatch.setattr(ingest_ig, "_get_json", privado)
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    r = ig_seguidos.ingerir(cx, a)
    assert r == {"cuentas": 1, "assets": 0, "errores": [], "cortado": False, "pendientes": 0}
    cuenta = ig_seguidos.listar(cx, a)[0]
    assert cuenta["privada"] == 1 and cuenta["notas"] == "perfil privado: no se puede ingerir"
    assert not any("/feed/user/" in u for u in ig_falso["get_json"])
    assert _assets(cx, a) == []


def test_ingerir_sin_cuentas_activas_no_toca_ig(cx, ids, ig_falso) -> None:
    assert ig_seguidos.ingerir(cx, ids["a"]) == {"cuentas": 0, "assets": 0, "errores": [],
                                                 "cortado": False, "pendientes": 0}
    assert ig_falso["get_json"] == []


def test_ingerir_progreso_y_aislamiento_de_fallos(cx, ids, ig_falso, monkeypatch) -> None:
    """LookupError, KeyError (perfil sin id) y errores de red no tiran a las demás."""
    real = ingest_ig._get_json

    def malo(session, url, params=None):
        u = (params or {}).get("username")
        if u == "rota":
            return {"data": {"user": None}}
        if u == "sin.id":
            return {"data": {"user": {"username": u, "is_private": False}}}
        if u == "red":
            raise ConnectionError("reset")
        return real(session, url, params)

    monkeypatch.setattr(ingest_ig, "_get_json", malo)
    a = ids["a"]
    for h in ("rota", "sin.id", "red", "cafe.tacuba"):
        ig_seguidos.fijar_estado(cx, a, h, "activa")
    avance: list[tuple[int, str]] = []
    r = ig_seguidos.ingerir(cx, a, progreso=lambda p, m: avance.append((p, m)))
    assert r["cuentas"] == 1 and r["assets"] == 4 and r["cortado"] is False
    assert [e.split(":")[0] for e in r["errores"]] == ["@red", "@rota", "@sin.id"]
    assert r["errores"][1].startswith("@rota: LookupError")
    assert r["errores"][2].startswith("@sin.id: KeyError")
    assert [m for _, m in avance] == ["@cafe.tacuba", "@red", "@rota", "@sin.id"]
    assert [p for p, _ in avance] == [0, 25, 50, 75]


def _origen() -> ig_seguidos._Origen:
    return ig_seguidos._Origen(handle="cafe.tacuba", codigo="Abc", post_id="1", caption="c")


def _reg(cx, a, tmp_path, datos: bytes, tipo="imagen"):
    p = tmp_path / "crudo"
    p.write_bytes(datos)
    return ig_seguidos._registrar(cx, a, "pensionmas", _origen(), p, tipo=tipo)


def test_registrar_rechaza_magic_bytes_tipo_y_tope(cx, ids, ig_falso, tmp_path, monkeypatch) -> None:
    a = ids["a"]
    assert _reg(cx, a, tmp_path, b"<html>no soy imagen</html>") == (None, False)
    gif = io.BytesIO()
    Image.new("RGB", (4, 4)).save(gif, "GIF")
    assert _reg(cx, a, tmp_path, gif.getvalue()) == (None, False)     # gif fuera de la lista
    assert _reg(cx, a, tmp_path, _png("x"), tipo="video") == (None, False)
    monkeypatch.setitem(biblioteca.TOPES, "imagen", 10)
    assert _reg(cx, a, tmp_path, _png("x")) == (None, False)          # excede el tope
    assert _assets(cx, a) == []
    raiz = biblioteca.ruta_de("pensionmas", "x").parent
    assert not raiz.exists() or list(raiz.iterdir()) == []            # nada llegó a disco


def test_registrar_acepta_mp4_con_dims(cx, ids, ig_falso, tmp_path) -> None:
    mp4 = b"\x00\x00\x00\x18ftypmp42" + b"x" * 20
    p = tmp_path / "crudo"
    p.write_bytes(mp4)
    fila, nueva = ig_seguidos._registrar(cx, ids["a"], "pensionmas", _origen(), p,
                                         tipo="video", dims=(720, 1280))
    assert nueva is True
    assert (fila["tipo"], fila["ancho"], fila["alto"]) == ("video", 720, 1280)
    assert fila["archivo"] == f"ig_{fila['sha'][:20]}.mp4"


def test_registrar_duplicado_devuelve_la_fila_existente(cx, ids, ig_falso, tmp_path) -> None:
    a = ids["a"]
    f1, n1 = _reg(cx, a, tmp_path, _png("x"))
    f2, n2 = _reg(cx, a, tmp_path, _png("x"))
    assert (n1, n2) == (True, False) and f1["id"] == f2["id"]
    assert len(_assets(cx, a)) == 1


def test_registrar_no_resucita_descartados(cx, ids, ig_falso, tmp_path) -> None:
    a = ids["a"]
    f1, _ = _reg(cx, a, tmp_path, _png("x"))
    db.update(cx, "brand_assets", f1["id"], descartada=1)
    f2, nueva = _reg(cx, a, tmp_path, _png("x"))
    assert nueva is False and f2["id"] == f1["id"] and f2["descartada"] == 1
    assert _assets(cx, a)[0]["descartada"] == 1


def test_registrar_carrera_integrity_error_es_duplicado(cx, ids, ig_falso, tmp_path, monkeypatch) -> None:
    """Otra llamada inserta los mismos bytes entre el SELECT y el INSERT."""
    a = ids["a"]
    f1, _ = _reg(cx, a, tmp_path, _png("x"))
    original = db.rows
    ciegas = {"n": 2}   # _registrar y guardar_bytes no ven la fila; el INSERT choca

    def ciega(cx_, sql, params=()):
        if "FROM brand_assets WHERE account_id = ? AND sha = ?" in sql and ciegas["n"] > 0:
            ciegas["n"] -= 1
            return []
        return original(cx_, sql, params)

    monkeypatch.setattr(db, "rows", ciega)
    fila, nueva = _reg(cx, a, tmp_path, _png("x"))
    assert ciegas["n"] == 0
    assert nueva is False and fila["id"] == f1["id"]
    assert len(_assets(cx, a)) == 1


def test_guardar_bytes_prefijo_largo_y_exts(cx, ids, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    a = ids["a"]
    png = _png("p")
    sha = hashlib.sha256(png).hexdigest()
    por_defecto, _ = biblioteca.guardar_bytes(cx, a, "pensionmas", png, proveedor="subida")
    assert por_defecto["archivo"] == f"{sha[:16]}.png"             # comportamiento previo
    otra = _png("q")
    sha2 = hashlib.sha256(otra).hexdigest()
    fila, nueva = biblioteca.guardar_bytes(cx, a, "pensionmas", otra, proveedor="x",
                                           prefijo="ig_", largo_sha=20,
                                           exts=frozenset({"png"}))
    assert nueva is True and fila["archivo"] == f"ig_{sha2[:20]}.png"
    gif = io.BytesIO()
    Image.new("RGB", (4, 4)).save(gif, "GIF")
    with pytest.raises(biblioteca.AssetInvalido, match="formato no soportado"):
        biblioteca.guardar_bytes(cx, a, "pensionmas", gif.getvalue(), proveedor="x",
                                 exts=frozenset({"png"}))
    # sin exts el gif sigue aceptándose
    g, _ = biblioteca.guardar_bytes(cx, a, "pensionmas", gif.getvalue(), proveedor="x")
    assert g["archivo"].endswith(".gif")
    with pytest.raises(ValueError, match="prefijo"):
        biblioteca.guardar_bytes(cx, a, "pensionmas", _png("z"), proveedor="x", prefijo="../")


def test_ingerir_reels_y_videos_de_carrusel(cx, ids, ig_falso) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    r = ig_seguidos.ingerir(cx, a)
    videos = [v for v in _assets(cx, a) if v["tipo"] == "video"]
    cuadros = [c for c in _assets(cx, a) if "cuadro_de_video" in (c["tags_json"] or "")]
    assert len(videos) == 2 and len(cuadros) == 2
    assert r["assets"] == 4                                  # 2 fotos + 2 videos (el cuadro no cuenta)
    assert all(c["tipo"] == "imagen" for c in cuadros)
    reel = next(v for v in videos if v["source_post_id"] == "9003")
    poster = json.loads(reel["tags_json"])["poster"]
    assert poster in {c["archivo"] for c in cuadros}
    assert reel["archivo"].endswith(".mp4")
    assert (reel["ancho"], reel["alto"]) == (40, 50)         # dimensiones del cuadro
    assert reel["url_origen"] == "https://www.instagram.com/p/ReEl3/"
    assert len(_fotos_propias(cx, a)) == 2                   # lo del Task 4 sigue valiendo
    # idempotente: segunda corrida no agrega nada
    assert ig_seguidos.ingerir(cx, a)["assets"] == 0
    assert len(_assets(cx, a)) == 6


def test_video_sin_cuadro_se_salta(cx, ids, ig_falso, monkeypatch) -> None:
    def roto(video, destino):
        raise subprocess.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr(ig_seguidos, "primer_cuadro", roto)
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    r = ig_seguidos.ingerir(cx, a)
    assert [v for v in _assets(cx, a) if v["tipo"] == "video"] == []
    assert len(_assets(cx, a)) == 2 and r["assets"] == 2
    assert len(_fotos_propias(cx, a)) == 2


def _estado_ig(cx, ids, ig_falso):
    ig_seguidos.fijar_estado(cx, ids["a"], "cafe.tacuba", "activa")
    return ig_seguidos.ingerir(cx, ids["a"])


def test_mp4_rechazado_no_deja_cuadro_huerfano(cx, ids, ig_falso, monkeypatch) -> None:
    llamadas = []
    monkeypatch.setitem(biblioteca.TOPES, "video", 5)           # todo mp4 excede el tope
    monkeypatch.setattr(ig_seguidos, "primer_cuadro",
                        lambda v, d: llamadas.append(v) or d)
    r = _estado_ig(cx, ids, ig_falso)
    a = ids["a"]
    assert llamadas == []                                       # ffmpeg ni se corre
    assert [x for x in _assets(cx, a) if x["tipo"] == "video"] == []
    assert not any("cuadro_de_video" in (x["tags_json"] or "") for x in _assets(cx, a))
    assert r["assets"] == 2 and len(_assets(cx, a)) == 2
    assert not ig_seguidos._ya_ingerido(cx, a, "cafe.tacuba", "9003")   # el reel se reintenta


def test_mp4_sin_magic_bytes_no_corre_ffmpeg(cx, ids, ig_falso, monkeypatch) -> None:
    llamadas = []
    monkeypatch.setattr(ingest_ig, "_download",
                        lambda s, u, d: d.write_bytes(b"<html>no</html>") or True)
    monkeypatch.setattr(ig_seguidos, "primer_cuadro", lambda v, d: llamadas.append(v) or d)
    assert _estado_ig(cx, ids, ig_falso)["assets"] == 0
    assert llamadas == [] and _assets(cx, ids["a"]) == []


@pytest.mark.parametrize("fallo", ["timeout", "no_escribe", "no_existe"])
def test_fallos_de_ffmpeg_saltan_solo_el_video(cx, ids, ig_falso, monkeypatch, fallo) -> None:
    def roto(video, destino):
        if fallo == "timeout":
            raise subprocess.TimeoutExpired("ffmpeg", 60)
        if fallo == "no_existe":
            raise FileNotFoundError("ffmpeg")
        return destino                                          # sale 0 pero no escribió el PNG

    monkeypatch.setattr(ig_seguidos, "primer_cuadro", roto)
    r = _estado_ig(cx, ids, ig_falso)
    assert r["errores"] == [] and r["cuentas"] == 1 and r["assets"] == 2
    assert [x for x in _assets(cx, ids["a"]) if x["tipo"] == "video"] == []
    assert len(_fotos_propias(cx, ids["a"])) == 2


def test_cuadro_con_sha_duplicado_reusa_la_fila(cx, ids, ig_falso) -> None:
    a = ids["a"]
    reel_url = "https://x/reel.mp4"
    # una foto previa con los mismos bytes que sacará el cuadro del reel
    previa = _reg(cx, a, Path(cx.execute("PRAGMA database_list").fetchone()[2]).parent,
                  _png("\x00\x00\x00\x18ftypmp42" + reel_url))[0]
    assert previa is not None
    ig_seguidos._bajar(cx, a, "pensionmas", object(), _origen(), "video", reel_url)
    video = next(x for x in _assets(cx, a) if x["tipo"] == "video")
    assert json.loads(video["tags_json"])["poster"] == previa["archivo"]
    assert len(_assets(cx, a)) == 2                             # foto previa + mp4, sin cuadro nuevo


def test_cuadro_descartado_no_es_poster_ni_resucita(cx, ids, ig_falso) -> None:
    a = ids["a"]
    reel_url = "https://x/reel.mp4"
    previa = _reg(cx, a, Path(cx.execute("PRAGMA database_list").fetchone()[2]).parent,
                  _png("\x00\x00\x00\x18ftypmp42" + reel_url))[0]
    db.update(cx, "brand_assets", previa["id"], descartada=1)
    ig_seguidos._bajar(cx, a, "pensionmas", object(), _origen(), "video", reel_url)
    video = next(x for x in _assets(cx, a) if x["tipo"] == "video")
    assert "poster" not in json.loads(video["tags_json"])
    assert db.get(cx, "brand_assets", previa["id"])["descartada"] == 1


def test_cuadro_que_falla_al_registrar_no_deja_poster_colgando(cx, ids, ig_falso, monkeypatch) -> None:
    real = ig_seguidos._registrar

    def sin_cuadro(cx_, a, slug, origen, tmp, *, tipo, **kw):
        if (kw.get("tags_extra") or {}).get("cuadro_de_video"):
            return None, False                                  # el cuadro no entra a la biblioteca
        return real(cx_, a, slug, origen, tmp, tipo=tipo, **kw)

    monkeypatch.setattr(ig_seguidos, "_registrar", sin_cuadro)
    a = ids["a"]
    ig_seguidos._bajar(cx, a, "pensionmas", object(), _origen(), "video", "https://x/reel.mp4")
    video = next(x for x in _assets(cx, a) if x["tipo"] == "video")
    assert "poster" not in json.loads(video["tags_json"])


def test_poster_es_el_archivo_real_del_cuadro(cx, ids, ig_falso) -> None:
    a = ids["a"]
    ig_seguidos._bajar(cx, a, "pensionmas", object(), _origen(), "video", "https://x/reel.mp4")
    todos = _assets(cx, a)
    video = next(x for x in todos if x["tipo"] == "video")
    cuadro = next(x for x in todos if x["tipo"] == "imagen")
    assert json.loads(video["tags_json"])["poster"] == cuadro["archivo"]
    assert json.loads(video["tags_json"])["fuente"] == "ig_seguidos"   # tags previos intactos


@pytest.mark.lento
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sin ffmpeg")
def test_primer_cuadro_real(tmp_path) -> None:
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=red:s=64x96:d=1", "-pix_fmt", "yuv420p", str(video)], check=True)
    png = ig_seguidos.primer_cuadro(video, tmp_path / "p.png")
    with Image.open(png) as im:
        assert im.size == (64, 96)
        assert im.getpixel((10, 10))[0] > 200


def _pool(tmp_path) -> list[dict]:
    return json.loads((tmp_path / "ig_accounts.json").read_text())


def test_rate_limit_rota_y_reintenta_la_misma_cuenta(cx, ids, ig_falso, tmp_path) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    ig_falso["fallar"].append(ingest_ig.IngestRateLimited("HTTP 429"))
    r = ig_seguidos.ingerir(cx, a)
    assert r == {"cuentas": 1, "assets": 4, "errores": [], "cortado": False, "pendientes": 0}
    pool = _pool(tmp_path)
    assert pool[0]["quemada_hasta"] and not pool[1]["quemada_hasta"]


def _http(status: int) -> HTTPError:
    return HTTPError(f"HTTP {status}", response=SimpleNamespace(status_code=status))


@pytest.mark.parametrize("status", [401, 403, 429])
def test_http_error_de_cookie_quema_y_rota(cx, ids, ig_falso, tmp_path, status) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    ig_falso["fallar"].append(_http(status))
    r = ig_seguidos.ingerir(cx, a)
    assert r == {"cuentas": 1, "assets": 4, "errores": [], "cortado": False, "pendientes": 0}
    pool = _pool(tmp_path)
    assert pool[0]["quemada_hasta"] and not pool[1]["quemada_hasta"]


def test_pool_agotado_sin_nada_lanza(cx, ids, ig_falso, tmp_path) -> None:
    ig_seguidos.fijar_estado(cx, ids["a"], "cafe.tacuba", "activa")
    ig_falso["fallar"].extend([ingest_ig.IngestRateLimited("429")] * 2)
    with pytest.raises(ingest_ig.IngestRateLimited):
        ig_seguidos.ingerir(cx, ids["a"])
    assert all(c["quemada_hasta"] for c in _pool(tmp_path))
    assert _assets(cx, ids["a"]) == []


def test_pool_agotado_a_media_corrida_devuelve_cortado(cx, ids, ig_falso, monkeypatch, tmp_path) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    ig_seguidos.fijar_estado(cx, a, "zz.segunda", "activa")
    real = ingest_ig._get_json

    def segunda_limitada(session, url, params=None):
        if params and params.get("username") == "zz.segunda":
            raise ingest_ig.IngestRateLimited("429")
        return real(session, url, params)

    monkeypatch.setattr(ingest_ig, "_get_json", segunda_limitada)
    r = ig_seguidos.ingerir(cx, a)
    assert r == {"cuentas": 1, "assets": 4, "errores": [], "cortado": True, "pendientes": 0}
    assert all(c["quemada_hasta"] for c in _pool(tmp_path))


def test_handle_inexistente_es_error_por_cuenta(cx, ids, ig_falso, monkeypatch, tmp_path) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    ig_seguidos.fijar_estado(cx, a, "aa.no.existe", "activa")
    real = ingest_ig._get_json

    def sin_usuario(session, url, params=None):
        if params and params.get("username") == "aa.no.existe":
            return {"data": {"user": None}}
        return real(session, url, params)

    monkeypatch.setattr(ingest_ig, "_get_json", sin_usuario)
    r = ig_seguidos.ingerir(cx, a)
    assert r["cuentas"] == 1 and r["cortado"] is False and len(r["errores"]) == 1
    assert r["errores"][0].startswith("@aa.no.existe: LookupError")
    assert not any(c["quemada_hasta"] for c in _pool(tmp_path))


@pytest.mark.parametrize("status", [404, 500])
def test_http_error_de_la_cuenta_no_quema_ni_corta(cx, ids, ig_falso, monkeypatch, tmp_path, status) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "aa.muerta", "activa")
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    real = ingest_ig._get_json

    def muerta(session, url, params=None):
        if params and params.get("username") == "aa.muerta":
            raise _http(status)
        return real(session, url, params)

    monkeypatch.setattr(ingest_ig, "_get_json", muerta)
    antes = _pool(tmp_path)
    r = ig_seguidos.ingerir(cx, a)
    assert r["cuentas"] == 1 and r["assets"] == 4 and r["cortado"] is False
    assert r["errores"] == [f"@aa.muerta: HTTPError: HTTP {status}"]
    assert _pool(tmp_path) == antes
    assert not any(c["quemada_hasta"] for c in _pool(tmp_path))


def _sleep_que_falla_desde(monkeypatch, n: int) -> None:
    llamadas = [0]

    def sleep():
        llamadas[0] += 1
        if llamadas[0] >= n:
            raise ingest_ig.IngestRateLimited("429 a medias")

    monkeypatch.setattr(ingest_ig, "_sleep", sleep)


def test_fallo_a_medias_cuenta_lo_guardado_y_el_reintento_completa(cx, ids, ig_falso, monkeypatch, tmp_path) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    llamadas = [0]

    def sleep():   # 1ª tras el perfil; 2ª tras el primer post bajado: falla solo esa vez
        llamadas[0] += 1
        if llamadas[0] == 2:
            raise ingest_ig.IngestRateLimited("429 a medias")

    monkeypatch.setattr(ingest_ig, "_sleep", sleep)
    r = ig_seguidos.ingerir(cx, a)
    assert r == {"cuentas": 1, "assets": 4, "errores": [], "cortado": False, "pendientes": 0}
    assert len(_assets(cx, a)) == 6   # 4 contados + 2 cuadros de video (no cuentan)
    pool = _pool(tmp_path)
    assert pool[0]["quemada_hasta"] and not pool[1]["quemada_hasta"]


def test_corte_con_progreso_parcial_no_lanza(cx, ids, ig_falso, monkeypatch, tmp_path) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    _sleep_que_falla_desde(monkeypatch, 2)
    r = ig_seguidos.ingerir(cx, a)
    guardados = len(_assets(cx, a))
    assert guardados > 0
    assert r == {"cuentas": 0, "assets": guardados, "errores": [], "cortado": True, "pendientes": 0}
    assert all(c["quemada_hasta"] for c in _pool(tmp_path))


# --- handlers de jobs (tarea 7) ---

def _job(cx, tipo, payload, account_id) -> dict:
    jid = jobs.crear(cx, tipo, account_id, payload)
    return dict(db.get(cx, "jobs", jid))


def test_handler_importar_seguidos(cx, ids, following_falso) -> None:
    job = _job(cx, "ig.importar_seguidos", {"semilla": "@pensionmas", "limite": 30}, ids["a"])
    r = handlers.HANDLERS["ig.importar_seguidos"](cx, job)
    assert r == {"nuevas": 3, "ya": 0, "total": 4}
    assert following_falso == [("pensionmas", 30)]
    assert len(ig_seguidos.listar(cx, ids["a"])) == 3
    assert "pensionmas" in (db.get(cx, "jobs", job["id"])["log"] or "")


@pytest.mark.parametrize("pedido,esperado", [(99999, 2000), (0, 1), (-5, 1), (None, 200),
                                              (1, 1), (2000, 2000)])
def test_handler_importar_acota_limite(cx, ids, following_falso, pedido, esperado) -> None:
    payload = {"semilla": "@pensionmas"} | ({} if pedido is None else {"limite": pedido})
    handlers.HANDLERS["ig.importar_seguidos"](cx, _job(cx, "ig.importar_seguidos", payload,
                                                       ids["a"]))
    assert following_falso == [("pensionmas", esperado)]


def test_handler_importar_sin_semilla_da_error_claro(cx, ids) -> None:
    job = _job(cx, "ig.importar_seguidos", {"limite": 5}, ids["a"])
    with pytest.raises(ValueError, match="semilla"):
        handlers.HANDLERS["ig.importar_seguidos"](cx, job)


def test_handler_ingerir_reporta_progreso(cx, ids, ig_falso) -> None:
    ig_seguidos.fijar_estado(cx, ids["a"], "cafe.tacuba", "activa")
    job = _job(cx, "ig.ingerir", {"por_cuenta": 5}, ids["a"])
    r = handlers.HANDLERS["ig.ingerir"](cx, job)
    assert r["cuentas"] == 1 and r["assets"] == 4
    assert "@cafe.tacuba" in (db.get(cx, "jobs", job["id"])["log"] or "")


def test_handler_ingerir_llama_progresar_por_cuenta(cx, ids, ig_falso, monkeypatch) -> None:
    for h in ("cafe.tacuba", "otra.cuenta", "tercera.cuenta"):
        ig_seguidos.fijar_estado(cx, ids["a"], h, "activa")
    llamadas = []
    monkeypatch.setattr(jobs, "progresar", lambda c, jid, pct, msg: llamadas.append((jid, msg)))
    monkeypatch.setattr(ig_seguidos, "_ingerir_cuenta", lambda *a, **k: None)
    job = _job(cx, "ig.ingerir", {"por_cuenta": 5}, ids["a"])
    handlers.HANDLERS["ig.ingerir"](cx, job)
    assert [m for _, m in llamadas] == ["@cafe.tacuba", "@otra.cuenta", "@tercera.cuenta"]
    assert {j for j, _ in llamadas} == {job["id"]}


def test_handler_ingerir_por_cuenta_acotado(cx, ids, monkeypatch) -> None:
    vistos = []
    monkeypatch.setattr(ig_seguidos, "ingerir",
                        lambda cx, aid, *, por_cuenta, progreso, desde=None: vistos.append(por_cuenta) or {})
    for pedido in (999, 0, None):
        handlers.HANDLERS["ig.ingerir"](cx, _job(cx, "ig.ingerir", {"por_cuenta": pedido}, ids["a"]))
    assert vistos == [50, 12, 12]


def test_handlers_igs_cuenta_inexistente_truena(cx, ids) -> None:
    job = _job(cx, "ig.ingerir", {"por_cuenta": 5}, ids["a"])
    job["account_id"] = 99999
    with pytest.raises(ValueError):
        handlers.HANDLERS["ig.ingerir"](cx, job)


# --- final-review I1: la semilla escrita a mano no puede quemar el pool compartido ---
def _pool_importar(tmp_path) -> list[dict]:
    return json.loads((tmp_path / "ig_accounts.json").read_text())


@pytest.mark.parametrize("status", [404, 500, 502])
def test_importar_semilla_http_no_quema_el_pool(cx, ids, following_falso, monkeypatch,
                                                tmp_path, status) -> None:
    def malo(session, handle):
        raise _http(status)

    monkeypatch.setattr(ingest_ig, "fetch_profile", malo)
    antes = _pool_importar(tmp_path)
    esperado = LookupError if status == 404 else HTTPError
    with pytest.raises(esperado) as ei:
        ig_seguidos.importar_seguidos(cx, ids["a"], "typo.no.existe")
    if status == 404:
        assert "la semilla" in str(ei.value) and "no existe" in str(ei.value)
    assert _pool_importar(tmp_path) == antes
    assert ig_seguidos.listar(cx, ids["a"]) == []


def test_importar_semilla_5xx_a_media_paginacion_no_quema(cx, ids, following_falso,
                                                          monkeypatch, tmp_path) -> None:
    def roto(session, uid, limite=None):
        raise _http(503)

    monkeypatch.setattr(import_followees, "listar_following", roto)
    antes = _pool_importar(tmp_path)
    with pytest.raises(HTTPError):
        ig_seguidos.importar_seguidos(cx, ids["a"], "pensionmas")
    assert _pool_importar(tmp_path) == antes


def test_importar_semilla_sin_datos_es_semilla_inexistente(cx, ids, following_falso,
                                                           monkeypatch, tmp_path) -> None:
    def vacio(session, handle):
        raise LookupError("IG no devolvió datos")

    monkeypatch.setattr(ingest_ig, "fetch_profile", vacio)
    antes = _pool_importar(tmp_path)
    with pytest.raises(LookupError, match="la semilla"):
        ig_seguidos.importar_seguidos(cx, ids["a"], "typo")
    assert _pool_importar(tmp_path) == antes


@pytest.mark.parametrize("status", [401, 403, 429])
def test_importar_semilla_http_de_cookie_quema_y_rota(cx, ids, following_falso, monkeypatch,
                                                      tmp_path, status) -> None:
    fallos = [_http(status)]
    real = ingest_ig.fetch_profile

    def una_vez(session, handle):
        if fallos:
            raise fallos.pop()
        return real(session, handle)

    monkeypatch.setattr(ingest_ig, "fetch_profile", una_vez)
    r = ig_seguidos.importar_seguidos(cx, ids["a"], "pensionmas")
    assert r == {"nuevas": 3, "ya": 0, "total": 4}
    pool = _pool_importar(tmp_path)
    assert pool[0]["quemada_hasta"] and not pool[1]["quemada_hasta"]


def test_importar_semilla_pool_agotado_lanza(cx, ids, following_falso, monkeypatch, tmp_path) -> None:
    def limitado(session, handle):
        raise ingest_ig.IngestRateLimited("429")

    monkeypatch.setattr(ingest_ig, "fetch_profile", limitado)
    with pytest.raises(ingest_ig.IngestRateLimited):
        ig_seguidos.importar_seguidos(cx, ids["a"], "pensionmas")
    assert all(c["quemada_hasta"] for c in _pool_importar(tmp_path))


def test_importar_ya_no_usa_listar_con_pool(cx, ids, following_falso, monkeypatch) -> None:
    def prohibido(*a, **k):
        raise AssertionError("_listar_con_pool quema con cualquier HTTPError")

    monkeypatch.setattr(import_followees, "_listar_con_pool", prohibido)
    assert ig_seguidos.importar_seguidos(cx, ids["a"], "pensionmas")["nuevas"] == 3


# --- final-review I2: tope de cuentas por job + reencolado ---
def _activas(cx, a, n) -> list[str]:
    hs = [f"cuenta.{i:02d}" for i in range(n)]
    for h in hs:
        ig_seguidos.fijar_estado(cx, a, h, "activa")
    return hs


def test_ingerir_respeta_el_tope_y_reporta_pendientes(cx, ids, ig_falso, monkeypatch) -> None:
    monkeypatch.setattr(ig_seguidos, "MAX_CUENTAS_POR_JOB", 3)
    a = ids["a"]
    _activas(cx, a, 5)
    avance = []
    r = ig_seguidos.ingerir(cx, a, progreso=lambda p, m: avance.append((p, m)))
    assert r["cuentas"] == 3 and r["pendientes"] == 2 and r["cortado"] is False
    assert [m for _, m in avance] == ["@cuenta.00", "@cuenta.01", "@cuenta.02"]
    assert [p for p, _ in avance] == [0, 33, 66]  # coherente con el lote, no con las 5


def test_ingerir_procesa_primero_las_mas_viejas(cx, ids, ig_falso, monkeypatch) -> None:
    monkeypatch.setattr(ig_seguidos, "MAX_CUENTAS_POR_JOB", 2)
    a = ids["a"]
    hs = _activas(cx, a, 4)
    sellos = {hs[0]: "2026-10-01 00:00:00", hs[1]: None,
              hs[2]: "2026-09-01 00:00:00", hs[3]: "2026-10-05 00:00:00"}
    for h, t in sellos.items():
        db.update(cx, "brand_ig_cuentas", ig_seguidos._fila(cx, a, h)["id"], scraped_at=t)
    avance = []
    ig_seguidos.ingerir(cx, a, progreso=lambda p, m: avance.append(m))
    assert avance == [f"@{hs[1]}", f"@{hs[2]}"]  # nunca ingerida, luego la más vieja


def test_ingerir_sin_exceso_no_deja_pendientes(cx, ids, ig_falso) -> None:
    ig_seguidos.fijar_estado(cx, ids["a"], "cafe.tacuba", "activa")
    assert ig_seguidos.ingerir(cx, ids["a"])["pendientes"] == 0


def test_tope_por_defecto_es_10() -> None:
    assert ig_seguidos.MAX_CUENTAS_POR_JOB == 10


def test_cuenta_con_error_se_sella_y_no_bloquea_la_cadena(cx, ids, ig_falso, monkeypatch) -> None:
    """Una cuenta que falla en fetch_profile no puede quedarse 'la más vieja' para siempre."""
    monkeypatch.setattr(ig_seguidos, "MAX_CUENTAS_POR_JOB", 1)
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "aa.muerta", "activa")
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    real = ingest_ig._get_json

    def muerta(session, url, params=None):
        if params and params.get("username") == "aa.muerta":
            raise _http(404)
        return real(session, url, params)

    monkeypatch.setattr(ingest_ig, "_get_json", muerta)
    r1 = ig_seguidos.ingerir(cx, a)
    assert r1["pendientes"] == 1 and len(r1["errores"]) == 1
    r2 = ig_seguidos.ingerir(cx, a)
    assert r2["cuentas"] == 1 and r2["assets"] == 4 and r2["pendientes"] == 1


def test_handler_reencola_el_resto_con_los_mismos_parametros(cx, ids, ig_falso, monkeypatch) -> None:
    monkeypatch.setattr(ig_seguidos, "MAX_CUENTAS_POR_JOB", 2)
    a = ids["a"]
    _activas(cx, a, 3)
    jid = jobs.crear(cx, "ig.ingerir", a, {"por_cuenta": 7}, creado_por=None)
    job = dict(db.get(cx, "jobs", jid))
    r = handlers.HANDLERS["ig.ingerir"](cx, job)
    assert r["cuentas"] == 2 and r["pendientes"] == 1
    cola = [j for j in _en_cola_ig(cx) if j["id"] != jid]
    assert len(cola) == 1 and cola[0]["account_id"] == a and r["reencolado"] == cola[0]["id"]
    p = json.loads(cola[0]["payload_json"])
    assert p["por_cuenta"] == 7 and p["desde"] and set(p) == {"por_cuenta", "desde"}


def _en_cola_ig(cx) -> list[dict]:
    return [dict(r) for r in db.rows(
        cx, "SELECT * FROM jobs WHERE estado = 'cola' AND tipo = 'ig.ingerir'")]


def test_handler_no_reencola_si_no_quedan(cx, ids, ig_falso) -> None:
    ig_seguidos.fijar_estado(cx, ids["a"], "cafe.tacuba", "activa")
    handlers.HANDLERS["ig.ingerir"](cx, _job(cx, "ig.ingerir", {"por_cuenta": 5}, ids["a"]))
    assert len(_en_cola_ig(cx)) == 1  # solo el propio job (sigue 'cola': nadie lo tomó)


def test_handler_no_reencola_si_el_pool_se_corto(cx, ids, monkeypatch) -> None:
    monkeypatch.setattr(ig_seguidos, "ingerir", lambda cx, aid, *, por_cuenta, progreso, desde=None:
                        {"cuentas": 1, "assets": 1, "errores": [], "cortado": True,
                         "pendientes": 4})
    handlers.HANDLERS["ig.ingerir"](cx, _job(cx, "ig.ingerir", {"por_cuenta": 5}, ids["a"]))
    assert len(_en_cola_ig(cx)) == 1  # reencolar giraría en vacío contra un pool en reposo


def test_job_reencolado_corre_despues_de_lo_ya_encolado_y_el_carril_ig_sigue(
        cx, ids, ig_falso, monkeypatch) -> None:
    monkeypatch.setattr(ig_seguidos, "MAX_CUENTAS_POR_JOB", 1)
    a, b = ids["a"], ids["b"]
    _activas(cx, a, 2)
    primero = jobs.crear(cx, "ig.ingerir", a, {"por_cuenta": 5})
    otro_no_ig = jobs.crear(cx, "diseno.chat", b, {})
    otro_ig = jobs.crear(cx, "ig.ingerir", b, {"por_cuenta": 5})
    tomado = jobs.tomar(cx, "w1")
    assert tomado["id"] == primero
    handlers.HANDLERS["ig.ingerir"](cx, tomado)       # procesa 1, reencola el resto
    reencolado = max(r["id"] for r in db.rows(cx, "SELECT id FROM jobs"))
    assert reencolado > otro_ig
    jobs.terminar(cx, primero, ok=True)
    orden = []
    while (j := jobs.tomar(cx, "w1")) is not None:
        orden.append(j["id"])
        if j["tipo"] == "ig.ingerir":                   # carril IG: nadie más IG mientras corre
            assert jobs.tomar(cx, "w2") is None
        jobs.terminar(cx, j["id"], ok=True)
    assert orden == [otro_no_ig, otro_ig, reencolado]


def _correr_cadena(cx, a, tope=20) -> list[dict]:
    """Corre jobs ig.ingerir de la marca hasta que no quede ninguno en cola."""
    resultados = []
    while (j := jobs.tomar(cx, "w")) is not None:
        assert len(resultados) < tope, "la cadena de reencolados no termina"
        resultados.append(handlers.HANDLERS["ig.ingerir"](cx, j))
        jobs.terminar(cx, j["id"], ok=True)
    return resultados


def test_cadena_completa_25_cuentas_son_3_jobs_y_termina(cx, ids, ig_falso) -> None:
    a = ids["a"]
    _activas(cx, a, 25)
    jobs.crear(cx, "ig.ingerir", a, {"por_cuenta": 5})
    res = _correr_cadena(cx, a)
    assert [r["cuentas"] for r in res] == [10, 10, 5]
    assert [r["pendientes"] for r in res] == [15, 5, 0]
    assert _en_cola_ig(cx) == []
    # cada cuenta se ingirió exactamente una vez en la cadena
    assert sum(r["cuentas"] for r in res) == 25


def test_cadena_con_cuentas_que_siempre_fallan_termina(cx, ids, ig_falso, monkeypatch) -> None:
    a = ids["a"]
    _activas(cx, a, 25)

    def siempre_falla(session, url, params=None):
        raise _http(500)

    monkeypatch.setattr(ingest_ig, "_get_json", siempre_falla)
    jobs.crear(cx, "ig.ingerir", a, {"por_cuenta": 5})
    res = _correr_cadena(cx, a)
    assert len(res) == 3 and all(r["cuentas"] == 0 for r in res)
    assert sum(len(r["errores"]) for r in res) == 25
    assert _en_cola_ig(cx) == []
