"""Temas sugeridos (`topic_suggestions`): fetch_rss/fetch_newsapi, guardar, listar, descartar."""
from __future__ import annotations

import pytest
import requests

from src import db, topics


@pytest.fixture()
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    db.insert(c, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    yield c
    c.close()


# ---------- fetch_rss ----------

_RSS2 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Feed de prueba</title>
<item>
  <title>Nota uno</title>
  <description>&lt;p&gt;Resumen &lt;b&gt;con html&lt;/b&gt; y espacios   raros.&lt;/p&gt;</description>
  <link>https://ejemplo.com/uno</link>
  <pubDate>Mon, 17 Aug 2026 10:00:00 GMT</pubDate>
</item>
<item>
  <title>Nota dos</title>
  <description>Resumen simple</description>
  <link>https://ejemplo.com/dos</link>
  <pubDate>Mon, 17 Aug 2026 11:00:00 GMT</pubDate>
</item>
</channel></rss>"""

_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Feed atom</title>
<entry>
  <title>Entrada uno</title>
  <summary>Resumen atom</summary>
  <link href="https://ejemplo.com/atom-uno" />
  <published>2026-08-17T10:00:00Z</published>
</entry>
</feed>"""


class _FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


# ---------- url_segura (H4: SSRF) ----------

def test_url_segura_acepta_https_normal() -> None:
    assert topics.url_segura("https://ejemplo.com/feed.xml") is True
    assert topics.url_segura("http://ejemplo.com/feed.xml") is True


def test_url_segura_rechaza_esquema_no_http() -> None:
    assert topics.url_segura("ftp://ejemplo.com/feed.xml") is False
    assert topics.url_segura("file:///etc/passwd") is False


def test_url_segura_rechaza_loopback_link_local_y_privados() -> None:
    assert topics.url_segura("http://127.0.0.1") is False
    assert topics.url_segura("http://127.0.0.1/x") is False
    assert topics.url_segura("http://169.254.169.254/x") is False  # metadata cloud
    assert topics.url_segura("http://localhost/x") is False
    assert topics.url_segura("http://10.0.0.5/x") is False
    assert topics.url_segura("http://192.168.1.1/x") is False


def test_url_segura_acepta_hostname_no_ip_sin_resolver_dns() -> None:
    assert topics.url_segura("https://noticias.ejemplo.com/rss") is True


def test_url_segura_rechaza_formas_alternativas_de_loopback() -> None:
    """Re-review: `ipaddress.ip_address` solo entiende la notación decimal
    con puntos — rechazaba "2130706433" (decimal), "0x7f000001" (hex),
    "127.1" (short) y "0x0"/"0" como ValueError, y como no eran IPs
    `url_segura` las trataba como hostname normal y las dejaba pasar. Todas
    resuelven a loopback/unspecified vía `socket.inet_aton` (y por lo tanto
    en el resolver real de cualquier cliente HTTP)."""
    assert topics.url_segura("http://2130706433/") is False  # 127.0.0.1 decimal
    assert topics.url_segura("http://0x7f000001/") is False  # 127.0.0.1 hex
    assert topics.url_segura("http://127.1/") is False  # 127.0.0.1 short
    assert topics.url_segura("http://0/") is False  # 0.0.0.0
    assert topics.url_segura("http://0x0/") is False  # 0.0.0.0 hex


def test_fetch_rss_bloquea_url_insegura_sin_llamar_a_get() -> None:
    llamado = []

    def _get(url, **kw):
        llamado.append(url)
        return _FakeResp(_RSS2)

    assert topics.fetch_rss("http://127.0.0.1/feed.xml", _get=_get) == []
    assert llamado == []


def test_fetch_rss_no_sigue_redirects() -> None:
    """Re-review: una URL pública que pasa `url_segura` podría 302 a un host
    interno (metadata cloud, etc.) — `fetch_rss` no debe perseguir el
    Location, ni hacer una segunda request."""
    llamadas = []

    class _RedirResp:
        status_code = 302
        headers = {"Location": "http://169.254.169.254/x"}

    def _get(url, **kw):
        llamadas.append(url)
        assert kw.get("allow_redirects") is False
        return _RedirResp()

    assert topics.fetch_rss("https://ejemplo.com/feed.xml", _get=_get) == []
    assert llamadas == ["https://ejemplo.com/feed.xml"]  # nunca siguió al Location


def test_fetch_rss_parsea_rss2() -> None:
    items = topics.fetch_rss("https://ejemplo.com/feed.xml",
                             _get=lambda url, **kw: _FakeResp(_RSS2))
    assert len(items) == 2
    assert items[0]["titulo"] == "Nota uno"
    assert items[0]["resumen"] == "Resumen con html y espacios raros."
    assert items[0]["url"] == "https://ejemplo.com/uno"
    assert items[0]["publicado_en"] == "Mon, 17 Aug 2026 10:00:00 GMT"
    assert items[1]["titulo"] == "Nota dos"


def test_fetch_rss_parsea_atom() -> None:
    items = topics.fetch_rss("https://ejemplo.com/atom.xml",
                             _get=lambda url, **kw: _FakeResp(_ATOM))
    assert len(items) == 1
    assert items[0]["titulo"] == "Entrada uno"
    assert items[0]["resumen"] == "Resumen atom"
    assert items[0]["url"] == "https://ejemplo.com/atom-uno"
    assert items[0]["publicado_en"] == "2026-08-17T10:00:00Z"


def test_fetch_rss_resumen_se_trunca_a_500() -> None:
    largo = "x" * 900
    xml = f"""<rss version="2.0"><channel><item>
    <title>Larga</title><description>{largo}</description>
    <link>https://ejemplo.com/larga</link>
    </item></channel></rss>"""
    items = topics.fetch_rss("https://ejemplo.com/feed.xml",
                             _get=lambda url, **kw: _FakeResp(xml))
    assert len(items[0]["resumen"]) == 500


def test_fetch_rss_xml_malformado_devuelve_lista_vacia() -> None:
    items = topics.fetch_rss("https://ejemplo.com/roto.xml",
                             _get=lambda url, **kw: _FakeResp("<rss><channel>"))
    assert items == []


def test_fetch_rss_error_de_red_devuelve_lista_vacia() -> None:
    def _get(url, **kw):
        raise ConnectionError("no hay red")
    items = topics.fetch_rss("https://ejemplo.com/feed.xml", _get=_get)
    assert items == []


def test_fetch_rss_formato_desconocido_devuelve_lista_vacia() -> None:
    items = topics.fetch_rss("https://ejemplo.com/feed.xml",
                             _get=lambda url, **kw: _FakeResp("<algo/>"))
    assert items == []


# ---------- fetch_newsapi ----------

class _FakeRespJson:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def test_fetch_newsapi_llama_al_endpoint_correcto_y_normaliza() -> None:
    capturado = {}

    def _get(url, params=None, **kw):
        capturado["url"] = url
        capturado["params"] = params
        return _FakeRespJson({"status": "ok", "articles": [
            {"title": "Título", "description": "Desc", "url": "https://x.com/a",
             "publishedAt": "2026-08-17T10:00:00Z"},
        ]})

    items = topics.fetch_newsapi("cafeterías", "clave-123", _get=_get)

    assert capturado["url"] == "https://newsapi.org/v2/everything"
    assert capturado["params"]["q"] == "cafeterías"
    assert capturado["params"]["language"] == "es"
    assert capturado["params"]["apiKey"] == "clave-123"
    assert len(items) == 1
    assert items[0] == {"titulo": "Título", "resumen": "Desc",
                        "url": "https://x.com/a", "publicado_en": "2026-08-17T10:00:00Z"}


def test_fetch_newsapi_top_20() -> None:
    articulos = [{"title": f"n{i}", "description": "", "url": f"https://x.com/{i}",
                  "publishedAt": None} for i in range(30)]

    def _get(url, params=None, **kw):
        return _FakeRespJson({"status": "ok", "articles": articulos})

    items = topics.fetch_newsapi("q", "k", _get=_get)
    assert len(items) == 20


def test_fetch_newsapi_error_devuelve_lista_vacia() -> None:
    def _get(url, params=None, **kw):
        raise ConnectionError("caída")
    assert topics.fetch_newsapi("q", "k", _get=_get) == []


class _FakeHTTPResp:
    """Respuesta HTTP fake cuya `.url` (como en `requests` real) trae la key
    en query string — exactamente el vector de fuga que hay que evitar."""
    def __init__(self, status_code, url):
        self.status_code = status_code
        self.url = url


def test_fetch_newsapi_http_error_no_filtra_la_key_al_log(capsys) -> None:
    resp = _FakeHTTPResp(500, "https://newsapi.org/v2/everything?apiKey=key_secreta_9")

    def _get(url, params=None, **kw):
        raise requests.HTTPError("500 Server Error", response=resp)

    items = topics.fetch_newsapi("q", "key_secreta_9", _get=_get)

    assert items == []
    salida = capsys.readouterr().out
    assert "key_secreta_9" not in salida
    assert "500" in salida


def test_fetch_newsapi_error_generico_redacta_la_key_del_mensaje(capsys) -> None:
    def _get(url, params=None, **kw):
        raise ConnectionError("fallo hablando con key_secreta_9 en el mensaje")

    items = topics.fetch_newsapi("q", "key_secreta_9", _get=_get)

    assert items == []
    salida = capsys.readouterr().out
    assert "key_secreta_9" not in salida
    assert "***" in salida


def test_fetch_newsapi_estricto_relanza_runtime_error_redactado(capsys) -> None:
    resp = _FakeHTTPResp(401, "https://newsapi.org/v2/everything?apiKey=key_secreta_9")

    def _get(url, params=None, **kw):
        raise requests.HTTPError("401", response=resp)

    with pytest.raises(RuntimeError, match="401"):
        topics.fetch_newsapi("q", "key_secreta_9", _get=_get, estricto=True)

    salida = capsys.readouterr().out
    assert "key_secreta_9" not in salida


def test_fetch_newsapi_estricto_sin_error_devuelve_items_normal() -> None:
    def _get(url, params=None, **kw):
        return _FakeRespJson({"status": "ok", "articles": [
            {"title": "T", "description": "d", "url": "https://x.com/1",
             "publishedAt": None},
        ]})

    items = topics.fetch_newsapi("q", "k", _get=_get, estricto=True)
    assert len(items) == 1


# ---------- guardar / listar / descartar ----------

def test_guardar_dedup_por_url(cx) -> None:
    items = [
        {"titulo": "Uno", "resumen": "r", "url": "https://x.com/1", "publicado_en": None},
        {"titulo": "Dos", "resumen": "r", "url": "https://x.com/2", "publicado_en": None},
    ]
    n1 = topics.guardar(cx, 2, items, "rss")
    assert n1 == 2
    n2 = topics.guardar(cx, 2, items, "rss")  # mismas URLs, misma cuenta
    assert n2 == 0
    filas = db.rows(cx, "SELECT * FROM topic_suggestions WHERE account_id = 2")
    assert len(filas) == 2


def test_guardar_misma_url_en_otra_cuenta_no_es_duplicado(cx) -> None:
    otra_id = db.insert(cx, "accounts", slug="otra", ig_handle="@o", nombre="O", ciudad="CDMX")
    items = [{"titulo": "Uno", "resumen": "r", "url": "https://x.com/1", "publicado_en": None}]
    assert topics.guardar(cx, 2, items, "rss") == 1
    assert topics.guardar(cx, otra_id, items, "rss") == 1


def test_guardar_ignora_items_sin_titulo(cx) -> None:
    items = [{"titulo": "", "resumen": "r", "url": "https://x.com/1", "publicado_en": None}]
    assert topics.guardar(cx, 2, items, "rss") == 0


def test_listar_excluye_descartados_y_usados_por_default(cx) -> None:
    items = [
        {"titulo": "Uno", "resumen": "r", "url": "https://x.com/1", "publicado_en": None},
        {"titulo": "Dos", "resumen": "r", "url": "https://x.com/2", "publicado_en": None},
        {"titulo": "Tres", "resumen": "r", "url": "https://x.com/3", "publicado_en": None},
    ]
    topics.guardar(cx, 2, items, "rss")
    filas = db.rows(cx, "SELECT * FROM topic_suggestions WHERE account_id = 2 ORDER BY id")
    topics.descartar(cx, filas[0]["id"])
    db.update(cx, "topic_suggestions", filas[1]["id"], usado_en_queue_id=99)

    activos = topics.listar(cx, 2)
    assert len(activos) == 1
    assert activos[0]["titulo"] == "Tres"

    con_usados = topics.listar(cx, 2, incluir_usados=True)
    assert {f["titulo"] for f in con_usados} == {"Dos", "Tres"}


def test_listar_aisla_por_cuenta(cx) -> None:
    otra_id = db.insert(cx, "accounts", slug="otra", ig_handle="@o", nombre="O", ciudad="CDMX")
    topics.guardar(cx, 2, [{"titulo": "A", "url": "https://x.com/a"}], "rss")
    topics.guardar(cx, otra_id, [{"titulo": "B", "url": "https://x.com/b"}], "rss")
    assert [f["titulo"] for f in topics.listar(cx, 2)] == ["A"]
