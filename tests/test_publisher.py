"""Publisher local desde content_queue: publica marcas SIN Sheet (Fase 2).

Regla anti-doble-publicación: marca CON SHEET_ID la publica Actions (Sheet);
este publisher SOLO toca marcas SIN SHEET_ID. Cero llamadas reales a
Telegram/IG: `_ig` inyectable y las filas de prueba no llevan tg_chat_id/
tg_message_id (notificar_resolucion vuelve False sin red).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytz

import config
from src import db, publisher

TZ = pytz.timezone(config.TIMEZONE)


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _marca(cx, slug: str) -> int:
    return db.insert(cx, "accounts", slug=slug, ig_handle=f"@{slug}",
                     nombre=slug, ciudad="CDMX")


def _fila(cx, *, account_id: int, imagen_url: str, scheduled, status="programado",
          aprobacion="aprobado") -> int:
    return db.insert(cx, "content_queue", tipo="meme", account_id=account_id,
                     status=status, aprobacion=aprobacion, caption="hola",
                     imagen_url=imagen_url, scheduled_datetime=scheduled.isoformat())


class FakeIG:
    """Doble de src.instagram: registra llamadas, nunca golpea la red."""

    def __init__(self, media_id: str = "MEDIA123", fallo: Exception | None = None):
        self.media_id = media_id
        self.fallo = fallo
        self.calls: list[tuple] = []

    def publish(self, image_url, caption, *, retries=3, creds=None):
        self.calls.append(("publish", image_url, caption, creds))
        if self.fallo:
            raise self.fallo
        return self.media_id

    def publish_carousel(self, image_urls, caption, *, retries=3, creds=None):
        self.calls.append(("carousel", image_urls, caption, creds))
        if self.fallo:
            raise self.fallo
        return self.media_id


def _ahora():
    return datetime.now(TZ)


# --------- filas_due ---------

def test_filas_due_solo_las_vencidas_programadas_y_aprobadas(tmp_path) -> None:
    cx = _cx(tmp_path)
    mid = _marca(cx, "pensionmas")
    ahora = _ahora()
    vencida = _fila(cx, account_id=mid, imagen_url="u1", scheduled=ahora - timedelta(minutes=5))
    futura = _fila(cx, account_id=mid, imagen_url="u2", scheduled=ahora + timedelta(hours=1))
    no_aprobada = _fila(cx, account_id=mid, imagen_url="u3",
                        scheduled=ahora - timedelta(minutes=5), aprobacion="pendiente")

    due = publisher.filas_due(cx, mid, ahora.isoformat())
    ids = [f["id"] for f in due]
    assert vencida in ids
    assert futura not in ids
    assert no_aprobada not in ids


# --------- ciclo ---------

def test_ciclo_marca_sin_sheet_publica_single_y_carrusel(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SHEET_ID__PENSIONMAS", raising=False)
    monkeypatch.setenv("IG_USER_ID__PENSIONMAS", "555")
    monkeypatch.setenv("IG_ACCESS_TOKEN__PENSIONMAS", "tok_secreto_999")
    cx = _cx(tmp_path)
    mid = _marca(cx, "pensionmas")
    ahora = _ahora()
    q1 = _fila(cx, account_id=mid, imagen_url="https://img/1.jpg",
              scheduled=ahora - timedelta(minutes=5))
    q2 = _fila(cx, account_id=mid, imagen_url=json.dumps(["https://img/2.jpg", "https://img/3.jpg"]),
              scheduled=ahora - timedelta(minutes=5))
    fake = FakeIG(media_id="MEDIA_OK")

    n = publisher.ciclo(cx, ahora=ahora, _ig=fake)

    assert n == 2
    tipos = {c[0] for c in fake.calls}
    assert tipos == {"publish", "carousel"}
    for c in fake.calls:
        assert c[3] == {"user_id": "555", "token": "tok_secreto_999"}

    f1 = db.get(cx, "content_queue", q1)
    f2 = db.get(cx, "content_queue", q2)
    for f in (f1, f2):
        assert f["status"] == "publicado"
        assert f["ig_media_id"] == "MEDIA_OK"
        assert f["publicado_en"]
        assert f["error"] is None


def test_ciclo_marca_con_sheet_se_salta(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SHEET_ID__PENSIONMAS", "SHEET-P")
    monkeypatch.setenv("IG_USER_ID__PENSIONMAS", "555")
    monkeypatch.setenv("IG_ACCESS_TOKEN__PENSIONMAS", "tok")
    cx = _cx(tmp_path)
    mid = _marca(cx, "pensionmas")
    ahora = _ahora()
    qid = _fila(cx, account_id=mid, imagen_url="https://img/1.jpg",
               scheduled=ahora - timedelta(minutes=5))
    fake = FakeIG()

    n = publisher.ciclo(cx, ahora=ahora, _ig=fake)

    assert n == 0
    assert fake.calls == []
    assert db.get(cx, "content_queue", qid)["status"] == "programado"


def test_ciclo_marca_sin_ig_creds_se_salta_sin_tocar_filas(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SHEET_ID__PENSIONMAS", raising=False)
    monkeypatch.delenv("IG_USER_ID__PENSIONMAS", raising=False)
    monkeypatch.delenv("IG_ACCESS_TOKEN__PENSIONMAS", raising=False)
    cx = _cx(tmp_path)
    mid = _marca(cx, "pensionmas")
    ahora = _ahora()
    qid = _fila(cx, account_id=mid, imagen_url="https://img/1.jpg",
               scheduled=ahora - timedelta(minutes=5))
    fake = FakeIG()

    n = publisher.ciclo(cx, ahora=ahora, _ig=fake)

    assert n == 0
    assert fake.calls == []
    fila = db.get(cx, "content_queue", qid)
    assert fila["status"] == "programado"
    assert fila["error"] is None


def test_ciclo_gdlscene_sin_sheet_usa_creds_none(tmp_path, monkeypatch) -> None:
    """gdlscene (account_id=1, seed de init_db) sin SHEET_ID → creds=None (globals)."""
    monkeypatch.delenv("SHEET_ID", raising=False)
    monkeypatch.delenv("SHEET_ID__GDLSCENE", raising=False)
    monkeypatch.setenv("IG_USER_ID", "1")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok-gdl")
    cx = _cx(tmp_path)
    ahora = _ahora()
    qid = _fila(cx, account_id=1, imagen_url="https://img/1.jpg",
               scheduled=ahora - timedelta(minutes=5))
    fake = FakeIG(media_id="M1")

    n = publisher.ciclo(cx, ahora=ahora, _ig=fake)

    assert n == 1
    assert fake.calls[0][3] is None
    assert db.get(cx, "content_queue", qid)["status"] == "publicado"


# --------- publicar_fila: error redactado + reintento ---------

def test_publicar_fila_excepcion_guarda_error_sin_token_y_no_toca_status(tmp_path) -> None:
    cx = _cx(tmp_path)
    mid = _marca(cx, "pensionmas")
    ahora = _ahora()
    qid = _fila(cx, account_id=mid, imagen_url="https://img/1.jpg",
               scheduled=ahora - timedelta(minutes=5))
    fila = db.get(cx, "content_queue", qid)
    creds = {"user_id": "555", "token": "tok_secreto_999"}
    fake = FakeIG(fallo=RuntimeError("Graph API 400: token inválido tok_secreto_999"))

    ok = publisher.publicar_fila(cx, fila, creds, _ig=fake)

    assert ok is False
    fila2 = db.get(cx, "content_queue", qid)
    assert fila2["status"] == "programado"
    assert fila2["error"]
    assert "tok_secreto_999" not in fila2["error"]
    assert len(fila2["error"]) <= 200


def test_publicar_fila_marca_publicando_antes_de_llamar_a_ig(tmp_path) -> None:
    """Ventana de crash: si el proceso muere a media llamada, `error` debe
    quedar en MARCADOR_PUBLICANDO (visible como estado error en vez de
    reintentarse solo y arriesgar duplicado). Si la llamada SÍ termina (aquí
    con una excepción conocida), se sobreescribe con el error real —el
    marcador nunca sobrevive a un intento resuelto."""
    cx = _cx(tmp_path)
    mid = _marca(cx, "pensionmas")
    ahora = _ahora()
    qid = _fila(cx, account_id=mid, imagen_url="https://img/1.jpg",
               scheduled=ahora - timedelta(minutes=5))
    fila = db.get(cx, "content_queue", qid)
    vistos: list[str | None] = []

    class _FakeMarcador:
        def publish(self, image_url, caption, *, retries=3, creds=None):
            vistos.append(db.get(cx, "content_queue", qid)["error"])
            raise RuntimeError("boom")

    ok = publisher.publicar_fila(cx, fila, {"user_id": "1", "token": "tok"},
                                 _ig=_FakeMarcador())

    assert ok is False
    assert vistos == [publisher.MARCADOR_PUBLICANDO]
    fila2 = db.get(cx, "content_queue", qid)
    assert fila2["error"] != publisher.MARCADOR_PUBLICANDO
    assert fila2["intentos"] == 1


def test_publicar_fila_claim_atomico_no_publica_dos_veces(tmp_path) -> None:
    """G3: si otra instancia del publisher ya tomó la fila (marcador puesto
    entre el filas_due de este ciclo y esta llamada), el claim atómico
    (rowcount 0) hace que publicar_fila devuelva False SIN llamar a _ig."""
    cx = _cx(tmp_path)
    mid = _marca(cx, "pensionmas")
    ahora = _ahora()
    qid = _fila(cx, account_id=mid, imagen_url="https://img/1.jpg",
               scheduled=ahora - timedelta(minutes=5))
    fila = db.get(cx, "content_queue", qid)  # snapshot ANTES del marcador
    db.update(cx, "content_queue", qid, error=publisher.MARCADOR_PUBLICANDO)  # otra instancia
    fake = FakeIG()

    ok = publisher.publicar_fila(cx, fila, None, _ig=fake)

    assert ok is False
    assert fake.calls == []


def test_filas_due_excluye_marcador_publicando(tmp_path) -> None:
    cx = _cx(tmp_path)
    mid = _marca(cx, "pensionmas")
    ahora = _ahora()
    qid = _fila(cx, account_id=mid, imagen_url="u1", scheduled=ahora - timedelta(minutes=5))
    db.update(cx, "content_queue", qid, error=publisher.MARCADOR_PUBLICANDO)

    due = publisher.filas_due(cx, mid, ahora.isoformat())

    assert qid not in [f["id"] for f in due]


def test_filas_due_excluye_intentos_agotados(tmp_path) -> None:
    cx = _cx(tmp_path)
    mid = _marca(cx, "pensionmas")
    ahora = _ahora()
    qid = _fila(cx, account_id=mid, imagen_url="u1", scheduled=ahora - timedelta(minutes=5))
    db.update(cx, "content_queue", qid, intentos=publisher.MAX_INTENTOS)

    due = publisher.filas_due(cx, mid, ahora.isoformat())

    assert qid not in [f["id"] for f in due]


def test_fallo_incrementa_intentos_cada_ciclo(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SHEET_ID__PENSIONMAS", raising=False)
    monkeypatch.setenv("IG_USER_ID__PENSIONMAS", "555")
    monkeypatch.setenv("IG_ACCESS_TOKEN__PENSIONMAS", "tok")
    cx = _cx(tmp_path)
    mid = _marca(cx, "pensionmas")
    ahora = _ahora()
    qid = _fila(cx, account_id=mid, imagen_url="https://img/1.jpg",
               scheduled=ahora - timedelta(minutes=5))

    publisher.ciclo(cx, ahora=ahora, _ig=FakeIG(fallo=RuntimeError("boom")))
    assert db.get(cx, "content_queue", qid)["intentos"] == 1

    publisher.ciclo(cx, ahora=ahora, _ig=FakeIG(fallo=RuntimeError("boom")))
    assert db.get(cx, "content_queue", qid)["intentos"] == 2


def test_reintento_siguiente_ciclo_reintenta_fila_con_error(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SHEET_ID__PENSIONMAS", raising=False)
    monkeypatch.setenv("IG_USER_ID__PENSIONMAS", "555")
    monkeypatch.setenv("IG_ACCESS_TOKEN__PENSIONMAS", "tok_secreto_999")
    cx = _cx(tmp_path)
    mid = _marca(cx, "pensionmas")
    ahora = _ahora()
    qid = _fila(cx, account_id=mid, imagen_url="https://img/1.jpg",
               scheduled=ahora - timedelta(minutes=5))

    fake_fail = FakeIG(fallo=RuntimeError("boom"))
    n1 = publisher.ciclo(cx, ahora=ahora, _ig=fake_fail)
    assert n1 == 0
    assert db.get(cx, "content_queue", qid)["status"] == "programado"

    fake_ok = FakeIG(media_id="M2")
    n2 = publisher.ciclo(cx, ahora=ahora, _ig=fake_ok)
    assert n2 == 1
    assert db.get(cx, "content_queue", qid)["status"] == "publicado"


# --------- main(once=True) ---------

def test_main_once_corre_un_solo_ciclo_y_no_duerme(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)

    def _fake_connect(*a, **kw):
        return cx

    monkeypatch.setattr(db, "connect", _fake_connect)

    def _no_dormir(seg):
        raise AssertionError("main(once=True) no debe dormir")

    monkeypatch.setattr(publisher, "_dormir", _no_dormir)

    publisher.main(once=True)  # no debe lanzar ni dormir (0 filas due)
