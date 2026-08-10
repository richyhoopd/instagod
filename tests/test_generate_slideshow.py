"""Orquestador de slideshows: dry-run, encolado y envío a Telegram."""
from __future__ import annotations

import json
from dataclasses import dataclass

from src import db
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
                        lambda cap, url, qid, **kw: enviados.append((cap, url, qid)))
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
