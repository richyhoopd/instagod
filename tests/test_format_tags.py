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


# ── etiquetar_publicados ────────────────────────────────────────────────────

def _seed_publicado(cx, formato_patron_cola=None):
    """Siembra banda → content_queue → ig_posts con caption."""
    bid = db.insert(cx, "bands", nombre="Los Prueba")
    qid = db.insert(cx, "content_queue", tipo="meme", band_id=bid,
                    formato_patron=formato_patron_cola)
    pid = db.insert(cx, "ig_posts", band_id=bid, queue_id=qid,
                    caption="El baterista usó el microondas", media_id="M1")
    return bid, qid, pid


def test_etiquetar_publicados_etiqueta_unlabeled(tmp_path) -> None:
    """Un ig_posts con caption etiqueta el content_queue vinculado (NULL → patrón)."""
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    _bid, qid, _pid = _seed_publicado(cx, formato_patron_cola=None)

    fake_llm = lambda prompt: '{"patron": "absurdo doméstico"}'
    resultado = format_tags.etiquetar_publicados(cx, _llm=fake_llm)

    assert resultado == {"etiquetados": 1, "fallados": 0}
    fila = db.rows(cx, "SELECT formato_patron FROM content_queue WHERE id = ?", (qid,))[0]
    assert fila["formato_patron"] == "absurdo_domestico"


def test_etiquetar_publicados_respeta_ya_etiquetados(tmp_path) -> None:
    """Un content_queue ya con formato_patron no se toca."""
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    _bid, qid, _pid = _seed_publicado(cx, formato_patron_cola="otro")

    fake_llm = lambda prompt: '{"patron": "absurdo doméstico"}'
    resultado = format_tags.etiquetar_publicados(cx, _llm=fake_llm)

    assert resultado == {"etiquetados": 0, "fallados": 0}
    fila = db.rows(cx, "SELECT formato_patron FROM content_queue WHERE id = ?", (qid,))[0]
    assert fila["formato_patron"] == "otro"  # no se pisó
