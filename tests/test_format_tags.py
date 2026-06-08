"""Etiquetado de formato: derivación de atributos y mapeo de taxonomía."""
from __future__ import annotations

from src import db, format_tags


def test_mapear_patron_contra_taxonomia() -> None:
    assert format_tags.mapear_patron("absurdo_domestico") == "absurdo_domestico"
    assert format_tags.mapear_patron("ABSURDO DOMÉSTICO") == "absurdo_domestico"
    assert format_tags.mapear_patron("categoria_inventada") == "otro"
    assert format_tags.mapear_patron(None) == "otro"


def test_atributos_derivados(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="Kabala")
    mid = db.insert(cx, "members", band_id=bid, nombre="Carlos", rol="guitarra")
    q1 = db.insert(cx, "content_queue", tipo="meme", band_id=bid, member_id=mid,
                   tema_semilla="microondas", template="clasica", formato_patron="absurdo_domestico")
    q2 = db.insert(cx, "content_queue", tipo="meme", band_id=bid)  # sin integrante ni tema
    attrs = {a["queue_id"]: a for a in format_tags.atributos_de_cola(cx)}
    assert attrs[q1]["tiene_integrante"] and attrs[q1]["tiene_tema"]
    assert attrs[q1]["template"] == "clasica" and attrs[q1]["patron"] == "absurdo_domestico"
    assert not attrs[q2]["tiene_integrante"] and not attrs[q2]["tiene_tema"]


def test_etiquetar_post_mapea(monkeypatch) -> None:
    from src import format_tags
    fake = lambda prompt: '{"patron": "absurdo doméstico"}'
    assert format_tags.etiquetar_post("El baterista usó el microondas", _llm=fake) == "absurdo_domestico"
    fake2 = lambda prompt: '{"patron": "no_existe"}'
    assert format_tags.etiquetar_post("x", _llm=fake2) == "otro"
