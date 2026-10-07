"""El diseñador con LLM. Cero llamadas reales: siempre monkeypatch."""
import json

import pytest

from src import db as db_mod
from src import jobs as jobs_mod
from src import plantillas
from src.jobs import handlers
from src.plantillas import contrato, disenador, layout

CONTRATO = {"aspecto": "4:5", "base": list(contrato.CAMPOS_BASE), "extras": []}
MARCA = {"nombre": "GDL Scene", "color_marca": "#1b5e3f", "handle": "gdlscene"}
# Nombres reales del catálogo (config.SLIDESHOW_FUENTES / fuentes_tipograficas):
# la "familia" incluye el peso, p.ej. "Poppins-Bold" — igual que el `fuente`
# por defecto de layout.vacio(). Con nombres pelones ("Poppins") el propio
# layout.vacio() no pasaría layout.validar en los casos felices de abajo.
FAMILIAS = {"Poppins-Bold", "Tinos-Regular"}


def _respuesta(layout_dict):
    return json.dumps(layout_dict, ensure_ascii=False)


def test_devuelve_el_layout_que_manda_el_llm(monkeypatch):
    bueno = layout.vacio("4:5")
    monkeypatch.setattr(disenador, "_pedir_al_llm", lambda p: _respuesta(bueno))
    assert disenador.disenar(marca=MARCA, contrato=CONTRATO,
                             instruccion="algo minimalista",
                             familias=FAMILIAS) == bueno


def test_tolera_el_json_envuelto_en_bloque_de_codigo(monkeypatch):
    bueno = layout.vacio("4:5")
    monkeypatch.setattr(disenador, "_pedir_al_llm",
                        lambda p: "```json\n" + _respuesta(bueno) + "\n```")
    assert disenador.disenar(marca=MARCA, contrato=CONTRATO, instruccion="x",
                             familias=FAMILIAS) == bueno


def test_reintenta_cuando_el_layout_no_valida(monkeypatch):
    malo = {**layout.vacio("4:5"), "capas": []}
    bueno = layout.vacio("4:5")
    respuestas = [_respuesta(malo), _respuesta(bueno)]
    vistos = []

    def falso(prompt):
        vistos.append(prompt)
        return respuestas.pop(0)

    monkeypatch.setattr(disenador, "_pedir_al_llm", falso)
    assert disenador.disenar(marca=MARCA, contrato=CONTRATO, instruccion="x",
                             familias=FAMILIAS) == bueno
    assert len(vistos) == 2
    # El segundo intento le dice qué salió mal.
    assert "vacío" in vistos[1]


def test_se_rinde_despues_de_los_intentos(monkeypatch):
    monkeypatch.setattr(disenador, "_pedir_al_llm", lambda p: "no soy json")
    with pytest.raises(contrato.ContratoInvalido):
        disenador.disenar(marca=MARCA, contrato=CONTRATO, instruccion="x",
                          familias=FAMILIAS, intentos=2)


def test_el_prompt_lleva_las_tipografias_y_los_datos_disponibles(monkeypatch):
    visto = {}

    def falso(prompt):
        visto["p"] = prompt
        return _respuesta(layout.vacio("4:5"))

    monkeypatch.setattr(disenador, "_pedir_al_llm", falso)
    disenador.disenar(marca=MARCA, contrato=CONTRATO, instruccion="algo verde",
                      familias=FAMILIAS, stickers=["corazon.png"])
    p = visto["p"]
    assert "Poppins" in p and "Tinos" in p
    assert "titular" in p and "imagen" in p
    assert "corazon.png" in p
    assert "1080" in p and "1350" in p
    assert "algo verde" in p


def test_partir_de_un_diseno_existente_lo_manda_como_base(monkeypatch):
    visto = {}
    base = layout.vacio("4:5")
    base["capas"][1]["id"] = "mi_titular_raro"

    def falso(prompt):
        visto["p"] = prompt
        return _respuesta(layout.vacio("4:5"))

    monkeypatch.setattr(disenador, "_pedir_al_llm", falso)
    disenador.disenar(marca=MARCA, contrato=CONTRATO, instruccion="hazlo más grande",
                      base=base, familias=FAMILIAS)
    assert "mi_titular_raro" in visto["p"]


# ---------- el handler del job (propone, nunca guarda) ----------

@pytest.fixture()
def cx(tmp_path):
    c = db_mod.connect(tmp_path / "t.db")
    db_mod.init_db(c)
    yield c
    c.close()


def _job(cx, tipo, account_id, payload):
    jid = jobs_mod.crear(cx, tipo, account_id, payload)
    return db_mod.get(cx, "jobs", jid)


def test_el_handler_propone_un_diseno_sin_guardarlo(cx, monkeypatch):
    bueno = layout.vacio("4:5")
    monkeypatch.setattr(handlers.disenador, "_pedir_al_llm", lambda p: _respuesta(bueno))
    job = _job(cx, "template.disenar", 1,
              {"template_id": None, "instruccion": "algo minimalista", "aspecto": "4:5"})

    resultado = handlers.template_disenar(cx, job)

    assert resultado["layout"] == bueno
    # Nunca escribe: el asistente propone, la persona guarda.
    assert db_mod.rows(cx, "SELECT * FROM brand_templates") == []
    assert db_mod.rows(cx, "SELECT * FROM template_versions") == []


def test_el_handler_usa_la_marca_del_job_nunca_la_del_payload(cx, monkeypatch):
    """Un diseño de partida de OTRA cuenta es un error, sin importar qué
    account_id venga (o no) en el payload: el aislamiento se decide con
    job['account_id'], nunca con datos que manda quien encoló el trabajo."""
    otra_id = db_mod.insert(cx, "accounts", slug="otra", ig_handle="otra",
                            nombre="Otra", ciudad="CDMX")
    ct = {"aspecto": "4:5", "base": list(contrato.CAMPOS_BASE), "extras": []}
    html_legacy = (
        "<!doctype html><html><head><style>"
        ".card { width:1080px; height:1350px; background:{{ color_marca }}; }"
        "</style></head><body><div class=\"card\">{{ titular }} "
        "\u2014 {{ handle }}</div></body></html>")
    tid_ajeno = plantillas.crear(cx, otra_id, "Ajeno", html_legacy, ct)

    monkeypatch.setattr(handlers.disenador, "_pedir_al_llm",
                        lambda p: _respuesta(layout.vacio("4:5")))
    job = _job(cx, "template.disenar", 1,
              {"template_id": tid_ajeno, "instruccion": "hazlo más grande",
               "aspecto": "4:5"})

    with pytest.raises(ValueError):
        handlers.template_disenar(cx, job)


def test_el_handler_traduce_errores_del_llm_sin_filtrar_secretos(cx, monkeypatch):
    monkeypatch.setattr(handlers.disenador, "_pedir_al_llm", lambda p: "no soy json")
    job = _job(cx, "template.disenar", 1,
              {"template_id": None, "instruccion": "x", "aspecto": "4:5"})

    with pytest.raises(ValueError) as exc:
        handlers.template_disenar(cx, job)
    # No debe reventar con la excepción original sin pasar por _redactar.
    assert "traceback" not in str(exc.value).lower()


def test_el_handler_rechaza_un_aspecto_inventado_sin_llamar_al_modelo(cx, monkeypatch):
    """El aspecto llega dentro del contrato y `_prompt` lo usa como llave: si
    no es uno de los que existen, el trabajo falla con un mensaje legible
    y sin gastar una llamada de pago."""
    llamadas = []

    def falso(prompt):
        llamadas.append(prompt)
        return _respuesta(layout.vacio("4:5"))

    monkeypatch.setattr(handlers.disenador, "_pedir_al_llm", falso)
    job = _job(cx, "template.disenar", 1,
              {"template_id": None, "instruccion": "x", "aspecto": "16:9"})

    with pytest.raises(ValueError):
        handlers.template_disenar(cx, job)
    assert llamadas == []
