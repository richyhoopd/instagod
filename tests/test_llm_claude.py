import sys
import types

import pytest

import config
from src import llm_claude


class _Bloque:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, content, stop_reason="tool_use"):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Bloque(input_tokens=120, output_tokens=40)


@pytest.fixture
def anthropic_falso(monkeypatch):
    llamadas: list[dict] = []
    respuesta = {"r": _Resp([_Bloque(type="tool_use", name="disenar",
                                     input={"kind": "side"})])}

    class _Mensajes:
        def create(self, **kw):
            llamadas.append(kw)
            return respuesta["r"]

    class Anthropic:
        def __init__(self, api_key):
            assert api_key == "sk-prueba"
            self.messages = _Mensajes()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-prueba")
    return llamadas, respuesta


HERR = {"name": "disenar", "description": "x",
        "input_schema": {"type": "object", "properties": {}}}


def test_fuerza_la_herramienta_y_devuelve_su_input(anthropic_falso):
    llamadas, _ = anthropic_falso
    uso: list[dict] = []
    out = llm_claude.pedir_herramienta(
        system="s", mensajes=[{"role": "user", "content": "hola"}],
        herramienta=HERR, uso=uso)
    assert out == {"kind": "side"}
    kw = llamadas[0]
    assert kw["tool_choice"] == {"type": "tool", "name": "disenar"}
    assert kw["tools"] == [HERR]
    assert kw["model"] == config.DISENO_MODELO
    assert uso == [{"modelo": config.DISENO_MODELO, "entrada": 120, "salida": 40}]


def test_adjunta_imagenes_al_ultimo_mensaje_de_usuario(anthropic_falso, tmp_path):
    llamadas, _ = anthropic_falso
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfalso")
    mensajes = [{"role": "user", "content": "uno"},
                {"role": "assistant", "content": "dos"},
                {"role": "user", "content": "tres"}]
    llm_claude.pedir_herramienta(system="s", mensajes=mensajes,
                                 herramienta=HERR, imagenes=[png])
    enviados = llamadas[0]["messages"]
    assert enviados[0]["content"] == "uno"
    ultimo = enviados[2]["content"]
    assert ultimo[0]["type"] == "image"
    assert ultimo[0]["source"]["media_type"] == "image/png"
    assert ultimo[1] == {"type": "text", "text": "tres"}
    assert mensajes[2]["content"] == "tres"   # no muta la entrada


def test_sin_tool_use_lanza(anthropic_falso):
    _, respuesta = anthropic_falso
    respuesta["r"] = _Resp([_Bloque(type="text", text="no")], stop_reason="max_tokens")
    with pytest.raises(llm_claude.LLMSinHerramienta, match="max_tokens"):
        llm_claude.pedir_herramienta(system="s", mensajes=[{"role": "user", "content": "x"}],
                                     herramienta=HERR)


def test_sin_api_key_lanza(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    with pytest.raises(llm_claude.LLMNoDisponible):
        llm_claude.pedir_herramienta(system="s", mensajes=[{"role": "user", "content": "x"}],
                                     herramienta=HERR)


def test_extension_no_soportada(anthropic_falso, tmp_path):
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"GIF89a")
    with pytest.raises(ValueError, match="gif"):
        llm_claude.pedir_herramienta(system="s", mensajes=[{"role": "user", "content": "x"}],
                                     herramienta=HERR, imagenes=[gif])
