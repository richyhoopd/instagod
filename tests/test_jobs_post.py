"""Handlers de job del post simple."""
from __future__ import annotations

import json

import pytest

from src import db, jobs, marcas, plantillas
from src.jobs import handlers
from src.plantillas import contrato as c

_HTML = "<div class='card'>{{ titular }} {{ handle }}</div>"


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _ct() -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": []}


def test_registrados_en_handlers() -> None:
    assert "post.generar" in handlers.HANDLERS
    assert "post.rerender" in handlers.HANDLERS


def test_generar_post_crea_la_pieza_y_reporta_progreso(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = plantillas.crear(cx, m.id, "Simple", _HTML, _ct())
    monkeypatch.setattr(handlers.posts, "crear_post", lambda *a, **k: 4242)

    vistos: list[int] = []
    real = jobs.progresar
    monkeypatch.setattr(handlers.jobs, "progresar",
                        lambda cx_, jid, pct, msg: vistos.append(pct) or real(cx_, jid, pct, msg))

    jid = jobs.crear(cx, "post.generar", m.id,
                     {"template_id": tid, "tema": "lo que sea"})
    job = db.get(cx, "jobs", jid)
    out = handlers.HANDLERS["post.generar"](cx, job)

    assert out["queue_id"] == 4242
    assert db.get(cx, "jobs", jid)["queue_id"] == 4242
    assert vistos, "el handler debe reportar progreso"


def test_generar_post_rechaza_plantilla_de_otra_marca(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    otra_id = db.insert(cx, "accounts", slug="otra", ig_handle="otra",
                        nombre="Otra", ciudad="CDMX")
    tid_ajena = plantillas.crear(cx, otra_id, "Ajena", _HTML, _ct())

    def explota(*a, **k):
        raise ValueError("plantilla")

    monkeypatch.setattr(handlers.posts, "crear_post", explota)
    jid = jobs.crear(cx, "post.generar", m.id,
                     {"template_id": tid_ajena, "tema": "x"})
    with pytest.raises(ValueError, match="plantilla"):
        handlers.HANDLERS["post.generar"](cx, db.get(cx, "jobs", jid))


def test_rerender_post_no_llama_al_llm(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    qid = db.insert(cx, "content_queue", tipo="post", account_id=m.id,
                    campos_json=json.dumps({"titular": "x"}))
    monkeypatch.setattr(handlers.posts, "rerender", lambda *a, **k: "https://cdn/y.png")
    jid = jobs.crear(cx, "post.rerender", m.id, {"queue_id": qid})
    out = handlers.HANDLERS["post.rerender"](cx, db.get(cx, "jobs", jid))
    assert out["queue_id"] == qid


def test_el_handler_pasa_un_objeto_marca_y_no_un_slug(tmp_path, monkeypatch) -> None:
    """Costura entre handlers.py y posts.py, SIN mockear crear_post.

    `_marca_de` devuelve el SLUG (str), no un objeto `Marca`. Si el handler
    se lo pasa tal cual a `posts.crear_post`, revienta con AttributeError en
    `marca.id` — en producción, no en CI, porque el resto de los tests de este
    archivo mockean `crear_post` y nunca ejercitan el tipo real.

    Este test corre el handler de verdad contra la orquestación de verdad, y
    solo mockea lo que sale de la máquina: el LLM, Chromium y la subida.
    """
    import json as _json

    from src import marcas, plantillas
    from src.plantillas import contrato as c

    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    ct = {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": []}
    tid = plantillas.crear(cx, m.id, "Simple", _HTML, ct)

    png = tmp_path / "fake.png"
    png.write_bytes(b"\x89PNG" + b"0" * 20_000)
    monkeypatch.setattr(handlers.posts.render, "render", lambda *a, **k: png)
    monkeypatch.setattr(handlers.posts.host, "upload", lambda ruta, **k: "https://cdn/x.png")
    monkeypatch.setattr(handlers.posts.generador, "generar_campos",
                        lambda ct_, **kw: {"titular": "Hola desde el handler"})

    jid = jobs.crear(cx, "post.generar", m.id, {"template_id": tid, "tema": "x"})
    out = handlers.HANDLERS["post.generar"](cx, db.get(cx, "jobs", jid))

    fila = db.get(cx, "content_queue", out["queue_id"])
    assert fila["account_id"] == m.id
    assert fila["tipo"] == "post"
    assert _json.loads(fila["campos_json"])["titular"] == "Hola desde el handler"
