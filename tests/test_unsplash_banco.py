"""UnsplashProvider + credenciales de imagen por marca (Fase 3, Task 3)."""
from __future__ import annotations

from src import image_sources as isrc


def test_unsplash_sin_key_devuelve_vacio(monkeypatch) -> None:
    llamadas = {"n": 0}

    def _get(*a, **kw):
        llamadas["n"] += 1
        raise AssertionError("no debería pegarle a la red sin key")

    monkeypatch.setattr(isrc.requests, "get", _get)
    out = isrc.UnsplashProvider().buscar("coffee")
    assert out == []
    assert llamadas["n"] == 0


def test_unsplash_parsea_resultados_y_credito(monkeypatch) -> None:
    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [
                {"urls": {"regular": "https://img/1.jpg"},
                 "user": {"name": "Ana"}},
                {"urls": {"regular": "https://img/2.jpg"},
                 "user": {"name": "Luis"}},
            ]}

    llamadas = {}

    def _get(url, **kw):
        llamadas["url"] = url
        llamadas["params"] = kw.get("params")
        llamadas["timeout"] = kw.get("timeout")
        return _Resp()

    monkeypatch.setattr(isrc.requests, "get", _get)
    out = isrc.UnsplashProvider(access_key="k123").buscar("coffee", n=2)
    assert len(out) == 2
    assert out[0].ruta_o_url == "https://img/1.jpg"
    assert out[0].source == "unsplash"
    assert out[0].credito == "Ana / Unsplash"
    assert out[1].credito == "Luis / Unsplash"
    assert llamadas["params"]["client_id"] == "k123"
    assert llamadas["params"]["query"] == "coffee"
    assert llamadas["timeout"] == 15


def test_unsplash_error_http_devuelve_vacio_sin_lanzar(monkeypatch, capsys) -> None:
    def _get(*a, **kw):
        raise isrc.requests.RequestException("401 unauthorized clave=secreta123")

    monkeypatch.setattr(isrc.requests, "get", _get)
    out = isrc.UnsplashProvider(access_key="secreta123").buscar("coffee")
    assert out == []
    salida = capsys.readouterr()
    assert "secreta123" not in salida.out
    assert "secreta123" not in salida.err


def test_providers_default_con_creds_inyecta_unsplash_key(monkeypatch) -> None:
    provs = isrc.providers_default(creds={"UNSPLASH_ACCESS_KEY": "abc"})
    assert isinstance(provs["unsplash"], isrc.UnsplashProvider)
    assert provs["unsplash"].access_key == "abc"


def test_providers_default_sin_creds_unsplash_sin_key() -> None:
    provs = isrc.providers_default()
    assert provs["unsplash"].access_key is None


def test_providers_default_creds_pexels_key_de_marca_gana_a_global(monkeypatch) -> None:
    monkeypatch.setattr(isrc.config, "PEXELS_API_KEY", "global123")
    provs = isrc.providers_default(creds={"PEXELS_API_KEY": "marca456"})
    assert provs["pexels"].api_key == "marca456"


def test_pexels_provider_sin_arg_usa_config_global(monkeypatch) -> None:
    monkeypatch.setattr(isrc.config, "PEXELS_API_KEY", "global123")
    assert isrc.PexelsProvider().api_key is None  # se resuelve en buscar()


def test_pexels_provider_con_arg_gana_a_config_global(monkeypatch) -> None:
    monkeypatch.setattr(isrc.config, "PEXELS_API_KEY", "global123")

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"photos": []}

    llamadas = {}

    def _get(url, **kw):
        llamadas["headers"] = kw.get("headers")
        return _Resp()

    monkeypatch.setattr(isrc.requests, "get", _get)
    isrc.PexelsProvider(api_key="marca456").buscar("coffee")
    assert llamadas["headers"]["Authorization"] == "marca456"


def test_providers_default_firma_compat_sin_creds() -> None:
    """Llamadas existentes sin `creds` siguen funcionando igual."""
    provs = isrc.providers_default(cx=None, slug=None)
    assert set(provs) == {"pexels", "pinterest", "unsplash"}
