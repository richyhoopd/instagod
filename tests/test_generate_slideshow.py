"""Orquestador de slideshows: dry-run, encolado y envío a Telegram."""
from __future__ import annotations

import json
import json as json_mod
from dataclasses import dataclass

from src import db
from src import db as db_mod
from src import generate_slideshow as gs


@dataclass
class _Img:
    ruta_o_url: str
    source: str = "pexels"


def _guion(n=3):
    return {"tema": "café", "hook": "Gancho", "caption": "pie del post",
            "cta": "Sígueme",
            "slides": [{"text": "Gancho", "rol": "hook", "image_hint": "a"},
                       {"text": "Punto", "rol": "punto", "image_hint": "b"},
                       {"text": "Sígueme", "rol": "cta", "image_hint": "c"}][:n]}


def _preparar(monkeypatch, tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: _guion())
    monkeypatch.setattr(gs.image_sources, "resolver",
                        lambda hints, fuentes, **kw: [_Img("/tmp/x.jpg")] * len(hints))
    pngs = iter([tmp_path / f"s{i}.png" for i in range(10)])

    def _render(template_file, ctx, **kw):
        p = next(pngs)
        p.write_bytes(b"png")
        return p

    monkeypatch.setattr(gs.compose, "render_card", _render)
    subidas = []

    def _upload(path, public_id=None):
        subidas.append(public_id)
        return f"https://cdn/{public_id}.jpg"

    monkeypatch.setattr(gs.host, "upload", _upload)
    enviados = []
    monkeypatch.setattr(gs.approval, "enviar_a_telegram",
                        lambda cap, url, qid, **kw: enviados.append((cap, url, qid, kw)))
    return cx, subidas, enviados


def test_dry_run_no_sube_ni_encola(monkeypatch, tmp_path) -> None:
    cx, subidas, enviados = _preparar(monkeypatch, tmp_path)
    out = gs.generar(cx, "café", dry_run=True)
    assert out is None
    assert subidas == [] and enviados == []
    assert db.rows(cx, "SELECT * FROM content_queue") == []


def test_generar_encola_y_envia(monkeypatch, tmp_path) -> None:
    cx, subidas, enviados = _preparar(monkeypatch, tmp_path)
    qid = gs.generar(cx, "café")
    assert qid is not None
    fila = db.get(cx, "content_queue", qid)
    assert fila["tipo"] == "slideshow"
    assert fila["aprobacion"] == "pendiente"
    urls = json.loads(fila["imagen_url"])
    assert len(urls) == 3 and all(u.startswith("https://cdn/") for u in urls)
    contrato = json.loads(fila["slideshow_json"])
    assert len(contrato["slides"]) == 3
    assert enviados and enviados[0][2] == qid
    assert len(subidas) == 3


def test_generar_aborta_si_contrato_invalido(monkeypatch, tmp_path) -> None:
    cx, _, enviados = _preparar(monkeypatch, tmp_path)
    malo = _guion()
    malo["slides"][0]["text"] = "   "
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: malo)
    import pytest
    with pytest.raises(RuntimeError):
        gs.generar(cx, "café")
    assert enviados == []
    assert db.rows(cx, "SELECT * FROM content_queue") == []


def _alta_marca(cx):
    return db_mod.insert(
        cx, "accounts", slug="pensionmas", ig_handle="@pensionmas",
        nombre="Pensión+", ciudad="CDMX",
        voz="REGLAS: montos estimados.",
        fuentes_imagen=json_mod.dumps(["pinterest", "pexels"]),
        formatos=json_mod.dumps(["libre"]),
        estilos_json=json_mod.dumps({"pensionmas": {
            "texto": "blanco", "fondo": "navy", "background_opacity": 0.3,
            "chrome": {"handle": "@pensionmas", "logo": None},
            "roles": {"hook": {"font": "Erode-Bold", "font_size": "extra_large",
                               "text_style": "background",
                               "text_vertical_anchor": "center"},
                      "punto": {"font": "Erode-Semibold", "font_size": "large",
                                "text_style": "background",
                                "text_vertical_anchor": "center"},
                      "cta": {"font": "Poppins-SemiBold", "font_size": "medium",
                              "text_style": "background",
                              "text_vertical_anchor": "bottom"}}}}))


def test_generar_con_marca_usa_su_perfil(monkeypatch, tmp_path) -> None:
    cx, subidas, enviados = _preparar(monkeypatch, tmp_path)
    mid = _alta_marca(cx)
    capturado = {}

    def _guion_spy(tema, **kw):
        capturado.update(kw)
        return _guion()

    monkeypatch.setattr(gs.slideshow_script, "generar_guion", _guion_spy)
    fuentes_vistas = {}

    def _resolver_spy(hints, fuentes, **kw):
        fuentes_vistas["f"] = fuentes
        return [None] * len(hints)

    monkeypatch.setattr(gs.image_sources, "resolver", _resolver_spy)
    qid = gs.generar(cx, "afore", marca="pensionmas")
    fila = db_mod.get(cx, "content_queue", qid)
    assert fila["account_id"] == mid
    assert capturado["formato"] == "libre"                 # default del perfil
    assert "montos estimados" in capturado["contexto"]     # voz inyectada
    assert fuentes_vistas["f"] == ["pinterest", "pexels"]
    assert enviados[-1][3].get("account_slug") == "pensionmas"
    contrato = json_mod.loads(fila["slideshow_json"])
    assert contrato["brief"]["fondo"] == "navy"            # estilo de marca


def test_generar_formato_no_habilitado(monkeypatch, tmp_path) -> None:
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    _alta_marca(cx)
    import pytest
    with pytest.raises(ValueError, match="formato"):
        gs.generar(cx, "afore", marca="pensionmas", formato="perfil")


def test_generar_sin_marca_sigue_siendo_gdlscene(monkeypatch, tmp_path) -> None:
    cx, _, enviados = _preparar(monkeypatch, tmp_path)
    qid = gs.generar(cx, "café")
    assert db_mod.get(cx, "content_queue", qid)["account_id"] == 1
    assert enviados[-1][3].get("account_slug", "gdlscene") == "gdlscene"
