"""Fuente de historias `reddit`: parseo del RSS, filtros y validación de config."""
from __future__ import annotations

import pytest

from src import db, fuentes, topics


class _Resp:
    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _rss(*entradas: str) -> str:
    cuerpo = "".join(entradas)
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{cuerpo}</feed>'


def _entry(titulo: str, contenido: str, href: str = "https://reddit.com/x") -> str:
    return (f"<entry><title>{titulo}</title>"
            f'<content type="html">{contenido}</content>'
            f'<link href="{href}"/><published>2026-10-01T00:00:00+00:00</published>'
            "</entry>")


_LARGO = " ".join(["palabra"] * 80)


def test_fetch_reddit_parsea_entradas_y_limpia_html() -> None:
    xml = _rss(_entry("Mi historia",
                      f"&lt;p&gt;{_LARGO}&lt;/p&gt;&lt;br&gt;submitted by &lt;a&gt;yo&lt;/a&gt;"))
    items = topics.fetch_reddit("/r/stories/top/.rss", _get=lambda *a, **k: _Resp(xml))
    assert len(items) == 1
    assert items[0]["titulo"] == "Mi historia"
    assert items[0]["url"] == "https://reddit.com/x"
    # ni tags ni el pie "submitted by" llegan al texto que va a narrarse
    assert "<" not in items[0]["resumen"]
    assert "submitted by" not in items[0]["resumen"]


def test_fetch_reddit_descarta_cortas_y_borradas() -> None:
    xml = _rss(_entry("Corta", "tres palabras nada mas"),
               _entry("Borrada", "[deleted]"),
               _entry("Buena", _LARGO))
    items = topics.fetch_reddit("/r/stories/top/.rss", min_palabras=60,
                                _get=lambda *a, **k: _Resp(xml))
    assert [i["titulo"] for i in items] == ["Buena"]


def test_fetch_reddit_rechaza_ruta_que_no_sea_path_de_subreddit() -> None:
    """Una URL completa o un path raro NO se consulta: ni sale la petición."""
    vistas: list[str] = []

    def _get(url, **kw):
        vistas.append(url)
        return _Resp(_rss())

    for mala in ("https://evil.example.com/r/stories/.rss", "/etc/passwd",
                 "//evil.com/r/stories/.rss", "r/stories/.rss", ""):
        assert topics.fetch_reddit(mala, _get=_get) == []
    assert vistas == []

    # y una ruta legítima sí consulta reddit.com, con el host fijado aquí
    topics.fetch_reddit("/r/stories/top/.rss?t=all", _get=_get)
    assert vistas == ["https://www.reddit.com/r/stories/top/.rss?t=all"]


def test_fetch_reddit_tolera_fallas_sin_reventar() -> None:
    def _boom(*a, **k):
        raise ConnectionError("red caída")

    assert topics.fetch_reddit("/r/stories/.rss", _get=_boom) == []
    # redirect (Reddit bloqueando) y XML basura también dan [] y no excepción
    assert topics.fetch_reddit("/r/stories/.rss", _get=lambda *a, **k: _Resp("", 302)) == []
    assert topics.fetch_reddit("/r/stories/.rss", _get=lambda *a, **k: _Resp("no es xml")) == []


def test_fetch_reddit_reintenta_el_429_y_luego_rinde() -> None:
    llamadas = {"n": 0}
    xml = _rss(_entry("Buena", _LARGO))

    def _get(*a, **k):
        llamadas["n"] += 1
        return _Resp(xml) if llamadas["n"] > 1 else _Resp("", 429)

    items = topics.fetch_reddit("/r/stories/.rss", _get=_get)
    assert llamadas["n"] == 2
    assert [i["titulo"] for i in items] == ["Buena"]


# --- registro de la fuente en `brand_sources` ---------------------------------

def _cuenta(cx) -> int:
    return db.insert(cx, "accounts", slug="shitbook", ig_handle="shit.book",
                     nombre="shit.book", ciudad="Guadalajara")


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    con = db.connect(str(tmp_path / "t.db"))
    db.init_db(con)
    yield con
    con.close()


def test_crear_fuente_reddit_valida_rutas(cx) -> None:
    aid = _cuenta(cx)
    sid = fuentes.crear(cx, aid, "info", "reddit",
                        {"rutas": ["/r/copypasta_es/top/.rss?t=all"], "min_palabras": 80})
    assert db.get(cx, "brand_sources", sid)["provider"] == "reddit"

    for malo in ({}, {"rutas": []}, {"rutas": ["sin-slash"]},
                 {"rutas": ["https://evil.com/r/stories"]}, {"rutas": [123]},
                 {"rutas": ["/r/stories/.rss"], "min_palabras": 0}):
        with pytest.raises(ValueError):
            fuentes.crear(cx, aid, "info", "reddit", malo)


def test_reddit_es_provider_info_valido(cx) -> None:
    assert "reddit" in fuentes.PROVIDERS_INFO
    # y sigue rechazándose como fuente de imagen
    with pytest.raises(ValueError):
        fuentes.crear(cx, _cuenta(cx), "imagen", "reddit", {"rutas": ["/r/stories/.rss"]})


def test_guardar_dedupe_por_url(cx) -> None:
    aid = _cuenta(cx)
    items = [{"titulo": "A", "resumen": _LARGO, "url": "https://r/1"},
             {"titulo": "A otra vez", "resumen": _LARGO, "url": "https://r/1"}]
    assert topics.guardar(cx, aid, items, "reddit") == 1
    assert topics.guardar(cx, aid, items, "reddit") == 0
