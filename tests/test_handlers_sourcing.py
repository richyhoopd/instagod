"""Handlers de sourcing (rss/newsapi/ig_scrape) y preview de presets como jobs."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src import db, fuentes, jobs, topics
from src.jobs import handlers, worker


@pytest.fixture()
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def _job(cx, tipo, account_id, payload):
    jid = jobs.crear(cx, tipo, account_id, payload)
    return db.get(cx, "jobs", jid)


# ---------- sourcing.rss_fetch ----------

def test_rss_fetch_lee_urls_de_la_fuente_y_guarda_topics(cx, monkeypatch) -> None:
    sid = fuentes.crear(cx, 1, "info", "rss", {"urls": ["https://a.com/f.xml"]})

    llamadas = []

    def _fake_fetch_rss(url, **kw):
        llamadas.append(url)
        return [{"titulo": "T1", "resumen": "r", "url": "https://a.com/1",
                 "publicado_en": None}]

    monkeypatch.setattr(handlers.topics, "fetch_rss", _fake_fetch_rss)
    job = _job(cx, "sourcing.rss_fetch", 1, {"source_id": sid})

    resultado = handlers.sourcing_rss_fetch(cx, job)

    assert llamadas == ["https://a.com/f.xml"]
    assert resultado["nuevos"] == 1
    assert len(topics.listar(cx, 1)) == 1
    fila = db.get(cx, "brand_sources", sid)
    assert fila["ultimo_run"]
    assert fila["ultimo_error"] is None


def test_rss_fetch_fuente_de_otra_cuenta_revienta(cx) -> None:
    otra_id = db.insert(cx, "accounts", slug="otra", ig_handle="@o", nombre="O", ciudad="CDMX")
    sid = fuentes.crear(cx, otra_id, "info", "rss", {"urls": ["https://a.com/f.xml"]})
    job = _job(cx, "sourcing.rss_fetch", 1, {"source_id": sid})  # job es de account_id=1

    with pytest.raises(ValueError):
        handlers.sourcing_rss_fetch(cx, job)


def test_rss_fetch_fuente_inexistente_revienta(cx) -> None:
    job = _job(cx, "sourcing.rss_fetch", 1, {"source_id": 999})
    with pytest.raises(ValueError):
        handlers.sourcing_rss_fetch(cx, job)


# ---------- sourcing.newsapi_fetch ----------

def test_newsapi_fetch_sin_key_termina_el_job_en_error_accionable(cx, monkeypatch) -> None:
    sid = fuentes.crear(cx, 1, "info", "newsapi", {"query": "cafeterías"})
    monkeypatch.setattr(handlers.config, "account_creds", lambda slug: {"NEWSAPI_KEY": None})
    job = _job(cx, "sourcing.newsapi_fetch", 1, {"source_id": sid})

    worker._despachar(cx, job)

    fila = db.get(cx, "jobs", job["id"])
    assert fila["estado"] == "error"
    assert "NEWSAPI_KEY" in json.loads(fila["resultado_json"])["error"]


def test_newsapi_fetch_con_key_guarda_topics(cx, monkeypatch) -> None:
    sid = fuentes.crear(cx, 1, "info", "newsapi", {"query": "cafeterías", "idioma": "es"})
    monkeypatch.setattr(handlers.config, "account_creds",
                        lambda slug: {"NEWSAPI_KEY": "clave-123"})

    capturado = {}

    def _fake_fetch_newsapi(query, key, **kw):
        capturado["query"] = query
        capturado["key"] = key
        capturado["idioma"] = kw.get("idioma")
        capturado["estricto"] = kw.get("estricto")
        return [{"titulo": "N1", "resumen": "r", "url": "https://n.com/1",
                 "publicado_en": None}]

    monkeypatch.setattr(handlers.topics, "fetch_newsapi", _fake_fetch_newsapi)
    job = _job(cx, "sourcing.newsapi_fetch", 1, {"source_id": sid})

    resultado = handlers.sourcing_newsapi_fetch(cx, job)

    assert capturado["query"] == "cafeterías"
    assert capturado["key"] == "clave-123"
    assert capturado["idioma"] == "es"
    assert capturado["estricto"] is True  # nunca 'best-effort' silencioso: si falla, se sabe
    assert resultado["nuevos"] == 1
    assert len(topics.listar(cx, 1)) == 1


def test_newsapi_fetch_error_marca_ultimo_error_y_termina_job_en_error(cx, monkeypatch) -> None:
    sid = fuentes.crear(cx, 1, "info", "newsapi", {"query": "cafeterías"})
    monkeypatch.setattr(handlers.config, "account_creds",
                        lambda slug: {"NEWSAPI_KEY": "clave-999"})

    def _fake_fetch_newsapi(query, key, **kw):
        assert kw.get("estricto") is True
        raise RuntimeError("newsapi HTTP 500")

    monkeypatch.setattr(handlers.topics, "fetch_newsapi", _fake_fetch_newsapi)
    job = _job(cx, "sourcing.newsapi_fetch", 1, {"source_id": sid})

    worker._despachar(cx, job)

    fila_job = db.get(cx, "jobs", job["id"])
    assert fila_job["estado"] == "error"
    fila_fuente = db.get(cx, "brand_sources", sid)
    assert fila_fuente["ultimo_error"] == "newsapi HTTP 500"
    assert "clave-999" not in (fila_fuente["ultimo_error"] or "")


def test_newsapi_fetch_sin_key_sella_ultimo_run_y_no_re_encola_de_inmediato(cx, monkeypatch) -> None:
    """H3: antes, el ValueError("Falta NEWSAPI_KEY") reventaba ANTES de tocar
    brand_sources, así que la fuente seguía "vencida" y el siguiente
    `encolar_fuentes_vencidas` la re-encolaba de inmediato — tormenta de jobs."""
    sid = fuentes.crear(cx, 1, "info", "newsapi", {"query": "cafeterías"})
    monkeypatch.setattr(handlers.config, "account_creds", lambda slug: {"NEWSAPI_KEY": None})
    job = _job(cx, "sourcing.newsapi_fetch", 1, {"source_id": sid})

    worker._despachar(cx, job)

    fila_job = db.get(cx, "jobs", job["id"])
    assert fila_job["estado"] == "error"
    fila_fuente = db.get(cx, "brand_sources", sid)
    assert fila_fuente["ultimo_run"] is not None

    creados = worker.encolar_fuentes_vencidas(cx)
    assert creados == 0


def test_newsapi_fetch_finally_no_enmascara_excepcion_si_falla_el_sellado(cx, monkeypatch) -> None:
    """Re-review: si `db.update` del `finally` revienta (ej. borraron la
    fuente a mitad del job), NO debe reemplazar/enmascarar la excepción
    original que se estaba propagando (aquí, el ValueError de la key
    faltante) — el `finally` la traga y solo avisa."""
    sid = fuentes.crear(cx, 1, "info", "newsapi", {"query": "cafeterías"})
    monkeypatch.setattr(handlers.config, "account_creds", lambda slug: {"NEWSAPI_KEY": None})

    def _update_revienta(cx_, tabla, sid_, **campos):
        raise sqlite3.OperationalError("no such row")

    monkeypatch.setattr(handlers.db, "update", _update_revienta)
    job = _job(cx, "sourcing.newsapi_fetch", 1, {"source_id": sid})

    with pytest.raises(ValueError, match="Falta NEWSAPI_KEY"):
        handlers.sourcing_newsapi_fetch(cx, job)


def test_rss_fetch_finally_no_revienta_si_falla_el_sellado(cx, monkeypatch) -> None:
    sid = fuentes.crear(cx, 1, "info", "rss", {"urls": ["https://a.com/f.xml"]})
    monkeypatch.setattr(handlers.topics, "fetch_rss", lambda url, **kw: [])

    def _update_revienta(cx_, tabla, sid_, **campos):
        raise sqlite3.OperationalError("no such row")

    monkeypatch.setattr(handlers.db, "update", _update_revienta)
    job = _job(cx, "sourcing.rss_fetch", 1, {"source_id": sid})

    resultado = handlers.sourcing_rss_fetch(cx, job)  # no debe lanzar
    assert resultado == {"nuevos": 0}


# ---------- sourcing.ig_scrape ----------

class _FakeSession:
    pass


def test_ig_scrape_descarga_fotos_de_cada_cuenta(cx, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(handlers.config, "BASE_DIR", tmp_path)
    sid = fuentes.crear(cx, 1, "imagen", "ig_accounts",
                        {"cuentas": ["@banda1"], "max_por_cuenta": 2})

    monkeypatch.setattr(handlers.ingest_ig, "get_session", lambda: _FakeSession())
    monkeypatch.setattr(handlers.ingest_ig, "fetch_profile",
                        lambda session, handle: {"id": "123", "is_private": False})
    monkeypatch.setattr(handlers.ingest_ig, "fetch_posts",
                        lambda session, user_id, count: [
                            {"code": "abc", "media_type": 1},
                            {"code": "def", "media_type": 1},
                        ])
    monkeypatch.setattr(handlers.ingest_ig, "_image_urls",
                        lambda item: [(0, f"https://img/{item['code']}.jpg")])

    sleeps = []
    monkeypatch.setattr(handlers.ingest_ig, "_sleep", lambda: sleeps.append(1))

    descargas = []

    def _fake_download(session, url, dest):
        descargas.append(dest)
        dest.write_bytes(b"jpg")
        return True

    monkeypatch.setattr(handlers.ingest_ig, "_download", _fake_download)

    job = _job(cx, "sourcing.ig_scrape", 1, {"source_id": sid})
    resultado = handlers.sourcing_ig_scrape(cx, job)

    assert resultado["bajadas"] == 2
    assert len(descargas) == 2
    for p in descargas:
        assert p.parent == tmp_path / "data" / "brands" / "gdlscene" / "fotos"
        assert p.exists()
    assert sleeps  # H6b: se pausó entre el request de perfil y el de posts


def test_ig_scrape_respeta_max_por_cuenta(cx, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(handlers.config, "BASE_DIR", tmp_path)
    sid = fuentes.crear(cx, 1, "imagen", "ig_accounts",
                        {"cuentas": ["@banda1"], "max_por_cuenta": 1})
    monkeypatch.setattr(handlers.ingest_ig, "get_session", lambda: _FakeSession())
    monkeypatch.setattr(handlers.ingest_ig, "fetch_profile",
                        lambda session, handle: {"id": "1", "is_private": False})
    monkeypatch.setattr(handlers.ingest_ig, "fetch_posts",
                        lambda session, user_id, count: [
                            {"code": "a"}, {"code": "b"}, {"code": "c"}])
    monkeypatch.setattr(handlers.ingest_ig, "_image_urls",
                        lambda item: [(0, f"https://img/{item['code']}.jpg")])
    monkeypatch.setattr(handlers.ingest_ig, "_download",
                        lambda session, url, dest: dest.write_bytes(b"x") or True)
    monkeypatch.setattr(handlers.ingest_ig, "_sleep", lambda: None)

    job = _job(cx, "sourcing.ig_scrape", 1, {"source_id": sid})
    resultado = handlers.sourcing_ig_scrape(cx, job)
    assert resultado["bajadas"] == 1


def test_ig_scrape_code_malicioso_no_escapa_la_carpeta(cx, monkeypatch, tmp_path) -> None:
    """H1: un `code` de post con path-traversal ("../../x") no debe terminar
    escribiendo un archivo fuera de data/brands/<slug>/fotos — el nombre se
    sanea y, de todos modos, se verifica contención antes de escribir."""
    monkeypatch.setattr(handlers.config, "BASE_DIR", tmp_path)
    sid = fuentes.crear(cx, 1, "imagen", "ig_accounts",
                        {"cuentas": ["@banda1"], "max_por_cuenta": 2})
    monkeypatch.setattr(handlers.ingest_ig, "get_session", lambda: _FakeSession())
    monkeypatch.setattr(handlers.ingest_ig, "fetch_profile",
                        lambda session, handle: {"id": "1", "is_private": False})
    monkeypatch.setattr(handlers.ingest_ig, "fetch_posts",
                        lambda session, user_id, count: [{"code": "../../evil"}])
    monkeypatch.setattr(handlers.ingest_ig, "_image_urls",
                        lambda item: [(0, "https://img/x.jpg")])
    monkeypatch.setattr(handlers.ingest_ig, "_sleep", lambda: None)

    descargas = []

    def _fake_download(session, url, dest):
        descargas.append(dest)
        dest.write_bytes(b"jpg")
        return True

    monkeypatch.setattr(handlers.ingest_ig, "_download", _fake_download)

    job = _job(cx, "sourcing.ig_scrape", 1, {"source_id": sid})
    resultado = handlers.sourcing_ig_scrape(cx, job)

    dest_dir = tmp_path / "data" / "brands" / "gdlscene" / "fotos"
    fuera = [p for p in dest_dir.parent.parent.rglob("*.jpg") if p.parent != dest_dir]
    assert fuera == []  # nunca se escribió fuera de fotos/
    for p in descargas:
        assert p.parent == dest_dir
        assert ".." not in p.name


def test_ig_scrape_sesion_no_sana_revienta_sin_loop(cx, monkeypatch) -> None:
    sid = fuentes.crear(cx, 1, "imagen", "ig_accounts", {"cuentas": ["@banda1"]})

    def _revienta():
        raise RuntimeError("Faltan cuentas scraper.")
    monkeypatch.setattr(handlers.ingest_ig, "get_session", _revienta)

    job = _job(cx, "sourcing.ig_scrape", 1, {"source_id": sid})
    with pytest.raises(RuntimeError, match="Faltan cuentas"):
        handlers.sourcing_ig_scrape(cx, job)


def test_ig_scrape_todas_las_cuentas_fallan_termina_el_job_en_error(cx, monkeypatch, tmp_path) -> None:
    """H6a: si NINGUNA cuenta produjo fotos y hubo errores, el job debe
    reventar (no un "ok" con 0 fotos que esconde que el scrape falló)."""
    monkeypatch.setattr(handlers.config, "BASE_DIR", tmp_path)
    sid = fuentes.crear(cx, 1, "imagen", "ig_accounts", {"cuentas": ["@priv"]})
    monkeypatch.setattr(handlers.ingest_ig, "get_session", lambda: _FakeSession())
    monkeypatch.setattr(handlers.ingest_ig, "fetch_profile",
                        lambda session, handle: {"id": "1", "is_private": True})

    job = _job(cx, "sourcing.ig_scrape", 1, {"source_id": sid})
    with pytest.raises(RuntimeError, match="scrape sin resultados"):
        handlers.sourcing_ig_scrape(cx, job)

    fila = db.get(cx, "brand_sources", sid)
    assert "priv" in (fila["ultimo_error"] or "")
    assert fila["ultimo_run"] is not None  # ultimo_run se sella pese al error


def test_ig_scrape_cuenta_privada_entre_varias_no_revienta_si_otra_si_baja(cx, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(handlers.config, "BASE_DIR", tmp_path)
    sid = fuentes.crear(cx, 1, "imagen", "ig_accounts", {"cuentas": ["@priv", "@ok"]})
    monkeypatch.setattr(handlers.ingest_ig, "get_session", lambda: _FakeSession())
    monkeypatch.setattr(handlers.ingest_ig, "fetch_profile",
                        lambda session, handle: {"id": "1", "is_private": handle == "priv"})
    monkeypatch.setattr(handlers.ingest_ig, "fetch_posts",
                        lambda session, user_id, count: [{"code": "abc"}])
    monkeypatch.setattr(handlers.ingest_ig, "_image_urls",
                        lambda item: [(0, "https://img/x.jpg")])
    monkeypatch.setattr(handlers.ingest_ig, "_sleep", lambda: None)
    monkeypatch.setattr(handlers.ingest_ig, "_download",
                        lambda session, url, dest: dest.write_bytes(b"x") or True)

    job = _job(cx, "sourcing.ig_scrape", 1, {"source_id": sid})
    resultado = handlers.sourcing_ig_scrape(cx, job)
    assert resultado["bajadas"] == 1  # @priv falló pero @ok sí bajó algo
    fila = db.get(cx, "brand_sources", sid)
    assert "priv" in (fila["ultimo_error"] or "")


# ---------- preset.preview ----------

def test_preset_preview_renderiza_y_copia_el_png(cx, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(handlers.config, "BASE_DIR", tmp_path)

    render_llamadas = []

    def _fake_render_card(template_file, ctx, **kw):
        render_llamadas.append((template_file, kw.get("prefix")))
        p = tmp_path / "render.png"
        p.write_bytes(b"png-data")
        return p

    monkeypatch.setattr(handlers.compose, "render_card", _fake_render_card)

    job = _job(cx, "preset.preview", 1, {"nombre": "tiktok_bold", "texto": "Hola mundo"})
    resultado = handlers.preset_preview(cx, job)

    assert render_llamadas[0][0] == "slide.html"
    assert "tiktok_bold" in render_llamadas[0][1]
    destino = tmp_path / "data" / "previews" / "gdlscene" / "tiktok_bold.png"
    assert resultado["path"] == str(destino)
    assert destino.exists()
    assert destino.read_bytes() == b"png-data"


def test_preset_preview_preset_inexistente_revienta(cx) -> None:
    job = _job(cx, "preset.preview", 1, {"nombre": "no-existe", "texto": "x"})
    with pytest.raises(ValueError):
        handlers.preset_preview(cx, job)


# ---------- HANDLERS dict ----------

def test_handlers_registrados() -> None:
    assert handlers.HANDLERS["sourcing.rss_fetch"] is handlers.sourcing_rss_fetch
    assert handlers.HANDLERS["sourcing.newsapi_fetch"] is handlers.sourcing_newsapi_fetch
    assert handlers.HANDLERS["sourcing.ig_scrape"] is handlers.sourcing_ig_scrape
    assert handlers.HANDLERS["preset.preview"] is handlers.preset_preview


# ---------- worker.encolar_fuentes_vencidas ----------

def test_encolar_fuentes_vencidas_crea_job_si_nunca_corrio(cx) -> None:
    sid = fuentes.crear(cx, 1, "info", "rss", {"urls": ["https://a.com/f.xml"]})
    creados = worker.encolar_fuentes_vencidas(cx)
    assert creados == 1
    pendientes = db.rows(cx, "SELECT * FROM jobs WHERE tipo = 'sourcing.rss_fetch'")
    assert len(pendientes) == 1
    payload = json.loads(pendientes[0]["payload_json"])
    assert payload["source_id"] == sid


def test_encolar_fuentes_vencidas_no_duplica_si_ya_hay_job_en_cola(cx) -> None:
    sid = fuentes.crear(cx, 1, "info", "rss", {"urls": ["https://a.com/f.xml"]})
    worker.encolar_fuentes_vencidas(cx)
    creados2 = worker.encolar_fuentes_vencidas(cx)
    assert creados2 == 0
    pendientes = db.rows(cx, "SELECT * FROM jobs WHERE tipo = 'sourcing.rss_fetch'")
    assert len(pendientes) == 1
    assert sid  # solo para linter, sid usado arriba


def test_encolar_fuentes_vencidas_no_colisiona_por_prefijo_numerico(cx) -> None:
    """G3: dedup debe comparar `source_id` como valor, no por substring del
    payload — sin esto, un job pendiente de source_id=10 "bloqueaba" (por el
    match `%"source_id": 1%`) a una fuente distinta con id=1."""
    sid1 = fuentes.crear(cx, 1, "info", "rss", {"urls": ["https://a.com/f.xml"]})
    assert sid1 == 1  # primera fuente creada en un cx limpio
    jobs.crear(cx, "sourcing.rss_fetch", 1, {"source_id": 10})  # job de OTRA fuente (id=10)

    creados = worker.encolar_fuentes_vencidas(cx)

    assert creados == 1  # sid1 se encoló pese al job pendiente de source_id=10
    ids_encolados = {
        json.loads(j["payload_json"])["source_id"]
        for j in db.rows(cx, "SELECT payload_json FROM jobs WHERE tipo = 'sourcing.rss_fetch'")
    }
    assert ids_encolados == {1, 10}


def test_encolar_fuentes_vencidas_no_encola_si_no_ha_pasado_cada_horas(cx) -> None:
    fuentes.crear(cx, 1, "info", "newsapi", {"query": "x", "cada_horas": 24})
    reciente = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    sid = db.rows(cx, "SELECT id FROM brand_sources")[0]["id"]
    db.update(cx, "brand_sources", sid, ultimo_run=reciente)

    creados = worker.encolar_fuentes_vencidas(cx)
    assert creados == 0


def test_encolar_fuentes_vencidas_encola_si_paso_cada_horas(cx) -> None:
    fuentes.crear(cx, 1, "info", "newsapi", {"query": "x", "cada_horas": 24})
    viejo = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")
    sid = db.rows(cx, "SELECT id FROM brand_sources")[0]["id"]
    db.update(cx, "brand_sources", sid, ultimo_run=viejo)

    creados = worker.encolar_fuentes_vencidas(cx)
    assert creados == 1
    pendientes = db.rows(cx, "SELECT * FROM jobs WHERE tipo = 'sourcing.newsapi_fetch'")
    assert len(pendientes) == 1


def test_encolar_fuentes_vencidas_ignora_fuentes_de_imagen(cx) -> None:
    fuentes.crear(cx, 1, "imagen", "ig_accounts", {"cuentas": ["@x"]})
    creados = worker.encolar_fuentes_vencidas(cx)
    assert creados == 0


def test_encolar_fuentes_vencidas_ignora_fuentes_inactivas(cx) -> None:
    sid = fuentes.crear(cx, 1, "info", "rss", {"urls": ["https://a.com/f.xml"]})
    fuentes.actualizar(cx, sid, activa=False)
    creados = worker.encolar_fuentes_vencidas(cx)
    assert creados == 0


def test_encolar_fuentes_vencidas_cada_horas_invalido_no_tumba_el_loop(cx) -> None:
    """H2: una fila con `cada_horas` no numérico (ej. tocada a mano en la DB,
    de antes de que `validar_config` lo exigiera int) nunca debe reventar
    `encolar_fuentes_vencidas` — cae al default de 24h."""
    sid = fuentes.crear(cx, 1, "info", "rss", {"urls": ["https://a.com/f.xml"]})
    # bypass de validar_config: escribimos config_json crudo directo en la fila.
    db.update(cx, "brand_sources", sid,
             config_json=json.dumps({"urls": ["https://a.com/f.xml"], "cada_horas": "abc"}))

    creados = worker.encolar_fuentes_vencidas(cx)  # no debe lanzar
    assert creados == 1  # nunca corrió -> vencida con el default de 24h


def test_encolar_fuentes_vencidas_cada_horas_legacy_cero_no_queda_siempre_vencida(cx) -> None:
    """Re-review: una fila legacy con cada_horas=0/negativo (de antes de que
    validar_config exigiera >= 6) haría que timedelta(hours=cada_horas) fuera
    ~0 — cualquier ultimo_run, por reciente que sea, ya contaría como
    vencido en el siguiente tick (tormenta de jobs). `max(6, ...)` pone un
    piso de 6h aunque el dato guardado sea 0 o negativo."""
    sid = fuentes.crear(cx, 1, "info", "rss", {"urls": ["https://a.com/f.xml"]})
    db.update(cx, "brand_sources", sid,
             config_json=json.dumps({"urls": ["https://a.com/f.xml"], "cada_horas": 0}))
    reciente = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    db.update(cx, "brand_sources", sid, ultimo_run=reciente)

    creados = worker.encolar_fuentes_vencidas(cx)
    assert creados == 0  # 1h < piso de 6h -> no vencida todavía

    viejo = (datetime.now(timezone.utc) - timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
    db.update(cx, "brand_sources", sid, ultimo_run=viejo)
    creados = worker.encolar_fuentes_vencidas(cx)
    assert creados == 1  # 7h > piso de 6h -> ahora sí vencida
