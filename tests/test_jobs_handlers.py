"""Handlers de jobs de slideshow: generar/regenerar delegan en generate_slideshow."""
from __future__ import annotations

import json

import pytest

from src import db, jobs
from src import generate_slideshow as gs
from src.jobs import handlers


@pytest.fixture()
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def _fake_generar(registro):
    def _f(cx, tema, **kw):
        registro.append({"tema": tema, **kw})
        return 77
    return _f


def test_generar_slideshow_pasa_marca_tema_progreso_y_guarda_queue_id(cx, monkeypatch) -> None:
    registro = []
    monkeypatch.setattr(handlers.generate_slideshow, "generar", _fake_generar(registro))

    payload = {"tema": "cafeterías", "formato": "listicle", "estilo": "tiktok_bold",
               "fuentes": ["pexels"], "n_slides": 5, "aspect": "4:5", "contexto": None}
    jid = jobs.crear(cx, "slideshow.generar", 1, payload, creado_por=9)
    job = db.get(cx, "jobs", jid)

    resultado = handlers.generar_slideshow(cx, job)

    assert resultado == {"queue_id": 77}
    assert db.get(cx, "jobs", jid)["queue_id"] == 77
    assert len(registro) == 1
    llamada = registro[0]
    assert llamada["tema"] == "cafeterías"
    assert llamada["marca"] == "gdlscene"  # account_id=1 seed
    assert llamada["formato"] == "listicle"
    assert llamada["estilo"] == "tiktok_bold"
    assert llamada["fuentes"] == ("pexels",)
    assert llamada["n_slides"] == 5
    assert llamada["aspect"] == "4:5"
    assert llamada["creado_por"] == 9
    assert callable(llamada["progreso"])


def test_generar_slideshow_pasa_topic_id_al_motor(cx, monkeypatch) -> None:
    registro = []
    monkeypatch.setattr(handlers.generate_slideshow, "generar", _fake_generar(registro))

    payload = {"tema": "cafeterías", "formato": "listicle", "estilo": "tiktok_bold",
               "fuentes": ["pexels"], "n_slides": 5, "aspect": "4:5", "contexto": None,
               "topic_id": 42}
    jid = jobs.crear(cx, "slideshow.generar", 1, payload, creado_por=9)
    job = db.get(cx, "jobs", jid)

    handlers.generar_slideshow(cx, job)

    assert registro[0]["topic_id"] == 42


def test_generar_slideshow_progreso_llega_a_jobs_progresar(cx, monkeypatch) -> None:
    capturado = {}

    def _f(cx, tema, **kw):
        capturado["progreso"] = kw["progreso"]
        return 77

    monkeypatch.setattr(handlers.generate_slideshow, "generar", _f)
    jid = jobs.crear(cx, "slideshow.generar", 1, {"tema": "x"})
    job = db.get(cx, "jobs", jid)

    handlers.generar_slideshow(cx, job)
    capturado["progreso"](40, "imágenes")

    fila = db.get(cx, "jobs", jid)
    assert "[40%] imágenes" in fila["log"]


def test_regenerar_slideshow_descarta_la_fila_vieja_y_usa_el_brief(cx, monkeypatch) -> None:
    registro = []
    monkeypatch.setattr(handlers.generate_slideshow, "generar", _fake_generar(registro))

    brief = {"tema": "x", "formato": "listicle", "estilo": "e", "fuentes": ["pexels"],
              "n_slides": 6, "contexto": None, "aspect": "4:5", "marca": "gdlscene"}
    qid = db.insert(cx, "content_queue", tipo="slideshow", status="publicado",
                    caption="cap", imagen_url="[]", account_id=1,
                    slideshow_json=json.dumps({"brief": brief}))
    jid = jobs.crear(cx, "slideshow.regenerar", 1, {"queue_id": qid}, creado_por=3)
    job = db.get(cx, "jobs", jid)

    resultado = handlers.regenerar_slideshow(cx, job)

    assert resultado == {"queue_id": 77}
    assert db.get(cx, "content_queue", qid)["status"] == "descartado"
    assert db.get(cx, "jobs", jid)["queue_id"] == 77
    assert len(registro) == 1
    llamada = registro[0]
    assert llamada["tema"] == "x"
    assert llamada["marca"] == "gdlscene"
    assert llamada["formato"] == "listicle"
    assert llamada["estilo"] == "e"
    assert llamada["fuentes"] == ("pexels",)
    assert llamada["n_slides"] == 6
    assert llamada["aspect"] == "4:5"
    assert llamada["creado_por"] == 3


def test_regenerar_slideshow_usa_la_marca_del_job_no_la_del_brief(cx, monkeypatch) -> None:
    """G2: el brief guardado puede traer una marca vieja/equivocada (la fila
    pudo migrar de cuenta); regenerar_slideshow debe usar SIEMPRE la marca
    real del job (account_id), nunca `brief["marca"]`."""
    registro = []
    monkeypatch.setattr(handlers.generate_slideshow, "generar", _fake_generar(registro))
    otra_id = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p",
                        nombre="Pension+", ciudad="CDMX")

    brief = {"tema": "x", "formato": "listicle", "estilo": "e", "fuentes": ["pexels"],
              "n_slides": 6, "contexto": None, "aspect": "4:5", "marca": "gdlscene"}
    qid = db.insert(cx, "content_queue", tipo="slideshow", status="publicado",
                    caption="cap", imagen_url="[]", account_id=otra_id,
                    slideshow_json=json.dumps({"brief": brief}))
    jid = jobs.crear(cx, "slideshow.regenerar", otra_id, {"queue_id": qid}, creado_por=3)
    job = db.get(cx, "jobs", jid)

    handlers.regenerar_slideshow(cx, job)

    assert registro[0]["marca"] == "pensionmas"


# ---------- smoke test real de progreso en generate_slideshow.generar ----------

@pytest.fixture()
def _cx_slideshow(tmp_path):
    c = db.connect(tmp_path / "s.db")
    db.init_db(c)
    yield c
    c.close()


def _guion(n=3):
    return {"tema": "café", "hook": "Gancho", "caption": "pie del post", "cta": "Sígueme",
            "slides": [{"text": "Gancho", "rol": "hook", "image_hint": "a"},
                       {"text": "Punto", "rol": "punto", "image_hint": "b"},
                       {"text": "Sígueme", "rol": "cta", "image_hint": "c"}][:n]}


def test_generar_reporta_progreso_creciente_hasta_100(monkeypatch, _cx_slideshow, tmp_path) -> None:
    from dataclasses import dataclass

    @dataclass
    class _Img:
        ruta_o_url: str
        source: str = "pexels"

    monkeypatch.setattr(gs.slideshow_script, "generar_guion", lambda tema, **kw: _guion())
    monkeypatch.setattr(gs.image_sources, "resolver",
                        lambda hints, fuentes, **kw: [_Img("/tmp/x.jpg")] * len(hints))
    pngs = iter([tmp_path / f"s{i}.png" for i in range(10)])

    def _render(template_file, ctx, **kw):
        p = next(pngs)
        p.write_bytes(b"png")
        return p

    monkeypatch.setattr(gs.compose, "render_card", _render)
    monkeypatch.setattr(gs.host, "upload", lambda path, public_id=None: f"https://cdn/{public_id}.jpg")
    monkeypatch.setattr(gs.approval, "enviar_a_telegram", lambda *a, **kw: None)

    reportes = []
    qid = gs.generar(_cx_slideshow, "café",
                     progreso=lambda pct, msg: reportes.append(pct), dry_run=False)

    assert qid is not None
    assert reportes == sorted(reportes)
    assert reportes[-1] == 100
    assert reportes[0] < reportes[-1]


# ---------- slideshow.rerender (Fase 4: edición slide por slide) ----------

def _show_json_valido():
    slides = [
        {"image_urls": ["https://cdn/x.jpg"], "image_layout": "single",
         "text_items": [{"text": "hook"}], "is_cta": False,
         "background_opacity": 0.35, "duration": 3.0, "source": "manual"},
        {"image_urls": [], "image_layout": "single",
         "text_items": [{"text": "cierre"}], "is_cta": True,
         "background_opacity": 0.0, "duration": 3.0, "source": "manual"},
    ]
    return json.dumps({"title": "t", "aspect_ratio": "4:5", "slides": slides,
                       "caption": "cap", "language": "es",
                       "brief": {"tema": "t", "estilo": "tiktok_bold"},
                       "formato": "listicle", "account_slug": "gdlscene"})


def test_rerender_slideshow_renderiza_sube_y_actualiza_imagen_url(cx, monkeypatch) -> None:
    renders, subidas = [], []

    def _fake_render(template, ctx, **kw):
        renders.append(kw.get("prefix"))
        return f"/tmp/{kw.get('prefix')}.png"

    def _fake_upload(path, public_id=None):
        subidas.append(public_id)
        return f"https://cdn/{public_id}.jpg"

    monkeypatch.setattr(handlers.compose, "render_card", _fake_render)
    monkeypatch.setattr(handlers.host, "upload", _fake_upload)

    qid = db.insert(cx, "content_queue", tipo="slideshow", status="programado",
                    aprobacion="aprobado", caption="cap", imagen_url="[]",
                    account_id=1, slideshow_json=_show_json_valido())
    jid = jobs.crear(cx, "slideshow.rerender", 1, {"queue_id": qid}, creado_por=3)
    job = db.get(cx, "jobs", jid)

    resultado = handlers.rerender_slideshow(cx, job)

    assert resultado == {"queue_id": qid}
    fila = db.get(cx, "content_queue", qid)
    urls = json.loads(fila["imagen_url"])
    assert len(urls) == 2 and all(u.startswith("https://cdn/") for u in urls)
    assert len(renders) == 2
    assert fila["status"] == "programado"  # el estado no cambia
    assert db.get(cx, "jobs", jid)["queue_id"] == qid


def test_rerender_slideshow_fila_inexistente(cx) -> None:
    jid = jobs.crear(cx, "slideshow.rerender", 1, {"queue_id": 999})
    job = db.get(cx, "jobs", jid)
    with pytest.raises(ValueError):
        handlers.rerender_slideshow(cx, job)


def test_rerender_slideshow_registrado_en_handlers(cx) -> None:
    assert handlers.HANDLERS["slideshow.rerender"] is handlers.rerender_slideshow
