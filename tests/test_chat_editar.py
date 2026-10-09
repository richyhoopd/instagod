import json
from types import SimpleNamespace

import pytest

from src import db
from src.plantillas import chat

ESCENA = {"v": 2, "lienzo": {"w": 1080, "h": 1350, "formato": "4x5",
                             "fondo": {"tipo": "color", "valor": "#ffffff"}},
          "tokens": {"colores": {}, "fuente": "Poppins-SemiBold"},
          "capas": [{"id": "titulo", "tipo": "text", "texto": "Hola", "estilo": {"fontSize": 72}},
                    {"id": "imagen", "tipo": "image", "src": "assets/a.png", "recorte": False}]}
CONTRATO = {"aspecto": "4:5", "base": [], "extras": []}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    respuestas, pedidos, validadas = [], [], []

    def falso(**kw):
        pedidos.append(kw)
        return respuestas.pop(0)

    monkeypatch.setattr(chat.llm_claude, "pedir_herramienta", falso)

    def validar(e, c, familias=None):
        validadas.append(e)
        tam = next(x for x in e["capas"] if x["id"] == "titulo")["estilo"].get("fontSize", 0)
        if tam > 400:
            raise chat.escena_mod.EscenaInvalida("fontSize fuera de rango")

    monkeypatch.setattr(chat.escena_mod, "validar", validar)
    monkeypatch.setattr(chat, "asset_para", lambda cx_, m, q, recortar: {
        "src": "file:///x/b.jpg", "archivo": "assets/b.jpg",
        "fuente_asset": {"proveedor": "pexels", "autor": "Ana", "licencia": None,
                         "url": None, "ig_handle": None}})
    marca = SimpleNamespace(id=1, slug="prueba", nombre="Prueba", ig_handle=None, voz="",
                            fuentes=[], estilos={}, logo_path=None)
    return SimpleNamespace(cx=cx, marca=marca, respuestas=respuestas, pedidos=pedidos,
                           validadas=validadas)


def test_editar_aplica_ops(entorno):
    entorno.respuestas.append({"ops": [{"op": "set", "capa": "titulo", "ruta": "estilo.fontSize",
                                        "valor": 96}], "respuesta": "Más grande."})
    lista, nueva, meta = chat.editar(entorno.cx, entorno.marca, ESCENA, CONTRATO, "más grande")
    assert nueva["capas"][0]["estilo"]["fontSize"] == 96
    assert ESCENA["capas"][0]["estilo"]["fontSize"] == 72
    assert lista == [{"op": "set", "capa": "titulo", "ruta": "estilo.fontSize", "valor": 96}]
    assert meta["respuesta"] == "Más grande."
    assert '"titulo"' in entorno.pedidos[0]["mensajes"][0]["content"]


def test_editar_reintenta_si_la_escena_no_valida(entorno):
    entorno.respuestas += [
        {"ops": [{"op": "set", "capa": "titulo", "ruta": "estilo.fontSize", "valor": 900}],
         "respuesta": "x"},
        {"ops": [{"op": "set", "capa": "titulo", "ruta": "estilo.fontSize", "valor": 300}],
         "respuesta": "y"}]
    lista, nueva, _ = chat.editar(entorno.cx, entorno.marca, ESCENA, CONTRATO, "enorme")
    assert nueva["capas"][0]["estilo"]["fontSize"] == 300
    assert "fontSize fuera de rango" in entorno.pedidos[1]["mensajes"][-1]["content"]


def test_editar_op_invalida_dos_veces(entorno):
    mala = {"ops": [{"op": "del", "capa": "nada"}], "respuesta": "x"}
    entorno.respuestas += [mala, mala]
    with pytest.raises(chat.ChatError):
        chat.editar(entorno.cx, entorno.marca, ESCENA, CONTRATO, "borra")


def test_buscar_asset_se_vuelve_ops(entorno):
    entorno.respuestas.append({"ops": [], "respuesta": "Cambié la foto.",
                               "buscar_asset": [{"capa": "imagen", "query": "beach sunset"}]})
    lista, nueva, _ = chat.editar(entorno.cx, entorno.marca, ESCENA, CONTRATO, "otra foto")
    assert {"op": "set", "capa": "imagen", "ruta": "src", "valor": "assets/b.jpg"} in lista
    assert nueva["capas"][1]["fuente_asset"]["autor"] == "Ana"


def test_buscar_asset_sobre_capa_no_imagen(entorno):
    mala = {"ops": [], "respuesta": "x", "buscar_asset": [{"capa": "titulo", "query": "a"}]}
    entorno.respuestas += [mala, mala]
    with pytest.raises(chat.ChatError, match="titulo"):
        chat.editar(entorno.cx, entorno.marca, ESCENA, CONTRATO, "x")


def test_editar_no_manda_src_largos(entorno):
    # §3: «escena sin src largos». Ni data: ni file:// ni cadenas enormes llegan a Claude.
    escena = json.loads(json.dumps(ESCENA))
    escena["capas"][1]["src"] = "data:image/png;base64," + "A" * 5000
    escena["capas"].append({"id": "logo", "tipo": "image", "src": "file:///Users/x/logo.png",
                            "recorte": False})
    entorno.respuestas.append({"ops": [], "respuesta": "ok"})
    chat.editar(entorno.cx, entorno.marca, escena, CONTRATO, "nada")
    enviado = entorno.pedidos[0]["mensajes"][0]["content"]
    assert "base64" not in enviado and "file://" not in enviado
    assert '"imagen"' in enviado and '"logo"' in enviado
    assert escena["capas"][1]["src"].startswith("data:")  # la escena real no se toca


def test_editar_truncado_se_reintenta_y_luego_falla(entorno, monkeypatch):
    def trunco(**kw):
        entorno.pedidos.append(kw)
        raise chat.llm_claude.LLMTruncado("max_tokens")

    monkeypatch.setattr(chat.llm_claude, "pedir_herramienta", trunco)
    with pytest.raises(chat.ChatError):
        chat.editar(entorno.cx, entorno.marca, ESCENA, CONTRATO, "x")
    assert len(entorno.pedidos) == 2
