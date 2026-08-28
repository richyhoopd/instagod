"""Propuesta de temas de un plan (src/plan_temas.py)."""
import json

import pytest

from src import plan_temas, slideshow_script


def _respuesta(n, formato="listicle"):
    return json.dumps({"temas": [
        {"titulo": f"tema {i}", "formato": formato, "hook": f"gancho {i}",
         "fuente": "prompt", "url": None}
        for i in range(n)
    ]})


def test_extraer_temas_tolera_fences():
    data = plan_temas.extraer_temas("```json\n" + _respuesta(2) + "\n```")
    assert data is not None and len(data["temas"]) == 2


def test_extraer_temas_none_si_no_hay_json():
    assert plan_temas.extraer_temas("no hay nada") is None


def test_validar_temas_detecta_titulo_vacio():
    data = {"temas": [{"titulo": " ", "formato": "listicle", "hook": "h"}]}
    errores = plan_temas.validar_temas(data, formatos=["listicle"])
    assert any("titulo" in e for e in errores)


def test_validar_temas_lista_vacia_es_error():
    assert plan_temas.validar_temas({"temas": []}, formatos=["listicle"])


def test_proponer_normaliza_formato_desconocido(monkeypatch):
    crudo = json.dumps({"temas": [{"titulo": "t", "formato": "inventado",
                                   "hook": "h", "fuente": "prompt", "url": None}]})
    monkeypatch.setattr(slideshow_script, "_llamar_llm", lambda *a, **k: crudo)
    temas = plan_temas.proponer("objetivo largo del plan", n=1, formatos=["listicle", "libre"])
    assert temas[0]["formato"] == "listicle"


def test_proponer_trunca_a_n(monkeypatch):
    monkeypatch.setattr(slideshow_script, "_llamar_llm",
                        lambda *a, **k: _respuesta(8))
    temas = plan_temas.proponer("objetivo del plan", n=5, formatos=["listicle"])
    assert len(temas) == 5


def test_proponer_fuente_noticia_solo_con_url_del_banco(monkeypatch):
    crudo = json.dumps({"temas": [
        {"titulo": "t1", "formato": "listicle", "hook": "h",
         "fuente": "noticia", "url": "https://ejemplo.mx/nota"},
        {"titulo": "t2", "formato": "listicle", "hook": "h",
         "fuente": "noticia", "url": "https://otro.mx/inventada"},
    ]})
    monkeypatch.setattr(slideshow_script, "_llamar_llm", lambda *a, **k: crudo)
    noticias = [{"titulo": "nota", "url": "https://ejemplo.mx/nota", "resumen": "r", "id": 7}]
    temas = plan_temas.proponer("objetivo", n=2, formatos=["listicle"], noticias=noticias)
    assert temas[0]["fuente"] == "noticia" and temas[0]["url"] == "https://ejemplo.mx/nota"
    # URL que no está en el banco de noticias → cae a 'prompt' sin URL (anti-alucinación)
    assert temas[1]["fuente"] == "prompt" and temas[1]["url"] is None


def test_proponer_usa_su_propio_system_prompt(monkeypatch):
    visto = {}

    def _llm(prompt, **kwargs):
        visto.update(kwargs)
        return _respuesta(2)

    monkeypatch.setattr(slideshow_script, "_llamar_llm", _llm)
    plan_temas.proponer("objetivo", n=2, formatos=["listicle"])
    assert visto.get("system_prompt") == plan_temas.SYSTEM_PROMPT_TEMAS


def test_proponer_reintenta_con_errores(monkeypatch):
    respuestas = iter(["esto no es json", _respuesta(3)])
    monkeypatch.setattr(slideshow_script, "_llamar_llm",
                        lambda *a, **k: next(respuestas))
    temas = plan_temas.proponer("objetivo", n=3, formatos=["listicle"])
    assert len(temas) == 3


def test_proponer_revienta_tras_3_intentos(monkeypatch):
    monkeypatch.setattr(slideshow_script, "_llamar_llm", lambda *a, **k: "basura")
    with pytest.raises(RuntimeError):
        plan_temas.proponer("objetivo", n=3, formatos=["listicle"])


def test_proponer_sin_formatos_es_error():
    with pytest.raises(ValueError):
        plan_temas.proponer("objetivo", n=3, formatos=[])
