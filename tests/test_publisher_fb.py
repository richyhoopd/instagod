"""Publisher: Facebook como destino por marca, aislado de Instagram."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytz

import config
from src import db, facebook, publisher

TZ = pytz.timezone(config.TIMEZONE)


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _marca(cx, slug: str) -> int:
    return db.insert(cx, "accounts", slug=slug, ig_handle=f"@{slug}", nombre=slug, ciudad="CDMX")


def _fila(cx, account_id: int, plataforma: str, imagen_url="https://cdn/x.png", **kw) -> int:
    venc = datetime.now(TZ) - timedelta(minutes=5)
    return db.insert(cx, "content_queue", tipo=kw.pop("tipo", "meme"), account_id=account_id,
                     status="programado", aprobacion="aprobado", caption="hola",
                     imagen_url=imagen_url, scheduled_datetime=venc.isoformat(),
                     plataforma=plataforma, **kw)


class FakeFB:
    def __init__(self, fallo: Exception | None = None):
        self.fallo = fallo
        self.calls: list[tuple] = []

    creds_de = staticmethod(facebook.creds_de)

    def _r(self, kind, creds, media):
        self.calls.append((kind, creds, media))
        if self.fallo:
            raise self.fallo
        return facebook.Resultado("POST9", "https://www.facebook.com/POST9")

    def publicar_foto(self, creds, url, caption):
        return self._r("foto", creds, url)

    def publicar_carrusel(self, creds, urls, caption):
        return self._r("carrusel", creds, urls)

    def publicar_video(self, creds, url, caption):
        return self._r("video", creds, url)


class FakeIG:
    def __init__(self, fallo: Exception | None = None):
        self.fallo = fallo

    def publish(self, image_url, caption, *, retries=3, creds=None):
        if self.fallo:
            raise self.fallo
        return "IGMEDIA"

    def publish_carousel(self, image_urls, caption, *, retries=3, creds=None):
        return self.publish(image_urls, caption)


def _creds(monkeypatch, slug="PENSIONMAS", ig=True, fb=True):
    if ig:
        monkeypatch.setenv(f"IG_USER_ID__{slug}", "igu")
        monkeypatch.setenv(f"IG_ACCESS_TOKEN__{slug}", "igt")
    if fb:
        monkeypatch.setenv(f"FB_PAGE_ID__{slug}", "PAGEX")
        monkeypatch.setenv(f"FB_PAGE_ACCESS_TOKEN__{slug}", "tok-fb-secreto")


def _avisos(monkeypatch) -> list[str]:
    textos: list[str] = []
    monkeypatch.setattr(publisher, "_notificar", lambda cx, qid, t: textos.append(t))
    return textos


def test_fb_foto_carrusel_y_video_con_creds_de_la_marca(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    pid = _marca(cx, "pensionmas")
    _creds(monkeypatch, ig=False)
    f1 = _fila(cx, pid, "facebook")
    f2 = _fila(cx, pid, "facebook", imagen_url=json.dumps(["https://cdn/1", "https://cdn/2"]))
    f3 = _fila(cx, pid, "facebook", imagen_url="https://cdn/r.mp4", formato="reel")
    avisos = _avisos(monkeypatch)
    fake = FakeFB()
    assert publisher.ciclo(cx, _ig=FakeIG(), _fb=fake) == 3
    assert sorted(c[0] for c in fake.calls) == ["carrusel", "foto", "video"]
    assert all(c[1] == facebook.FbCreds("PAGEX", "tok-fb-secreto") for c in fake.calls)
    for qid in (f1, f2, f3):
        fila = db.get(cx, "content_queue", qid)
        assert fila["status"] == "publicado" and fila["error"] is None
        dest = json.loads(fila["destinos_json"])["facebook"]
        assert dest["ok"] is True and dest["id"] == "POST9"
        assert dest["url"] == "https://www.facebook.com/POST9"
    assert avisos.count("📤 Publicado en Facebook: https://www.facebook.com/POST9") == 3


def test_marca_sin_fb_no_intenta_ni_usa_creds_de_gdlscene(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    pid = _marca(cx, "pensionmas")
    _creds(monkeypatch, fb=False)
    monkeypatch.setenv("FB_PAGE_ID", "PAGE_GDLSCENE")
    monkeypatch.setenv("FB_PAGE_ACCESS_TOKEN", "tok-gdlscene")
    qid = _fila(cx, pid, "facebook")
    fake = FakeFB()
    publisher.ciclo(cx, _ig=FakeIG(), _fb=fake)
    assert fake.calls == []
    fila = db.get(cx, "content_queue", qid)
    assert fila["status"] == "programado" and fila["error"] is None
    assert fila["destinos_json"] is None


def test_kill_switch_publisher_fb(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    pid = _marca(cx, "pensionmas")
    _creds(monkeypatch)
    monkeypatch.setenv("PUBLISHER_FB", "0")
    _fila(cx, pid, "facebook")
    fake = FakeFB()
    publisher.ciclo(cx, _ig=FakeIG(), _fb=fake)
    assert fake.calls == []


def test_ig_ok_y_fb_error_quedan_por_separado(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    pid = _marca(cx, "pensionmas")
    _creds(monkeypatch)
    ig_id = _fila(cx, pid, "instagram")
    fb_id = _fila(cx, pid, "facebook")
    avisos = _avisos(monkeypatch)
    error = facebook.FbError("Facebook (190): token tok-fb-secreto inválido", codigo=190)
    n = publisher.ciclo(cx, _ig=FakeIG(), _fb=FakeFB(fallo=error))
    assert n == 1
    ig = db.get(cx, "content_queue", ig_id)
    assert ig["status"] == "publicado"
    assert json.loads(ig["destinos_json"])["instagram"] == {
        **json.loads(ig["destinos_json"])["instagram"], "ok": True, "id": "IGMEDIA"}
    fbf = db.get(cx, "content_queue", fb_id)
    assert fbf["status"] == "programado" and fbf["intentos"] == 1
    dest = json.loads(fbf["destinos_json"])["facebook"]
    assert dest["ok"] is False and "190" in dest["error"]
    assert "tok-fb-secreto" not in fbf["error"] and "tok-fb-secreto" not in dest["error"]
    assert "📤 Publicado en Instagram" in avisos
    assert any(a.startswith("⚠️ Error al publicar en Facebook") for a in avisos)


def test_ig_falla_y_fb_publica_igual(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    pid = _marca(cx, "pensionmas")
    _creds(monkeypatch)
    ig_id = _fila(cx, pid, "instagram")
    fb_id = _fila(cx, pid, "facebook")
    _avisos(monkeypatch)
    n = publisher.ciclo(cx, _ig=FakeIG(fallo=RuntimeError("IG caído")), _fb=FakeFB())
    assert n == 1
    assert db.get(cx, "content_queue", fb_id)["status"] == "publicado"
    ig = db.get(cx, "content_queue", ig_id)
    assert ig["status"] == "programado"
    assert json.loads(ig["destinos_json"])["instagram"]["ok"] is False


def test_marca_sin_ig_igual_publica_fb(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    pid = _marca(cx, "pensionmas")
    _creds(monkeypatch, ig=False)
    ig_id = _fila(cx, pid, "instagram")
    fb_id = _fila(cx, pid, "facebook")
    _avisos(monkeypatch)
    assert publisher.ciclo(cx, _ig=FakeIG(), _fb=FakeFB()) == 1
    assert db.get(cx, "content_queue", fb_id)["status"] == "publicado"
    assert db.get(cx, "content_queue", ig_id)["error"] is None


def test_historias_de_fb_no_se_publican(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    pid = _marca(cx, "pensionmas")
    _creds(monkeypatch)
    _fila(cx, pid, "facebook", formato="historia")
    fake = FakeFB()
    publisher.ciclo(cx, _ig=FakeIG(), _fb=fake)
    assert fake.calls == []
