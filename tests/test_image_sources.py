"""Sourcing multi-fuente: cascada de providers, dedup y providers locales."""
from __future__ import annotations

from src import db
from src import image_sources as isrc


class _Fake:
    def __init__(self, nombre, resultados):
        self.nombre = nombre
        self.resultados = resultados  # hint → list[ImagenCandidata]
        self.llamadas = []

    def buscar(self, hint, n=3):
        self.llamadas.append(hint)
        return self.resultados.get(hint, [])


def _cand(ruta, source="pexels"):
    return isrc.ImagenCandidata(ruta_o_url=ruta, source=source)


def test_resolver_usa_primer_provider_con_resultado() -> None:
    p1 = _Fake("banco", {})
    p2 = _Fake("pexels", {"cafe": [_cand("/tmp/a.jpg")]})
    out = isrc.resolver(["cafe"], ["banco", "pexels"],
                        providers={"banco": p1, "pexels": p2})
    assert out[0].ruta_o_url == "/tmp/a.jpg"
    assert p1.llamadas == ["cafe"]  # se intentó primero


def test_resolver_none_si_nadie_tiene() -> None:
    out = isrc.resolver(["x"], ["pexels"], providers={"pexels": _Fake("pexels", {})})
    assert out == [None]


def test_resolver_no_repite_imagen_en_el_set() -> None:
    p = _Fake("pexels", {"a": [_cand("/tmp/1.jpg"), _cand("/tmp/2.jpg")],
                         "b": [_cand("/tmp/1.jpg"), _cand("/tmp/3.jpg")]})
    out = isrc.resolver(["a", "b"], ["pexels"], providers={"pexels": p})
    assert out[0].ruta_o_url == "/tmp/1.jpg"
    assert out[1].ruta_o_url == "/tmp/3.jpg"  # la 1 ya estaba usada


def test_resolver_fuente_desconocida_se_ignora() -> None:
    p = _Fake("pexels", {"a": [_cand("/tmp/1.jpg")]})
    out = isrc.resolver(["a"], ["noexiste", "pexels"], providers={"pexels": p})
    assert out[0].ruta_o_url == "/tmp/1.jpg"


def test_provider_que_lanza_no_tumba_resolver() -> None:
    class _Roto:
        nombre = "roto"

        def buscar(self, hint, n=3):
            raise RuntimeError("boom")

    p = _Fake("pexels", {"a": [_cand("/tmp/1.jpg")]})
    out = isrc.resolver(["a"], ["roto", "pexels"],
                        providers={"roto": _Roto(), "pexels": p})
    assert out[0].ruta_o_url == "/tmp/1.jpg"


def _db_con_fotos(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial",
                    activa=1)
    db.insert(cx, "photos", band_id=bid, path="/tmp/kabala1.jpg",
              source_post_id="p1", usable_meme=1, usada=0, descartada=0,
              nitidez=90.0)
    db.insert(cx, "photos", band_id=bid, path="/tmp/kabala2.jpg",
              source_post_id="p2", usable_meme=1, usada=1, descartada=0,
              nitidez=99.0)  # usada: no debe salir
    return cx, bid


def test_banco_provider_matchea_por_nombre(tmp_path) -> None:
    cx, _ = _db_con_fotos(tmp_path)
    out = isrc.BancoProvider(cx).buscar("kabala")
    assert [c.ruta_o_url for c in out] == ["/tmp/kabala1.jpg"]
    assert out[0].source == "banco"


def test_banco_provider_sin_match(tmp_path) -> None:
    cx, _ = _db_con_fotos(tmp_path)
    assert isrc.BancoProvider(cx).buscar("mountain sunset") == []


def test_covers_provider_matchea_titulo(tmp_path, monkeypatch) -> None:
    cx, bid = _db_con_fotos(tmp_path)
    db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-08-01",
              titulo="Disco Lunar (álbum)", cover_url="https://cdn/x.jpg")
    monkeypatch.setattr(isrc.covers, "asegurar_cover",
                        lambda url, **kw: tmp_path / "cover.jpg")
    out = isrc.CoversProvider(cx).buscar("lunar")
    assert out and out[0].source == "covers"


def test_descargar_cache_valida_magia(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(isrc, "SOURCING_DIR", tmp_path)

    class _Resp:
        status_code = 200
        content = b"\xff\xd8\xff" + b"x" * 100  # JPEG mágico

        def raise_for_status(self):
            pass

    monkeypatch.setattr(isrc.requests, "get", lambda *a, **kw: _Resp())
    p = isrc._descargar_cache("https://img/x.jpg")
    assert p is not None and p.exists()
    # segunda llamada: cache hit, sin red
    monkeypatch.setattr(isrc.requests, "get",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("red")))
    assert isrc._descargar_cache("https://img/x.jpg") == p


def test_descargar_cache_rechaza_no_imagen(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(isrc, "SOURCING_DIR", tmp_path)

    class _Resp:
        status_code = 200
        content = b"<html>not found</html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(isrc.requests, "get", lambda *a, **kw: _Resp())
    assert isrc._descargar_cache("https://img/y.jpg") is None


def test_pexels_sin_api_key_devuelve_vacio(monkeypatch) -> None:
    monkeypatch.setattr(isrc.config, "PEXELS_API_KEY", None)
    assert isrc.PexelsProvider().buscar("coffee") == []


def test_pexels_parsea_respuesta(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(isrc.config, "PEXELS_API_KEY", "k123")
    monkeypatch.setattr(isrc, "SOURCING_DIR", tmp_path)

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"photos": [
                {"src": {"large2x": "https://img/1.jpg"},
                 "photographer": "Ana"},
                {"src": {"large2x": "https://img/2.jpg"},
                 "photographer": "Luis"},
            ]}

    llamadas = {}

    def _get(url, **kw):
        if "api.pexels.com" in url:
            llamadas["headers"] = kw.get("headers")
            return _Resp()
        # descarga de la imagen

        class _Img:
            status_code = 200
            content = b"\xff\xd8\xff" + b"x" * 50

            def raise_for_status(self):
                pass

        return _Img()

    monkeypatch.setattr(isrc.requests, "get", _get)
    out = isrc.PexelsProvider().buscar("coffee", n=2)
    assert len(out) == 2
    assert out[0].source == "pexels"
    assert out[0].credito == "Ana"
    assert out[0].ruta_o_url.endswith(".jpg")  # ruta local del cache
    assert llamadas["headers"]["Authorization"] == "k123"


def test_pexels_error_http_devuelve_vacio(monkeypatch) -> None:
    monkeypatch.setattr(isrc.config, "PEXELS_API_KEY", "k123")

    def _get(url, **kw):
        raise isrc.requests.RequestException("timeout")

    monkeypatch.setattr(isrc.requests, "get", _get)
    assert isrc.PexelsProvider().buscar("coffee") == []


def test_pinterest_apagado_por_flag(monkeypatch) -> None:
    monkeypatch.setattr(isrc.config, "SOURCING_PINTEREST", False)
    assert isrc.PinterestProvider().buscar("coffee") == []


def test_pinterest_parsea_resultados(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(isrc.config, "SOURCING_PINTEREST", True)
    monkeypatch.setattr(isrc, "SOURCING_DIR", tmp_path)

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"resource_response": {"data": {"results": [
                {"images": {"orig": {"url": "https://i.pinimg.com/a.jpg"}}},
            ]}}}

    def _get(url, **kw):
        if "pinterest.com" in url:
            return _Resp()

        class _Img:
            status_code = 200
            content = b"\xff\xd8\xff" + b"x" * 50

            def raise_for_status(self):
                pass

        return _Img()

    monkeypatch.setattr(isrc.requests, "get", _get)
    out = isrc.PinterestProvider().buscar("coffee")
    assert out and out[0].source == "pinterest"


def test_pinterest_circuit_breaker(monkeypatch) -> None:
    """Tras un fallo, el provider queda muerto en la corrida: no reintenta."""
    monkeypatch.setattr(isrc.config, "SOURCING_PINTEREST", True)
    contador = {"n": 0}

    def _get(url, **kw):
        contador["n"] += 1
        raise isrc.requests.RequestException("403")

    monkeypatch.setattr(isrc.requests, "get", _get)
    p = isrc.PinterestProvider()
    assert p.buscar("a") == []
    assert p.buscar("b") == []  # segundo hint: NO vuelve a pegarle a la red
    assert contador["n"] == 1


def test_pinterest_circuit_breaker_con_resultados_malformados(monkeypatch) -> None:
    """Un item no-dict en 'results' debe apagar el provider, no escapar como excepción."""
    monkeypatch.setattr(isrc.config, "SOURCING_PINTEREST", True)
    contador = {"n": 0}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"resource_response": {"data": {"results": [
                {"images": None}, "basura",
            ]}}}

    def _get(url, **kw):
        contador["n"] += 1
        return _Resp()

    monkeypatch.setattr(isrc.requests, "get", _get)
    p = isrc.PinterestProvider()
    assert p.buscar("a") == []
    assert p.buscar("b") == []  # segunda llamada: NO pega a la red
    assert contador["n"] == 1


def test_banco_provider_nombre_de_banda_contenido_en_hint(tmp_path) -> None:
    """Los hints del LLM traen el sujeto + contexto ("kabala band on stage"):
    el provider debe matchear cuando el NOMBRE está contenido en el hint."""
    cx, _ = _db_con_fotos(tmp_path)
    out = isrc.BancoProvider(cx).buscar("kabala band on stage")
    assert [c.ruta_o_url for c in out] == ["/tmp/kabala1.jpg"]


def test_banco_provider_nombre_corto_sin_falso_positivo(tmp_path) -> None:
    """Nombres de <4 chars ("edu") no deben matchear por estar contenidos
    en palabras del hint ("education")."""
    cx, _ = _db_con_fotos(tmp_path)
    bid = db.insert(cx, "bands", nombre="edu", ig_handle="edu_mx", activa=1)
    db.insert(cx, "photos", band_id=bid, path="/tmp/edu1.jpg",
              source_post_id="e1", usable_meme=1, usada=0, descartada=0,
              nitidez=80.0)
    assert isrc.BancoProvider(cx).buscar("coffee education poster") == []


# --- CarpetaProvider: fotos propias de la marca en data/brands/<slug>/fotos ---

def _carpeta_marca(tmp_path):
    raiz = tmp_path / "fotos"
    for rel in ("brand/bay-sunset.jpg", "brand/aerial-palms.jpg",
                "melaque/pier.jpg", "sayula/church.png", "notas.txt"):
        p = raiz / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return raiz


def test_carpeta_matchea_tokens_del_hint_contra_ruta(tmp_path) -> None:
    prov = isrc.CarpetaProvider(_carpeta_marca(tmp_path))
    out = prov.buscar("melaque pier at golden hour", n=2)
    assert out and out[0].ruta_o_url.endswith("melaque/pier.jpg")
    assert out[0].source == "carpeta"


def test_carpeta_prefiere_mas_tokens_coincidentes(tmp_path) -> None:
    prov = isrc.CarpetaProvider(_carpeta_marca(tmp_path))
    out = prov.buscar("aerial view of palms on the bay", n=3)
    # aerial+palms (2 tokens) gana a bay (1 token)
    assert out[0].ruta_o_url.endswith("brand/aerial-palms.jpg")
    assert out[1].ruta_o_url.endswith("brand/bay-sunset.jpg")


def test_carpeta_sin_match_cae_a_fotos_de_marca_igual(tmp_path) -> None:
    """Sin coincidencia sigue devolviendo fotos: la marca prefiere su banco a
    fondo sólido o stock. Determinista por hint (mismo hint → mismo orden)."""
    prov = isrc.CarpetaProvider(_carpeta_marca(tmp_path))
    a = prov.buscar("régimen ejidal y fideicomiso", n=3)
    b = prov.buscar("régimen ejidal y fideicomiso", n=3)
    assert len(a) == 3 and [c.ruta_o_url for c in a] == [c.ruta_o_url for c in b]
    assert all(not c.ruta_o_url.endswith(".txt") for c in a)


def test_carpeta_inexistente_devuelve_vacio(tmp_path) -> None:
    assert isrc.CarpetaProvider(tmp_path / "nada").buscar("beach") == []


def test_providers_default_incluye_carpeta_de_la_marca(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(isrc, "BRANDS_DIR", tmp_path)
    (tmp_path / "melaquecapital" / "fotos").mkdir(parents=True)
    provs = isrc.providers_default(slug="melaquecapital")
    assert isinstance(provs["carpeta"], isrc.CarpetaProvider)
    assert "carpeta" not in isrc.providers_default()
