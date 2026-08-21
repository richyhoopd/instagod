"""Fuentes de contenido por marca (`brand_sources`): CRUD, catálogo, cascada."""
from __future__ import annotations

import pytest

from src import db, fuentes
from src import marcas as marcas_mod


@pytest.fixture()
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    db.insert(c, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    yield c
    c.close()


# ---------- crear: catálogo de providers ----------

def test_crear_provider_no_catalogado_revienta(cx) -> None:
    with pytest.raises(ValueError, match="provider"):
        fuentes.crear(cx, 2, "imagen", "youtube")


def test_crear_provider_de_otro_kind_revienta(cx) -> None:
    with pytest.raises(ValueError, match="provider"):
        fuentes.crear(cx, 2, "imagen", "rss")
    with pytest.raises(ValueError, match="provider"):
        fuentes.crear(cx, 2, "info", "pexels")


def test_crear_providers_sin_config_obligatoria_aceptan_config_opcional(cx) -> None:
    sid = fuentes.crear(cx, 2, "imagen", "pexels")
    assert sid > 0
    sid2 = fuentes.crear(cx, 2, "imagen", "banco", {"cualquier": "cosa"})
    assert sid2 > 0


# ---------- crear: validación de config por provider ----------

def test_crear_ig_accounts_valida_config(cx) -> None:
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "imagen", "ig_accounts", {})  # sin cuentas
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "imagen", "ig_accounts", {"cuentas": []})
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "imagen", "ig_accounts", {"cuentas": ["sin_arroba"]})
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "imagen", "ig_accounts",
                      {"cuentas": ["@x"], "max_por_cuenta": 51})
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "imagen", "ig_accounts",
                      {"cuentas": ["@x"], "cada_horas": 5})
    sid = fuentes.crear(cx, 2, "imagen", "ig_accounts",
                        {"cuentas": ["@x", "@y"], "max_por_cuenta": 10, "cada_horas": 6})
    assert sid > 0


def test_crear_ig_accounts_rechaza_cuentas_con_traversal(cx) -> None:
    """H1: un `startswith('@')` a secas dejaba pasar handles tipo path-traversal
    que luego se usan para construir el nombre del archivo destino."""
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "imagen", "ig_accounts", {"cuentas": ["@../../evil"]})
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "imagen", "ig_accounts", {"cuentas": ["@x/../../y"]})
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "imagen", "ig_accounts", {"cuentas": ["@" + "x" * 31]})  # >30 chars


def test_crear_rss_valida_config(cx) -> None:
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "info", "rss", {})  # sin urls
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "info", "rss", {"urls": []})
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "info", "rss", {"urls": ["no-es-url"]})
    sid = fuentes.crear(cx, 2, "info", "rss", {"urls": ["https://x.com/feed"]})
    assert sid > 0


def test_crear_rss_valida_cada_horas(cx) -> None:
    """H2: cada_horas ausente = ok (default lo pone el scheduler); presente
    debe ser int >= 6."""
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "info", "rss", {"urls": ["https://x.com/feed"], "cada_horas": "abc"})
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "info", "rss", {"urls": ["https://x.com/feed"], "cada_horas": -5})
    sid = fuentes.crear(cx, 2, "info", "rss", {"urls": ["https://x.com/feed"], "cada_horas": 12})
    assert sid > 0


def test_crear_newsapi_valida_config(cx) -> None:
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "info", "newsapi", {})  # sin query
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "info", "newsapi", {"query": "   "})
    sid = fuentes.crear(cx, 2, "info", "newsapi",
                        {"query": "pensiones", "idioma": "es", "pais": "mx"})
    assert sid > 0


def test_crear_newsapi_valida_cada_horas(cx) -> None:
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "info", "newsapi", {"query": "x", "cada_horas": "abc"})
    with pytest.raises(ValueError, match="config"):
        fuentes.crear(cx, 2, "info", "newsapi", {"query": "x", "cada_horas": -5})
    sid = fuentes.crear(cx, 2, "info", "newsapi", {"query": "x", "cada_horas": 6})
    assert sid > 0


# ---------- listar / actualizar / borrar ----------

def test_crear_asigna_orden_incremental_y_listar_devuelve_config_parseado(cx) -> None:
    s1 = fuentes.crear(cx, 2, "imagen", "banco")
    s2 = fuentes.crear(cx, 2, "imagen", "pexels")
    filas = fuentes.listar(cx, 2, kind="imagen")
    assert [f["id"] for f in filas] == [s1, s2]
    assert [f["orden"] for f in filas] == [0, 1]

    fuentes.crear(cx, 2, "info", "newsapi", {"query": "x"})
    filas_info = fuentes.listar(cx, 2, kind="info")
    assert filas_info[0]["config"] == {"query": "x"}

    todas = fuentes.listar(cx, 2)
    assert len(todas) == 3


def test_actualizar_config_y_activa(cx) -> None:
    sid = fuentes.crear(cx, 2, "info", "newsapi", {"query": "pensiones"})
    fuentes.actualizar(cx, sid, config={"query": "pensiones mx"}, activa=False)
    fila = db.get(cx, "brand_sources", sid)
    assert fila["activa"] == 0
    import json
    assert json.loads(fila["config_json"]) == {"query": "pensiones mx"}


def test_actualizar_con_config_invalida_revienta(cx) -> None:
    sid = fuentes.crear(cx, 2, "info", "rss", {"urls": ["https://x.com/feed"]})
    with pytest.raises(ValueError, match="config"):
        fuentes.actualizar(cx, sid, config={})  # rss sin urls


def test_actualizar_de_fuente_inexistente_revienta(cx) -> None:
    with pytest.raises(ValueError, match="fuente"):
        fuentes.actualizar(cx, 999999, config={"query": "x"})
    with pytest.raises(ValueError, match="fuente"):
        fuentes.actualizar(cx, 999999, activa=False)


def test_actualizar_edicion_valida_persiste(cx) -> None:
    sid = fuentes.crear(cx, 2, "info", "rss", {"urls": ["https://x.com/feed"]})
    fuentes.actualizar(cx, sid, config={"urls": ["https://y.com/feed", "https://z.com/feed"]})
    fila = db.get(cx, "brand_sources", sid)
    import json
    assert json.loads(fila["config_json"]) == {"urls": ["https://y.com/feed", "https://z.com/feed"]}


def test_borrar(cx) -> None:
    sid = fuentes.crear(cx, 2, "imagen", "pexels")
    fuentes.borrar(cx, sid)
    assert db.get(cx, "brand_sources", sid) is None


# ---------- reordenar ----------

def test_reordenar_aplica_nuevo_orden(cx) -> None:
    s1 = fuentes.crear(cx, 2, "imagen", "banco")
    s2 = fuentes.crear(cx, 2, "imagen", "pexels")
    s3 = fuentes.crear(cx, 2, "imagen", "pinterest")
    fuentes.reordenar(cx, 2, [s3, s1, s2])
    filas = fuentes.listar(cx, 2, kind="imagen")
    assert [f["id"] for f in filas] == [s3, s1, s2]


def test_reordenar_con_id_ajeno_revienta(cx) -> None:
    s1 = fuentes.crear(cx, 2, "imagen", "banco")
    s2 = fuentes.crear(cx, 2, "imagen", "pexels")
    otra_id = db.insert(cx, "accounts", slug="otra", ig_handle="@o", nombre="O", ciudad="X")
    s_otra = fuentes.crear(cx, otra_id, "imagen", "banco")
    with pytest.raises(ValueError, match="ids"):
        fuentes.reordenar(cx, 2, [s1, s_otra])
    with pytest.raises(ValueError, match="ids"):
        fuentes.reordenar(cx, 2, [s1])  # falta s2


# ---------- orden_imagen ----------

def test_orden_imagen_usa_filas_activas_en_orden(cx) -> None:
    m = marcas_mod.cargar(cx, "pensionmas")
    fuentes.crear(cx, m.id, "imagen", "pinterest")
    inactivo = fuentes.crear(cx, m.id, "imagen", "banco")
    fuentes.crear(cx, m.id, "imagen", "pexels")
    fuentes.actualizar(cx, inactivo, activa=False)
    assert fuentes.orden_imagen(cx, m) == ["pinterest", "pexels"]


def test_orden_imagen_sin_filas_cae_a_fuentes_legacy_de_la_marca(cx) -> None:
    m = marcas_mod.cargar(cx, "pensionmas")
    assert fuentes.orden_imagen(cx, m) == m.fuentes
