from types import SimpleNamespace

import pytest

from src import db
from src.assets import Candidata
from src.plantillas import chat, kinds


def _marca():
    return SimpleNamespace(id=1, slug="prueba", nombre="Prueba", ig_handle="prueba",
                           color_marca="#7A4CFF", voz="Cercana, directa.", fuentes=[],
                           formatos=["4x5"], estilos={}, logo_path=None, activa=True, prompts={})


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    respuestas: list[dict] = []
    pedidos: list[dict] = []

    def falso(**kw):
        pedidos.append(kw)
        if kw.get("uso") is not None:
            kw["uso"].append({"modelo": "falso", "entrada": 1, "salida": 1})
        return respuestas.pop(0)

    monkeypatch.setattr(chat.llm_claude, "pedir_herramienta", falso)
    buscadas: list[str] = []

    def buscar(cx_, aid, slug, q, *, tipo="imagen", proveedores=None, n=20):
        buscadas.append(q)
        return [Candidata(proveedor="pexels", id_origen="1", tipo="imagen", url="u",
                          preview_url="p", ancho=10, alto=10, autor="Ana",
                          licencia="Pexels", url_origen="https://pexels.com/1")]

    monkeypatch.setattr(chat.buscar, "buscar", buscar)
    monkeypatch.setattr(chat.biblioteca, "importar", lambda cx_, aid, slug, cand: {
        "archivo": "foto.jpg", "proveedor": cand.proveedor, "autor": cand.autor,
        "licencia": cand.licencia, "url_origen": cand.url_origen, "ig_handle": None,
        "recorte_archivo": None})
    monkeypatch.setattr(chat.biblioteca, "ruta_de", lambda slug, a: tmp_path / a)
    recortes: list[str] = []
    monkeypatch.setattr(chat.recorte, "quitar_fondo",
                        lambda o, d: recortes.append(d.name) or d)
    compuestos: list[dict] = []

    def componer(cx_, marca, kind, spec, assets, catalogo):
        compuestos.append({"kind": kind, "spec": spec, "assets": assets})
        esc = {"v": 2, "lienzo": {"w": 1080, "h": 1350, "formato": "4x5",
                                  "fondo": {"tipo": "color", "valor": "#ffffff"}},
               "tokens": {"colores": {}, "fuente": "Poppins-SemiBold"},
               "capas": [{"id": "bajada", "tipo": "text", "campo": "bajada", "texto": "x"}]}
        return b"\x89PNG", esc, {"bajada": "x"}

    monkeypatch.setattr(chat, "_componer", componer)
    validadas: list[dict] = []
    monkeypatch.setattr(chat.escena_mod, "validar",
                        lambda e, c, familias=None: validadas.append(c))
    return SimpleNamespace(cx=cx, respuestas=respuestas, pedidos=pedidos, buscadas=buscadas,
                           recortes=recortes, compuestos=compuestos, validadas=validadas)


SIDE = {"kind": "side", "spec": {"titulo": ["Hola"], "bajada": "x"},
        "assets": {"imagen": "woman doctor smiling"}, "respuesta": "Listo"}


def test_crear_feliz(entorno):
    entorno.respuestas += [SIDE, {"ok": True}]
    uso: list = []
    escena, contrato, meta = chat.crear(entorno.cx, _marca(), "post de ginecología", uso=uso)
    assert entorno.buscadas == ["woman doctor smiling"]
    assert entorno.compuestos[0]["assets"]["imagen"]["archivo"] == "assets/foto.jpg"
    assert entorno.compuestos[0]["assets"]["imagen"]["fuente_asset"]["url"] == "https://pexels.com/1"
    assert contrato["extras"] == [{"id": "bajada", "tipo": "texto"}]
    assert contrato["aspecto"] == "4:5"
    assert meta["kind"] == "side" and meta["respuesta"] == "Listo"
    assert len(uso) == 2
    # la segunda llamada es la crítica, con la imagen
    assert entorno.pedidos[1]["herramienta"]["name"] == "revisar"
    assert len(entorno.pedidos[1]["imagenes"]) == 1


def test_spec_invalido_reintenta_una_vez(entorno):
    malo = {**SIDE, "spec": {"titulo": []}}
    entorno.respuestas += [malo, SIDE, {"ok": True}]
    chat.crear(entorno.cx, _marca(), "x")
    reintento = entorno.pedidos[1]["mensajes"]
    assert reintento[-1]["role"] == "user" and "titulo" in reintento[-1]["content"]


def test_dos_fallos_es_chat_error(entorno):
    malo = {**SIDE, "spec": {"titulo": []}}
    entorno.respuestas += [malo, malo]
    with pytest.raises(chat.ChatError):
        chat.crear(entorno.cx, _marca(), "x")


def test_falta_consulta_de_slot_requerido(entorno):
    sin = {**SIDE, "assets": {}}
    entorno.respuestas += [sin, sin]
    with pytest.raises(chat.ChatError, match="imagen"):
        chat.crear(entorno.cx, _marca(), "x")


def test_recorte_en_compare(entorno):
    comp = {"kind": "compare", "respuesta": "ok", "assets": {"item_0": "pill", "item_1": "flask"},
            "spec": {"titulo": ["A"], "oferta": {"nombre": "T", "precio": "$1"},
                     "items": [{"nombre": "a", "precio": "1"}, {"nombre": "b", "precio": "2"}]}}
    entorno.respuestas += [comp, {"ok": True}]
    chat.crear(entorno.cx, _marca(), "x")
    assert entorno.recortes == ["foto-recorte.png", "foto-recorte.png"]
    assert entorno.compuestos[0]["assets"]["item_0"]["archivo"] == "assets/foto-recorte.png"


def test_critica_corrige_una_vez(entorno):
    entorno.respuestas += [SIDE, {"ok": False, "problemas": ["título corto"],
                                  "spec": {"titulo": ["Hola", "mundo"]}}]
    chat.crear(entorno.cx, _marca(), "x")
    assert len(entorno.compuestos) == 2
    assert entorno.compuestos[1]["spec"]["titulo"] == ["Hola", "mundo"]
    assert len(entorno.pedidos) == 2


def test_critica_con_spec_invalido_se_ignora(entorno):
    entorno.respuestas += [SIDE, {"ok": False, "spec": {"titulo": []}}]
    chat.crear(entorno.cx, _marca(), "x")
    assert len(entorno.compuestos) == 1


def test_formato_1x1_reformatea(entorno, monkeypatch):
    llamado = {}
    monkeypatch.setattr(chat.escena_mod, "reformatear",
                        lambda e, f: llamado.setdefault("f", f) and e)
    entorno.respuestas += [SIDE, {"ok": True}]
    _, contrato, _ = chat.crear(entorno.cx, _marca(), "x", formato="1x1")
    assert llamado["f"] == "1x1"
    assert contrato["aspecto"] == "1:1"


def test_system_lista_los_kinds(entorno):
    entorno.respuestas += [SIDE, {"ok": True}]
    chat.crear(entorno.cx, _marca(), "x")
    system = entorno.pedidos[0]["system"]
    for k in kinds.KINDS:
        assert f'"{k}"' in system
    assert "Cercana, directa." in system


def test_asset_salta_candidata_que_no_descarga(entorno, monkeypatch):
    # §3: «el primer resultado viable». Si la primera candidata no se descarga
    # (404, host no permitido, tipo equivocado), se prueba la siguiente.
    c1 = Candidata(proveedor="pexels", id_origen="1", tipo="imagen", url="u1", preview_url="p",
                   ancho=10, alto=10, autor="Mala", licencia="Pexels", url_origen="o1")
    c2 = Candidata(proveedor="pexels", id_origen="2", tipo="imagen", url="u2", preview_url="p",
                   ancho=10, alto=10, autor="Buena", licencia="Pexels", url_origen="o2")
    monkeypatch.setattr(chat.buscar, "buscar", lambda *a, **k: [c1, c2])

    def importar(cx_, aid, slug, cand):
        if cand.id_origen == "1":
            raise chat.biblioteca.AssetInvalido("404")
        return {"archivo": "buena.jpg", "proveedor": "pexels", "autor": cand.autor,
                "licencia": "Pexels", "url_origen": cand.url_origen, "ig_handle": None,
                "recorte_archivo": None}

    monkeypatch.setattr(chat.biblioteca, "importar", importar)
    a = chat.asset_para(entorno.cx, _marca(), "beach", recortar=False)
    assert a["archivo"] == "assets/buena.jpg"
    assert a["fuente_asset"]["autor"] == "Buena"

    monkeypatch.setattr(chat.biblioteca, "importar",
                        lambda *a, **k: (_ for _ in ()).throw(chat.biblioteca.AssetInvalido("x")))
    assert chat.asset_para(entorno.cx, _marca(), "beach", recortar=False) is None


def test_max_tokens_en_diseno_reintenta_y_luego_falla(entorno, monkeypatch):
    original = chat.llm_claude.pedir_herramienta
    llamadas = {"n": 0}

    def primero_truncado(**kw):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise chat.llm_claude.LLMTruncado("max_tokens")
        return original(**kw)

    entorno.respuestas += [SIDE, {"ok": True}]
    monkeypatch.setattr(chat.llm_claude, "pedir_herramienta", primero_truncado)
    _, _, meta = chat.crear(entorno.cx, _marca(), "x")
    assert meta["kind"] == "side" and llamadas["n"] == 3

    def truncado(**kw):
        raise chat.llm_claude.LLMTruncado("max_tokens")

    monkeypatch.setattr(chat.llm_claude, "pedir_herramienta", truncado)
    with pytest.raises(chat.ChatError, match="max_tokens"):
        chat.crear(entorno.cx, _marca(), "x")


def test_max_tokens_en_critica_se_ignora(entorno, monkeypatch):
    original = chat.llm_claude.pedir_herramienta

    def f(**kw):
        if kw["herramienta"]["name"] == "revisar":
            raise chat.llm_claude.LLMTruncado("max_tokens")
        return original(**kw)

    entorno.respuestas += [SIDE]
    monkeypatch.setattr(chat.llm_claude, "pedir_herramienta", f)
    chat.crear(entorno.cx, _marca(), "x")
    assert len(entorno.compuestos) == 1


def test_critica_con_slot_sin_resolver_conserva_el_primer_render(entorno):
    comp = {"kind": "compare", "respuesta": "ok", "assets": {"item_0": "pill", "item_1": "flask"},
            "spec": {"titulo": ["A"], "oferta": {"nombre": "T", "precio": "$1"},
                     "items": [{"nombre": "a", "precio": "1"}, {"nombre": "b", "precio": "2"}]}}
    tres = {**comp["spec"], "items": comp["spec"]["items"] + [{"nombre": "c", "precio": "3"}]}
    entorno.respuestas += [comp, {"ok": False, "problemas": ["falta uno"], "spec": tres}]
    _, _, meta = chat.crear(entorno.cx, _marca(), "x")
    assert len(entorno.compuestos) == 1
    assert meta["revisado"] is False
    assert len(meta["spec"]["items"]) == 2
