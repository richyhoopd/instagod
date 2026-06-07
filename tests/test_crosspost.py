"""Crosspost X/FB: adaptación de captions y fan-out por plataforma de publish.py."""
from __future__ import annotations

import publish
from src import facebook, x_twitter


# ---------- adaptar_caption (X) ----------

def test_x_quita_arrobas_pero_deja_nombres():
    out = x_twitter.adaptar_caption("Tocan @los_baxters con @extranoenemigo_ hoy")
    assert out == "Tocan los_baxters con extranoenemigo_ hoy"


def test_x_recorta_a_280_sin_partir_palabras():
    texto = "palabra " * 60  # ~480 chars
    out = x_twitter.adaptar_caption(texto)
    assert len(out) <= 280
    assert out.endswith("…")
    assert not out[:-1].endswith(" palabr")  # no corta a media palabra


def test_x_caption_corto_queda_igual():
    assert x_twitter.adaptar_caption("Reporte: todo bien") == "Reporte: todo bien"


def test_fb_quita_arrobas_sin_recortar():
    texto = "x" * 500 + " @kabala_oficial"
    out = facebook.adaptar_caption(texto)
    assert "@" not in out
    assert len(out) > 280  # FB no recorta


# ---------- fan-out de publish.py ----------

class _FakeMod:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def publish(self, url, caption):
        self.calls.append(("single", url))
        if self.fail:
            raise RuntimeError("boom")
        return "post123"

    def publish_carousel(self, urls, caption):
        self.calls.append(("carousel", tuple(urls)))
        if self.fail:
            raise RuntimeError("boom")
        return "carrusel123"


def _row(**extra):
    base = {"id": 7, "imagen_compuesta_url": "https://img/x.png",
            "caption_final": "hola", "ig_post_id": "", "tw_post_id": "", "fb_post_id": ""}
    base.update(extra)
    return base


def test_publica_en_todas_las_habilitadas(monkeypatch):
    ig, tw, fb = _FakeMod(), _FakeMod(), _FakeMod()
    escritos = {}
    monkeypatch.setattr(publish, "PLATFORMS", [
        ("ig_post_id", "ig", ig, True), ("tw_post_id", "x", tw, True),
        ("fb_post_id", "fb", fb, True)])
    monkeypatch.setattr(publish.sheets, "update_row",
                        lambda rid, **f: escritos.update(f))
    listas, errores = publish.publish_row(_row())
    assert listas and not errores
    assert {"ig_post_id", "tw_post_id", "fb_post_id"} <= set(escritos)
    assert all(len(m.calls) == 1 for m in (ig, tw, fb))


def test_reintento_salta_las_que_ya_tienen_id(monkeypatch):
    ig, tw, fb = _FakeMod(), _FakeMod(), _FakeMod()
    monkeypatch.setattr(publish, "PLATFORMS", [
        ("ig_post_id", "ig", ig, True), ("tw_post_id", "x", tw, True),
        ("fb_post_id", "fb", fb, True)])
    monkeypatch.setattr(publish.sheets, "update_row", lambda rid, **f: None)
    listas, _ = publish.publish_row(_row(ig_post_id="ya_existe"))
    assert listas
    assert ig.calls == []  # no duplica IG
    assert len(tw.calls) == 1 and len(fb.calls) == 1


def test_fallo_parcial_no_bloquea_a_las_demas(monkeypatch):
    ig, tw, fb = _FakeMod(), _FakeMod(fail=True), _FakeMod()
    escritos = {}
    monkeypatch.setattr(publish, "PLATFORMS", [
        ("ig_post_id", "ig", ig, True), ("tw_post_id", "x", tw, True),
        ("fb_post_id", "fb", fb, True)])
    monkeypatch.setattr(publish.sheets, "update_row",
                        lambda rid, **f: escritos.update(f))
    listas, errores = publish.publish_row(_row())
    assert not listas
    assert len(errores) == 1 and errores[0].startswith("x:")
    assert "ig_post_id" in escritos and "fb_post_id" in escritos
    assert "tw_post_id" not in escritos


def test_deshabilitada_no_bloquea_published(monkeypatch):
    ig, tw, fb = _FakeMod(), _FakeMod(fail=True), _FakeMod()
    monkeypatch.setattr(publish, "PLATFORMS", [
        ("ig_post_id", "ig", ig, True), ("tw_post_id", "x", tw, False),
        ("fb_post_id", "fb", fb, True)])
    monkeypatch.setattr(publish.sheets, "update_row", lambda rid, **f: None)
    listas, errores = publish.publish_row(_row())
    assert listas and not errores
    assert tw.calls == []


def test_carrusel_usa_publish_carousel(monkeypatch):
    ig = _FakeMod()
    monkeypatch.setattr(publish, "PLATFORMS", [("ig_post_id", "ig", ig, True)])
    monkeypatch.setattr(publish.sheets, "update_row", lambda rid, **f: None)
    row = _row(imagen_compuesta_url='["https://a.png", "https://b.png"]')
    listas, _ = publish.publish_row(row)
    assert listas
    assert ig.calls[0][0] == "carousel"
