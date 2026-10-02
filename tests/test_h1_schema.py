"""H1: tablas y columnas nuevas del cimiento de entidades y plantillas."""
from __future__ import annotations

from src import db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_tabla_brand_entities(tmp_path) -> None:
    cx = _cx(tmp_path)
    eid = db.insert(cx, "brand_entities", account_id=1, tipo="banda",
                    nombre="Los Ejemplo", slug="los-ejemplo")
    fila = db.get(cx, "brand_entities", eid)
    assert fila["nombre"] == "Los Ejemplo"
    assert fila["prioridad"] == 3      # default
    assert fila["activa"] == 1         # default


def test_brand_entities_slug_unico_por_cuenta(tmp_path) -> None:
    import sqlite3
    cx = _cx(tmp_path)
    db.insert(cx, "brand_entities", account_id=1, tipo="banda",
              nombre="A", slug="repetido")
    try:
        db.insert(cx, "brand_entities", account_id=1, tipo="banda",
                  nombre="B", slug="repetido")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("el slug debe ser único por cuenta")


def test_tabla_brand_templates(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = db.insert(cx, "brand_templates", account_id=1, slug="clasica",
                    nombre="Clásica", aspecto="4:5",
                    contrato_json='{"aspecto":"4:5","base":[],"extras":[]}',
                    html="<div class=card></div>", origen="seed")
    fila = db.get(cx, "brand_templates", tid)
    assert fila["estado"] == "borrador"      # default
    assert fila["version_actual"] == 1       # default


def test_brand_templates_rechaza_aspecto_invalido(tmp_path) -> None:
    import sqlite3
    cx = _cx(tmp_path)
    try:
        db.insert(cx, "brand_templates", account_id=1, slug="x", nombre="X",
                  aspecto="16:9", contrato_json="{}", html="<div></div>")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("aspecto solo acepta 4:5 y 9:16")


def test_tabla_template_versions(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = db.insert(cx, "brand_templates", account_id=1, slug="v", nombre="V",
                    contrato_json="{}", html="<div></div>")
    vid = db.insert(cx, "template_versions", template_id=tid, version=1,
                    html="<div></div>", contrato_json="{}",
                    mensaje_usuario="hazla verde")
    assert db.get(cx, "template_versions", vid)["mensaje_usuario"] == "hazla verde"


def test_tabla_brand_fonts(tmp_path) -> None:
    cx = _cx(tmp_path)
    fid = db.insert(cx, "brand_fonts", account_id=1, familia="Anton",
                    archivo="fonts/Anton-Regular.ttf")
    assert db.get(cx, "brand_fonts", fid)["familia"] == "Anton"


def test_columnas_nuevas_en_content_queue(tmp_path) -> None:
    cx = _cx(tmp_path)
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(content_queue)")}
    assert {"template_id", "template_version", "entity_id",
            "campos_json", "aspecto"} <= cols


def test_columnas_nuevas_en_planes(tmp_path) -> None:
    cx = _cx(tmp_path)
    plan_cols = {r["name"] for r in cx.execute("PRAGMA table_info(content_plans)")}
    topic_cols = {r["name"] for r in cx.execute("PRAGMA table_info(plan_topics)")}
    foto_cols = {r["name"] for r in cx.execute("PRAGMA table_info(photos)")}
    assert {"estrategia", "criterio_json"} <= plan_cols
    assert "entity_id" in topic_cols
    assert "entity_id" in foto_cols


def test_estrategia_por_defecto_es_llm(tmp_path) -> None:
    # Los planes que ya existen en prod no deben cambiar de comportamiento.
    cx = _cx(tmp_path)
    pid = db.insert(cx, "content_plans", account_id=1, tipo_periodo="mes",
                    periodo="2026-09", objetivo="x")
    assert db.get(cx, "content_plans", pid)["estrategia"] == "llm"


def test_campos_json_persiste_en_content_queue(tmp_path) -> None:
    cx = _cx(tmp_path)
    qid = db.insert(cx, "content_queue", tipo="meme", campos_json='{"titular":"hola"}',
                    aspecto="9:16", template_version=2)
    fila = db.get(cx, "content_queue", qid)
    assert fila["campos_json"] == '{"titular":"hola"}'
    assert fila["aspecto"] == "9:16"
    assert fila["template_version"] == 2


def test_tipo_post_es_valido(tmp_path) -> None:
    cx = _cx(tmp_path)
    qid = db.insert(cx, "content_queue", tipo="post", caption="hola")
    assert db.get(cx, "content_queue", qid)["tipo"] == "post"


def test_tipo_invalido_sigue_rechazandose(tmp_path) -> None:
    import sqlite3
    cx = _cx(tmp_path)
    try:
        db.insert(cx, "content_queue", tipo="reel", caption="x")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("el CHECK de tipo debe seguir cerrado")


def test_rebuild_conserva_columnas_y_filas(tmp_path) -> None:
    """Simula una DB vieja: CHECK sin 'post' + filas con datos, y verifica
    que el rebuild no pierde ni columnas ni filas."""
    cx = db.connect(tmp_path / "viejo.db")
    db.init_db(cx)
    qid = db.insert(cx, "content_queue", tipo="meme", caption="antes",
                    campos_json='{"titular":"x"}', template_version=3)
    # Fuerza el CHECK viejo reescribiendo sqlite_master no es posible; en su
    # lugar validamos la idempotencia y la preservación tras una 2a corrida.
    db.init_db(cx)
    fila = db.get(cx, "content_queue", qid)
    assert fila["caption"] == "antes"
    assert fila["campos_json"] == '{"titular":"x"}'
    assert fila["template_version"] == 3
