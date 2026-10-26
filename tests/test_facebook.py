"""src/facebook.py contra un Graph API falso: foto, carrusel, video (simple y
reanudable), errores 190/200 sin reintento y reintento en transitorios."""
from __future__ import annotations

import json

import pytest

from src import facebook as fb

CREDS = fb.FbCreds("PAGE1", "tok-pagina")


class _Resp:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> dict:
        return self._body


class _Graph:
    """Responde en orden la lista `respuestas` y registra cada llamada."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, metodo, url, **kw):
        self.calls.append((metodo, url, kw))
        status, body = self.respuestas.pop(0)
        return _Resp(status, body)


@pytest.fixture()
def graph(monkeypatch):
    dormidas: list[float] = []
    monkeypatch.setattr(fb, "_dormir", dormidas.append)

    def instalar(*respuestas):
        g = _Graph(*respuestas)
        g.dormidas = dormidas
        monkeypatch.setattr(fb.requests, "request", g)
        return g
    return instalar


def test_foto_por_url(graph) -> None:
    g = graph((200, {"id": "F1", "post_id": "PAGE1_P1"}))
    res = fb.publicar_foto(CREDS, "https://cdn/x.png", "hola @melaque")
    metodo, url, kw = g.calls[0]
    assert metodo == "POST" and url.endswith(f"/{fb.API_VERSION}/PAGE1/photos")
    assert kw["data"]["url"] == "https://cdn/x.png"
    assert kw["data"]["message"] == "hola melaque"
    assert kw["data"]["access_token"] == "tok-pagina"
    assert res == fb.Resultado("PAGE1_P1", "https://www.facebook.com/PAGE1_P1")


def test_carrusel_fotos_sin_publicar_y_feed(graph) -> None:
    g = graph((200, {"id": "A"}), (200, {"id": "B"}), (200, {"id": "PAGE1_POST"}))
    res = fb.publicar_carrusel(CREDS, ["https://cdn/1.png", "https://cdn/2.png"], "pie")
    assert [c[2]["data"]["published"] for c in g.calls[:2]] == ["false", "false"]
    feed = g.calls[2]
    assert feed[1].endswith("/PAGE1/feed")
    assert json.loads(feed[2]["data"]["attached_media[0]"]) == {"media_fbid": "A"}
    assert json.loads(feed[2]["data"]["attached_media[1]"]) == {"media_fbid": "B"}
    assert res.id == "PAGE1_POST"


def test_video_por_url_usa_file_url(graph) -> None:
    g = graph((200, {"id": "V1"}))
    res = fb.publicar_video(CREDS, "https://cdn/r.mp4", "reel")
    data = g.calls[0][2]["data"]
    assert g.calls[0][1].endswith("/PAGE1/videos")
    assert data["file_url"] == "https://cdn/r.mp4" and data["description"] == "reel"
    assert res == fb.Resultado("V1", "https://www.facebook.com/PAGE1/videos/V1")


def test_video_local_chico_va_en_source(graph, tmp_path) -> None:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x" * 10)
    g = graph((200, {"id": "V2"}))
    fb.publicar_video(CREDS, str(video), "pie")
    assert "source" in g.calls[0][2]["files"]


def test_video_reanudable_start_transfer_finish(graph, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(fb, "VIDEO_SIMPLE_MAX", 5)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0123456789")
    g = graph(
        (200, {"upload_session_id": "S", "video_id": "V3", "start_offset": "0", "end_offset": "6"}),
        (200, {"start_offset": "6", "end_offset": "10"}),
        (200, {"start_offset": "10", "end_offset": "10"}),
        (200, {"success": True}),
    )
    res = fb.publicar_video(CREDS, str(video), "pie")
    fases = [c[2]["data"]["upload_phase"] for c in g.calls]
    assert fases == ["start", "transfer", "transfer", "finish"]
    assert g.calls[0][2]["data"]["file_size"] == "10"
    trozos = [c[2]["files"]["video_file_chunk"][1] for c in g.calls[1:3]]
    assert trozos == [b"012345", b"6789"]
    assert g.calls[3][2]["data"]["description"] == "pie"
    assert res.id == "V3"


def test_190_token_invalido_no_reintenta(graph) -> None:
    g = graph((400, {"error": {"code": 190, "message": "Invalid OAuth access token"}}))
    with pytest.raises(fb.FbError) as e:
        fb.publicar_foto(CREDS, "https://cdn/x.png", "x")
    assert e.value.codigo == 190 and "inválido o expiró" in str(e.value)
    assert len(g.calls) == 1 and g.dormidas == []


def test_200_sin_permiso_no_reintenta(graph) -> None:
    g = graph((403, {"error": {"code": 200, "message": "Permissions error"}}))
    with pytest.raises(fb.FbError) as e:
        fb.publicar_foto(CREDS, "https://cdn/x.png", "x")
    assert e.value.codigo == 200 and "pages_manage_posts" in str(e.value)
    assert len(g.calls) == 1


def test_transitorio_reintenta_con_backoff(graph) -> None:
    g = graph((400, {"error": {"code": 2, "message": "Service temporarily unavailable"}}),
              (500, {"error": {"message": "boom"}}),
              (200, {"id": "F", "post_id": "OK"}))
    res = fb.publicar_foto(CREDS, "https://cdn/x.png", "x")
    assert res.id == "OK" and len(g.calls) == 3 and g.dormidas == [1, 2]


def test_transitorio_agota_reintentos(graph) -> None:
    g = graph(*[(400, {"error": {"code": 17, "message": "rate"}})] * fb.REINTENTOS)
    with pytest.raises(fb.FbError) as e:
        fb.publicar_foto(CREDS, "https://cdn/x.png", "x")
    assert e.value.transitorio and len(g.calls) == fb.REINTENTOS


def test_sin_creds_no_toca_la_red(graph) -> None:
    g = graph()
    with pytest.raises(fb.SinCredencialesFB, match="melaquecapital"):
        fb.creds_de({"FB_PAGE_ID": "", "FB_PAGE_ACCESS_TOKEN": "t"}, "melaquecapital")
    with pytest.raises(fb.SinCredencialesFB):
        fb.publish("https://cdn/x.png", "x")  # sin creds: ya no hay fallback global
    assert g.calls == []
