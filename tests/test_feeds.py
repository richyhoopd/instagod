"""Feeds v1: validación, upsert en brand_entities, cursor, media y avisos."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src import db, entidades, feeds
from tests.fixtures.feed_mwrs import item, sobre


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    aid = db.insert(cx, "accounts", slug="melaquecapital", ig_handle="mc",
                    nombre="MWRS", ciudad="Melaque")
    fid = db.insert(cx, "brand_feeds", account_id=aid,
                    url="https://melaquecapital.com/api/instagod-feed")
    return cx, aid, fid


class _Http:
    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def __call__(self, url, *, params, headers):
        self.llamadas.append({"url": url, "params": params, "headers": headers})
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class _Subir:
    def __init__(self):
        self.urls = []

    def __call__(self, url, *, public_id):
        self.urls.append(url)
        return f"https://res.cloudinary.com/x/{public_id}.jpg"


# ------------------------------------------------------------- validación

def test_item_mwrs_valido():
    assert feeds.validar_item(item()) == []


def test_item_invalido_reporta_cada_campo():
    malo = item(status="vendido", url="/es/propiedades/x", updated_at="ayer",
                media=[{"url": "/img/x.jpg"}], facts=["no"], unverified="regimen")
    del malo["type"]
    errores = " | ".join(feeds.validar_item(malo))
    for campo in ("type", "status", "url", "updated_at", "media[0]", "facts", "unverified"):
        assert campo in errores, campo


def test_title_string_o_dict():
    assert feeds.validar_item(item(title="Casa")) == []
    assert feeds.validar_item(item(title={"es": "", "en": ""}))
    assert feeds.titulo_de(item()) == "Lote esquina en Melaque"
    assert feeds.titulo_de(item(), "en") == "Corner lot in Melaque"


def test_sobre_version_incorrecta():
    assert feeds.validar_sobre({"version": 2, "items": []})
    assert feeds.validar_sobre({"version": 1, "items": None})
    assert feeds.validar_sobre({"version": 1, "items": []}) == []


# ----------------------------------------------------------------- sync

def test_sync_upsert_cursor_y_media(tmp_path):
    cx, aid, fid = _cx(tmp_path)
    otro = item("casa-peñitas", type="property", updated_at="2026-10-07T10:00:00Z")
    http, subir = _Http(sobre([item(), otro, {"id": "roto"}])), _Subir()
    res = feeds.sincronizar(cx, fid, http_get=http, subir=subir, avisar=lambda *a: True)
    assert res["ok"] and res["creadas"] == 2 and res["actualizadas"] == 0
    assert [i["id"] for i in res["invalidos"]] == ["roto"]
    assert http.llamadas[0]["params"] == {}          # sin cursor = feed completo
    assert http.llamadas[0]["headers"] == {}         # MWRS va público
    assert res["cursor"] == "2026-10-07T10:00:00Z"   # max updated_at
    e = entidades.por_slug(cx, aid, "lote-esquina-melaque")
    a = entidades.atributos_de(e)
    assert e["tipo"] == "lot" and e["nombre"] == "Lote esquina en Melaque" and e["activa"]
    assert a["facts"]["m2"] == 300 and a["unverified"] == ["regimen"]
    assert set(a["media_cdn"]) == {m["url"] for m in item()["media"]}
    assert len(subir.urls) == 4
    f = db.get(cx, "brand_feeds", fid)
    assert f["cursor"] == "2026-10-07T10:00:00Z" and f["fallas_seguidas"] == 0
    assert f["ultimo_ok"] and "1 items inválidos" in f["ultimo_error"]


def test_segundo_sync_manda_since_actualiza_y_no_resube(tmp_path):
    cx, aid, fid = _cx(tmp_path)
    subir = _Subir()
    feeds.sincronizar(cx, fid, http_get=_Http(sobre([item()])), subir=subir,
                      avisar=lambda *a: True)
    vendido = item(status="sold", updated_at="2026-10-08T00:00:00Z",
                   facts={"precio": "$1,300,000 MXN", "m2": 300})
    http = _Http(sobre([vendido], cursor="c-opaco-2"))
    res = feeds.sincronizar(cx, fid, http_get=http, subir=subir, avisar=lambda *a: True)
    assert http.llamadas[0]["params"] == {"since": "2026-10-06T18:00:00Z"}
    assert res["creadas"] == 0 and res["actualizadas"] == 1
    assert res["cursor"] == "c-opaco-2"              # cursor explícito del sobre gana
    assert len(subir.urls) == 2                      # las 2 fotos ya estaban
    e = entidades.por_slug(cx, aid, "lote-esquina-melaque")
    assert not e["activa"]                           # sold → no genera contenido
    assert entidades.atributos_de(e)["facts"]["precio"] == "$1,300,000 MXN"
    assert len(entidades.listar(cx, aid, solo_activas=False)) == 1


def test_media_rota_no_tumba_el_item(tmp_path):
    cx, aid, fid = _cx(tmp_path)

    def subir(url, *, public_id):
        raise RuntimeError("cloudinary caído")

    res = feeds.sincronizar(cx, fid, http_get=_Http(sobre([item()])), subir=subir,
                            avisar=lambda *a: True)
    assert res["ok"] and res["creadas"] == 1 and len(res["media_errores"]) == 2


def test_tres_fallas_seguidas_avisan_una_vez_y_ok_resetea(tmp_path):
    cx, aid, fid = _cx(tmp_path)
    avisos = []
    http = _Http(ConnectionError("x"), {"version": 9, "items": []}, ConnectionError("x"),
                 ConnectionError("x"), sobre([item()]))
    for esperado in (1, 2, 3, 4):
        res = feeds.sincronizar(cx, fid, http_get=http, subir=None,
                                avisar=lambda s, t: avisos.append((s, t)) or True)
        assert not res["ok"] and res["fallas_seguidas"] == esperado
    assert len(avisos) == 1 and avisos[0][0] == "melaquecapital"
    assert db.get(cx, "brand_feeds", fid)["cursor"] is None   # cursor no avanza
    res = feeds.sincronizar(cx, fid, http_get=http, subir=None, avisar=lambda *a: True)
    assert res["ok"] and db.get(cx, "brand_feeds", fid)["fallas_seguidas"] == 0


def test_error_no_filtra_el_token(tmp_path, monkeypatch):
    cx, aid, fid = _cx(tmp_path)
    monkeypatch.setattr(feeds, "_token_de", lambda cx, a: "SECRETO123")
    http = _Http(RuntimeError("401 para Bearer SECRETO123"))
    res = feeds.sincronizar(cx, fid, http_get=http, subir=None, avisar=lambda *a: True)
    assert http.llamadas[0]["headers"] == {"Authorization": "Bearer SECRETO123"}
    assert "SECRETO123" not in res["error"]
    assert "SECRETO123" not in db.get(cx, "brand_feeds", fid)["ultimo_error"]


def test_encolar_vencidos_respeta_intervalo_y_dedup(tmp_path):
    cx, aid, fid = _cx(tmp_path)
    ahora = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    assert feeds.encolar_vencidos(cx, ahora) == 1      # nunca intentado
    assert feeds.encolar_vencidos(cx, ahora) == 0      # ya hay job en cola
    cx.execute("UPDATE jobs SET estado = 'ok'")
    reciente = (ahora - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    db.update(cx, "brand_feeds", fid, ultimo_intento=reciente)
    assert feeds.encolar_vencidos(cx, ahora) == 0      # intervalo 360 min
    viejo = (ahora - timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
    db.update(cx, "brand_feeds", fid, ultimo_intento=viejo)
    assert feeds.encolar_vencidos(cx, ahora) == 1


def test_handler_feeds_sync_rechaza_feed_ajeno(tmp_path):
    import json

    import pytest

    from src.jobs import handlers
    cx, aid, fid = _cx(tmp_path)
    with pytest.raises(ValueError):
        handlers.feeds_sync(cx, {"id": 1, "account_id": aid + 99,
                                 "payload_json": json.dumps({"feed_id": fid})})
