"""Orquestación del post simple. LLM e imágenes mockeados: cero red."""
from __future__ import annotations

import json

from src import db, entidades, marcas, plantillas, posts
from src.plantillas import contrato as c

_HTML = ("<div class='card'>{{ titular }} {{ handle }}"
         "{% if imagen %}<img src='{{ imagen }}'>{% endif %}</div>")


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _ct() -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": []}


def _plantilla(cx, account_id) -> int:
    return plantillas.crear(cx, account_id, "Simple", _HTML, _ct())


def _sin_render(monkeypatch, tmp_path):
    """Evita levantar Chromium en los tests de orquestación."""
    png = tmp_path / "fake.png"
    png.write_bytes(b"\x89PNG" + b"0" * 20_000)
    monkeypatch.setattr(posts.render, "render", lambda *a, **k: png)
    monkeypatch.setattr(posts.host, "upload", lambda ruta, **k: "https://cdn/x.png")
    return png


def test_crear_post_inserta_fila_completa(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = _plantilla(cx, m.id)
    _sin_render(monkeypatch, tmp_path)
    monkeypatch.setattr(posts.generador, "generar_campos",
                        lambda ct, **kw: {"titular": "Hola mundo"})

    qid = posts.crear_post(cx, m, template_id=tid, tema="lo que sea")
    fila = db.get(cx, "content_queue", qid)
    assert fila["tipo"] == "post"
    assert fila["template_id"] == tid
    assert fila["template_version"] == 1
    assert fila["aspecto"] == "4:5"
    assert json.loads(fila["campos_json"])["titular"] == "Hola mundo"
    assert fila["status"] == "borrador"
    # 'pendiente', no None: la fila se inserta con el PNG ya hecho, así que
    # lo que falta es la revisión humana. Con None, estado_de la deriva como
    # "generando" y el portal no deja ni editarla ni aprobarla.
    assert fila["aprobacion"] == "pendiente"
    assert fila["account_id"] == m.id


def test_los_campos_manuales_ganan_al_llm(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = _plantilla(cx, m.id)
    _sin_render(monkeypatch, tmp_path)

    def no_debe_llamarse(*a, **k):
        raise AssertionError("no se debe llamar al LLM si vienen campos manuales")

    monkeypatch.setattr(posts.generador, "generar_campos", no_debe_llamarse)
    qid = posts.crear_post(cx, m, template_id=tid, tema="x",
                           campos_manuales={"titular": "Escrito a mano"})
    assert json.loads(db.get(cx, "content_queue", qid)["campos_json"])["titular"] == "Escrito a mano"


def test_congela_la_version_de_la_plantilla(tmp_path, monkeypatch) -> None:
    """Editar la plantilla después no debe cambiar piezas ya generadas."""
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = _plantilla(cx, m.id)
    _sin_render(monkeypatch, tmp_path)
    monkeypatch.setattr(posts.generador, "generar_campos",
                        lambda ct, **kw: {"titular": "v1"})
    qid = posts.crear_post(cx, m, template_id=tid, tema="x")
    plantillas.nueva_version(cx, tid, _HTML + "<b>v2</b>", _ct())
    assert db.get(cx, "content_queue", qid)["template_version"] == 1
    assert plantillas.obtener(cx, tid)["version_actual"] == 2


def test_imagen_manual_gana(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    monkeypatch.setattr(posts.image_sources, "resolver",
                        lambda *a, **k: [None])
    assert posts.resolver_imagen(cx, m, manual="/tmp/mia.jpg") == "/tmp/mia.jpg"


def test_usa_foto_de_la_entidad_antes_que_la_cascada(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    bid = db.insert(cx, "bands", nombre="Los Ejemplo", account_id=m.id)
    eid = entidades.crear(cx, m.id, "Los Ejemplo", "banda", band_id=bid)
    db.insert(cx, "photos", band_id=bid, entity_id=eid,
              path="/tmp/de-la-banda.jpg", usable_meme=1)

    def no_debe_llamarse(*a, **k):
        raise AssertionError("no debe caer a la cascada si la entidad tiene foto")

    monkeypatch.setattr(posts.image_sources, "resolver", no_debe_llamarse)
    assert posts.resolver_imagen(cx, m, entidad_id=eid) == "/tmp/de-la-banda.jpg"


def test_sin_imagen_no_es_error(tmp_path, monkeypatch) -> None:
    """Una marca de puro texto es válida: la plantilla decide con {% if %}."""
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    monkeypatch.setattr(posts.image_sources, "resolver", lambda *a, **k: [None])
    assert posts.resolver_imagen(cx, m, hint="lo que sea") is None


def test_rerender_usa_los_campos_guardados(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = _plantilla(cx, m.id)
    _sin_render(monkeypatch, tmp_path)
    monkeypatch.setattr(posts.generador, "generar_campos",
                        lambda ct, **kw: {"titular": "original"})
    qid = posts.crear_post(cx, m, template_id=tid, tema="x")

    db.update(cx, "content_queue", qid,
              campos_json=json.dumps({"titular": "editado a mano"}))

    def no_debe_llamarse(*a, **k):
        raise AssertionError("rerender NO debe llamar al LLM")

    monkeypatch.setattr(posts.generador, "generar_campos", no_debe_llamarse)
    posts.rerender(cx, m, qid)
    assert json.loads(db.get(cx, "content_queue", qid)["campos_json"])["titular"] == "editado a mano"


def test_la_pieza_creada_queda_editable_y_aprobable(tmp_path, monkeypatch) -> None:
    """Regresión de la costura entre posts.py y cola.py.

    La fila se inserta DESPUÉS de renderizar, así que la pieza ya está lista.
    Con `aprobacion=NULL`, `cola.estado_de` la derivaba como "generando"
    (origen='api' + aprobacion NULL = "el worker la está armando") y el
    colaborador no podía ni editarla ni aprobarla desde el portal.
    """
    from src import cola

    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = _plantilla(cx, m.id)
    _sin_render(monkeypatch, tmp_path)
    monkeypatch.setattr(posts.generador, "generar_campos",
                        lambda ct, **kw: {"titular": "Hola"})

    qid = posts.crear_post(cx, m, template_id=tid, tema="x")
    fila = db.get(cx, "content_queue", qid)
    assert cola.estado_de(fila) == "pendiente"
    assert cola.estado_de(fila) in cola._EDITABLES_CAMPOS

    # Y de hecho se puede editar, que es lo que el portal necesita.
    cola.editar_campos(cx, qid, {"titular": "corregido a mano"})
    guardado = json.loads(db.get(cx, "content_queue", qid)["campos_json"])
    assert guardado["titular"] == "corregido a mano"
