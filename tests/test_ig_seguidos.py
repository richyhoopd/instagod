"""Fuente «Seguidos de IG» (plan 5 del editor v2). Sin red: IG se simula con fixtures."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
from pathlib import Path

import pytest
from PIL import Image

import config
from src import assets, db, import_followees, ingest_ig
from src.assets import biblioteca, ig_seguidos

FIX = Path(__file__).parent / "fixtures" / "assets" / "ig"


@pytest.fixture
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def cuadro_falso(request, monkeypatch):
    """Ninguna prueba rápida llama ffmpeg real (Task 5 define primer_cuadro)."""
    if request.node.get_closest_marker("lento"):
        return

    def falso(video, destino):
        raise AssertionError("ffmpeg real en una prueba rápida")

    monkeypatch.setattr(ig_seguidos, "primer_cuadro", falso, raising=False)


@pytest.fixture
def ids(cx) -> dict[str, int]:
    """Ids reales devueltos por insert (init_db siembra gdlscene=1; no se asume nada)."""
    return {
        "a": db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p",
                       nombre="P", ciudad="CDMX"),
        "b": db.insert(cx, "accounts", slug="daisies", ig_handle="@d",
                       nombre="D", ciudad="CDMX"),
    }


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
def following_falso(monkeypatch):
    llamadas: list[tuple] = []

    def falso(cuenta, limite):
        llamadas.append((cuenta, limite))
        return _following()

    monkeypatch.setattr(import_followees, "_listar_con_pool", falso)
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
    estado = {"get_json": [], "descargas": []}

    def get_json(session, url, params=None):
        estado["get_json"].append(url)
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
    assert r == {"cuentas": 1, "assets": 2, "errores": [], "cortado": False}
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
    assert ig_seguidos.ingerir(cx, a)["assets"] == 2
    antes = _assets(cx, a)
    descargas = len(ig_falso["descargas"])
    r = ig_seguidos.ingerir(cx, a)
    assert r == {"cuentas": 1, "assets": 0, "errores": [], "cortado": False}
    assert _assets(cx, a) == antes
    assert len(ig_falso["descargas"]) == descargas          # post ya ingerido: ni se baja


def test_nombre_de_archivo_sin_datos_de_ig(cx, ids, ig_falso, tmp_path) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    ig_seguidos.ingerir(cx, a)
    raiz = biblioteca.ruta_de("pensionmas", "x").parent.resolve()
    assert str(raiz).startswith(str(tmp_path.resolve()))
    filas = _assets(cx, a)
    assert len(filas) == 2
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
    assert r == {"cuentas": 1, "assets": 0, "errores": [], "cortado": False}
    cuenta = ig_seguidos.listar(cx, a)[0]
    assert cuenta["privada"] == 1 and cuenta["notas"] == "perfil privado: no se puede ingerir"
    assert not any("/feed/user/" in u for u in ig_falso["get_json"])
    assert _assets(cx, a) == []


def test_ingerir_sin_cuentas_activas_no_toca_ig(cx, ids, ig_falso) -> None:
    assert ig_seguidos.ingerir(cx, ids["a"]) == {"cuentas": 0, "assets": 0, "errores": [],
                                                 "cortado": False}
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
    assert r["cuentas"] == 1 and r["assets"] == 2 and r["cortado"] is False
    assert [e.split(":")[0] for e in r["errores"]] == ["@red", "@rota", "@sin.id"]
    assert r["errores"][1].startswith("@rota: LookupError")
    assert r["errores"][2].startswith("@sin.id: KeyError")
    assert [m for _, m in avance] == ["@cafe.tacuba", "@red", "@rota", "@sin.id"]
    assert [p for p, _ in avance] == [0, 25, 50, 75]


def test_rate_limit_se_propaga(cx, ids, ig_falso, monkeypatch) -> None:
    def limitado(session, url, params=None):
        raise ingest_ig.IngestRateLimited("HTTP 429")

    monkeypatch.setattr(ingest_ig, "_get_json", limitado)
    ig_seguidos.fijar_estado(cx, ids["a"], "cafe.tacuba", "activa")
    with pytest.raises(ingest_ig.IngestRateLimited):
        ig_seguidos.ingerir(cx, ids["a"])


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
