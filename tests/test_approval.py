"""Aprobación asíncrona: encolar pendiente y resolver (aprobar/rechazar)."""
from __future__ import annotations

from datetime import datetime

from src import approval, db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_encolar_pendiente(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Kabala")
    qid = approval.encolar_pendiente(cx, tipo="meme", band_id=bid,
                                     caption="hola", imagen_url="http://x/y.jpg")
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "pendiente" and fila["status"] == "borrador"
    assert fila["caption"] == "hola" and fila["imagen_url"] == "http://x/y.jpg"


def test_aprobar_meme_toma_hueco_de_la_malla(tmp_path, monkeypatch) -> None:
    """Memes aprobados → siguiente hueco libre de POSTING_SLOTS (no el slot
    semanal de timing, que haría chocar un batch entero en el mismo datetime).
    La foto queda usada (mismo contrato que el plan mensual)."""
    monkeypatch.setenv("SHEET_ID", "SHEET-TEST")  # gdlscene (account_id=1 default)
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Kabala")
    pid = db.insert(cx, "photos", band_id=bid, path="x.jpg")
    qid = approval.encolar_pendiente(cx, tipo="meme", band_id=bid, photo_id=pid,
                                     caption="x", imagen_url="u")
    hueco = datetime(2026, 6, 11, 19, 0)
    slot = approval.aprobar(cx, qid, ahora=datetime(2026, 6, 10, 10, 0),
                            _escribir_sheet=lambda **k: 99,  # doble: no toca Sheet real
                            _slot_meme=lambda ahora, sheet_id, slots: hueco)  # doble: no lee el Sheet
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "aprobado" and fila["status"] == "en_sheet"
    assert fila["sheet_row_id"] == "99"
    assert slot == hueco and fila["scheduled_datetime"] == hueco.isoformat()
    assert db.get(cx, "photos", pid)["usada"] == 1


def test_rechazar(tmp_path) -> None:
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="x", imagen_url="u")
    approval.rechazar(cx, qid)
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "rechazado" and fila["status"] == "descartado"


def test_aprobar_inmediato_publica_ahora(tmp_path, monkeypatch):
    from src import approval, db
    monkeypatch.setenv("SHEET_ID", "SHEET-TEST")  # gdlscene (account_id=1 default)
    cx = db.connect(tmp_path / "t.db"); db.init_db(cx)
    qid = approval.encolar_pendiente(cx, tipo="anuncio", caption="x", imagen_url="u")
    llamado = {}
    slot = approval.aprobar(cx, qid, ahora=__import__("datetime").datetime(2026,6,9,2,0),
                            _escribir_sheet=lambda **k: 5,
                            _publicar=lambda: llamado.setdefault("pub", True))
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "aprobado" and fila["status"] == "en_sheet"
    # tipo 'anuncio' → scheduled = ahora (inmediato) y se llamó _publicar
    assert slot.year == 2026 and slot.hour == 2 and llamado.get("pub")


def test_aprobar_default_ahora_es_aware_en_tz_de_la_cuenta(tmp_path, monkeypatch) -> None:
    """Regresión: sin `ahora`, el slot inmediato debe salir en config.TIMEZONE
    (aware), no en hora-máquina naive — si no, get_due_rows nunca lo ve vencido."""
    import pytz

    import config
    monkeypatch.setenv("SHEET_ID", "SHEET-TEST")  # gdlscene (account_id=1 default)
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="anuncio", caption="x", imagen_url="u")
    slot = approval.aprobar(cx, qid, _escribir_sheet=lambda **k: 7,
                            _publicar=lambda: None)
    assert slot.tzinfo is not None
    esperado = datetime.now(pytz.timezone(config.TIMEZONE)).utcoffset()
    assert slot.utcoffset() == esperado


def test_aprobar_marca_eventos_anunciado(tmp_path, monkeypatch) -> None:
    """Al aprobar, los events de evento_ids quedan status='anunciado'."""
    import json
    monkeypatch.setenv("SHEET_ID", "SHEET-TEST")  # gdlscene (account_id=1 default)
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="SilentNoir")
    e1 = db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-06-01")
    e2 = db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-06-02")
    qid = approval.encolar_pendiente(cx, tipo="anuncio", caption="x", imagen_url="u",
                                     evento_ids=json.dumps([e1, e2]))
    approval.aprobar(cx, qid, ahora=datetime(2026, 6, 8, 10, 0),
                     ventana_trafico="meme", audiencia=[],
                     _escribir_sheet=lambda **k: 99)
    assert db.get(cx, "events", e1)["status"] == "anunciado"
    assert db.get(cx, "events", e2)["status"] == "anunciado"


# --- Helpers PUROS del daemon (la cáscara que hace polling no se testea) ---

def test_construir_botones() -> None:
    teclado = approval.construir_botones(123)
    datas = [b["callback_data"] for fila in teclado for b in fila]
    assert datas == ["aprobar:123", "rechazar:123"]


def test_construir_botones_regenerable() -> None:
    """Memes individuales llevan además 🔄 Regenerar / 🎨 Plantilla."""
    teclado = approval.construir_botones(123, regenerable=True)
    datas = [b["callback_data"] for fila in teclado for b in fila]
    assert datas == ["aprobar:123", "rechazar:123", "regenerar:123", "plantilla:123"]


def test_parsear_callback() -> None:
    assert approval.parsear_callback("aprobar:123") == ("aprobar", 123)
    assert approval.parsear_callback("rechazar:7") == ("rechazar", 7)
    assert approval.parsear_callback("regenerar:9") == ("regenerar", 9)
    assert approval.parsear_callback("plantilla:9") == ("plantilla", 9)


def _meme_en_cola(cx) -> int:
    bid = db.insert(cx, "bands", nombre="Kabala", tipo="banda", ig_handle="kabala_oficial")
    pid = db.insert(cx, "photos", band_id=bid, path="foto.jpg")
    return approval.encolar_pendiente(cx, tipo="meme", band_id=bid, photo_id=pid,
                                      caption="titular viejo\n\n@kabala_oficial",
                                      imagen_url="http://x/v1.jpg", template="clasica")


def test_regenerar_meme(tmp_path, monkeypatch) -> None:
    """🔄: caption nuevo del LLM (acumulando rechazados), recompone y actualiza la fila."""
    import json

    from src import caption as caption_mod
    from src import compose as compose_mod
    from src import host
    cx = _cx(tmp_path)
    qid = _meme_en_cola(cx)
    visto = {}

    def fake_caption(banda=None, rechazados=None, **kw):
        visto["rechazados"] = list(rechazados or [])
        return "titular nuevo"

    monkeypatch.setattr(caption_mod, "generate_caption", fake_caption)
    monkeypatch.setattr(compose_mod, "compose", lambda **kw: tmp_path / "m.png")
    monkeypatch.setattr(host, "upload", lambda *a, **kw: "http://x/v2.jpg")
    cap, url = approval.regenerar_meme(cx, qid)
    fila = db.get(cx, "content_queue", qid)
    # El caption rechazado se guarda SIN el @handle y no se vuelve a sugerir.
    assert visto["rechazados"] == ["titular viejo"]
    assert json.loads(fila["rechazados"]) == ["titular viejo"]
    assert cap == "titular nuevo\n\n@kabala_oficial" == fila["caption"]
    assert url == "http://x/v2.jpg" == fila["imagen_url"]


def test_cambiar_plantilla_conserva_caption(tmp_path, monkeypatch) -> None:
    """🎨: cicla clasica→verde recomponiendo el MISMO caption (sin tocar el LLM)."""
    from src import compose as compose_mod
    from src import host
    cx = _cx(tmp_path)
    qid = _meme_en_cola(cx)
    visto = {}

    def fake_compose(caption=None, template=None, **kw):
        visto.update(caption=caption, template=template)
        return tmp_path / "m.png"

    monkeypatch.setattr(compose_mod, "compose", fake_compose)
    monkeypatch.setattr(host, "upload", lambda *a, **kw: "http://x/v2.jpg")
    cap, _url = approval.cambiar_plantilla(cx, qid)
    fila = db.get(cx, "content_queue", qid)
    assert visto["template"] == "verde" and fila["template"] == "verde"
    assert visto["caption"] == "titular viejo"  # la imagen va sin handle
    assert cap == "titular viejo\n\n@kabala_oficial" == fila["caption"]
    assert fila["rechazados"] is None  # cambiar plantilla no quema el caption


def test_parsear_callback_invalido() -> None:
    import pytest
    with pytest.raises(ValueError):
        approval.parsear_callback("borrar:1")


# --- Helper puro: parsear imagen_url (string vs JSON-lista) ---

def test_parse_imagen_url():
    import json

    from src import approval
    assert approval._urls_de_imagen(json.dumps(["a","b","c"])) == ["a","b","c"]
    assert approval._urls_de_imagen("http://x/y.jpg") == ["http://x/y.jpg"]
    assert approval._urls_de_imagen("") == []


def test_aprobar_rechaza_pieza_descartada(tmp_path, monkeypatch) -> None:
    """Replan (y quitar/eliminar) marcan la fila 'descartado', pero su tarjeta de
    Telegram sigue viva en el chat: send_plan no guarda tg_message_id, así que no
    hay forma de borrarla. Sin este guard, un ✅ tardío le asignaba slot y la
    publicaba semanas después de haberla sacado del plan."""
    import pytest

    monkeypatch.setenv("SHEET_ID", "SHEET-TEST")
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Kabala")
    pid = db.insert(cx, "photos", band_id=bid, path="x.jpg")
    qid = approval.encolar_pendiente(cx, tipo="meme", band_id=bid, photo_id=pid,
                                     caption="x", imagen_url="u")
    db.update(cx, "content_queue", qid, status=db.QUEUE_DESCARTADO)

    with pytest.raises(approval.PiezaDescartada):
        approval.aprobar(cx, qid, ahora=datetime(2026, 6, 10, 10, 0),
                         _escribir_sheet=lambda **k: 99,
                         _slot_meme=lambda ahora, sheet_id, slots: datetime(2026, 6, 11, 19, 0))

    fila = db.get(cx, "content_queue", qid)
    assert fila["status"] == db.QUEUE_DESCARTADO and fila["aprobacion"] == "pendiente"
    assert db.get(cx, "photos", pid)["usada"] == 0  # no consumió la foto


def test_aprobar_pieza_inexistente_no_revienta_con_typeerror(tmp_path) -> None:
    import pytest

    cx = _cx(tmp_path)
    with pytest.raises(approval.PiezaDescartada):
        approval.aprobar(cx, 999999)
