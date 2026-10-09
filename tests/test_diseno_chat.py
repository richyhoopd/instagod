import json

import pytest

from src import db, jobs, plantillas
from src.jobs import handlers
from src.plantillas import chat

ESCENA = {"v": 2, "lienzo": {"w": 1080, "h": 1350, "formato": "4x5",
                             "fondo": {"tipo": "color", "valor": "#ffffff"}},
          "tokens": {"colores": {}, "fuente": "Poppins-SemiBold"}, "capas": []}
CONTRATO = {"aspecto": "4:5", "base": ["titular", "imagen", "handle", "logo", "color_marca"],
            "extras": []}


def _marca(cx, slug):
    """conftest no tiene helper de marcas: se insertan como en test_disenos_web.py."""
    filas = db.rows(cx, "SELECT id FROM accounts WHERE slug = ?", (slug,))
    if filas:
        return {"id": filas[0]["id"], "slug": slug}
    aid = db.insert(cx, "accounts", slug=slug, ig_handle=slug, nombre=slug.title(),
                    ciudad="CDMX")
    return {"id": aid, "slug": slug}


def _plantilla(cx, account_id):
    # Mismo patrón que las pruebas del plan 1: HTML vacío y la escena v2 como layout.
    return plantillas.crear(cx, account_id, "Prueba", "", CONTRATO, layout=ESCENA)


@pytest.fixture
def con_marca(api_cliente):
    cli, cx, H = api_cliente
    prueba = _marca(cx, "prueba")
    uid = H.usuario("dueno@x.com", marcas=((prueba["id"], "manager"),))
    H.login(uid)
    return cli, cx, H, uid


def test_post_encola_202(con_marca, monkeypatch):
    cli, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    r = cli.post(f"/brands/prueba/templates/{tid}/chat",
                 json={"mensaje": "hazlo amarillo", "modo": "editar", "escena": ESCENA})
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])
    assert job["tipo"] == "diseno.chat"
    assert json.loads(job["payload_json"])["template_id"] == tid


def test_post_editor_403(con_marca):
    cli, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    otro = H.usuario("editor@x.com", marcas=((marca["id"], "editor"),))
    H.login(otro)
    r = cli.post(f"/brands/prueba/templates/{tid}/chat", json={"mensaje": "x"})
    assert r.status_code == 403


def test_post_plantilla_ajena_404(con_marca):
    cli, cx, H, uid = con_marca
    _marca(cx, "prueba")
    ajena = _marca(cx, "otra")
    tid = _plantilla(cx, ajena["id"])
    r = cli.post(f"/brands/prueba/templates/{tid}/chat", json={"mensaje": "x"})
    assert r.status_code == 404


def test_handler_crear_guarda_version(con_marca, monkeypatch):
    _, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    monkeypatch.setattr(chat, "crear", lambda cx_, m, msg, formato="4x5", uso=None: (
        uso.append({"modelo": "f", "entrada": 1, "salida": 1}) or ESCENA, CONTRATO,
        {"kind": "side", "respuesta": "Listo"}))
    jid = jobs.crear(cx, "diseno.chat", marca["id"],
                     {"template_id": tid, "mensaje": "post", "modo": "crear"}, creado_por=uid)
    res = handlers.diseno_chat(cx, db.get(cx, "jobs", jid))
    assert res["escena"] == ESCENA and res["respuesta"] == "Listo"
    ver = plantillas.versiones(cx, tid)[-1]
    assert ver["mensaje_usuario"] == "post"
    assert json.loads(ver["llm_meta"])["modo"] == "crear"


def test_handler_editar_devuelve_ops(con_marca, monkeypatch):
    _, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    lista = [{"op": "set", "capa": "t", "ruta": "x", "valor": 1}]
    monkeypatch.setattr(chat, "editar", lambda cx_, m, e, c, msg, uso=None: (
        lista, ESCENA, {"respuesta": "Hecho"}))
    jid = jobs.crear(cx, "diseno.chat", marca["id"],
                     {"template_id": tid, "mensaje": "x", "modo": "editar", "escena": ESCENA},
                     creado_por=uid)
    res = handlers.diseno_chat(cx, db.get(cx, "jobs", jid))
    assert res["ops"] == lista and "escena" not in res


def test_handler_plantilla_de_otra_cuenta(con_marca):
    _, cx, H, uid = con_marca
    m1 = _marca(cx, "prueba")
    m2 = _marca(cx, "otra")
    tid = _plantilla(cx, m2["id"])
    jid = jobs.crear(cx, "diseno.chat", m1["id"],
                     {"template_id": tid, "mensaje": "x", "modo": "crear"}, creado_por=uid)
    with pytest.raises(ValueError):
        handlers.diseno_chat(cx, db.get(cx, "jobs", jid))


def test_handler_error_no_guarda_version(con_marca, monkeypatch):
    # §6: si el modelo falla dos veces o falta un asset, error en el chat y la escena no se toca.
    _, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    antes = len(plantillas.versiones(cx, tid))
    layout_antes = plantillas.obtener(cx, tid)["layout_json"]

    def falla(*a, **k):
        raise chat.ChatError("spec inválido tras reintento")

    monkeypatch.setattr(chat, "crear", falla)
    monkeypatch.setattr(chat, "editar", falla)
    for payload in ({"template_id": tid, "mensaje": "x", "modo": "crear"},
                    {"template_id": tid, "mensaje": "x", "modo": "editar", "escena": ESCENA}):
        jid = jobs.crear(cx, "diseno.chat", marca["id"], payload, creado_por=uid)
        with pytest.raises(chat.ChatError):
            handlers.diseno_chat(cx, db.get(cx, "jobs", jid))
    assert len(plantillas.versiones(cx, tid)) == antes
    assert plantillas.obtener(cx, tid)["layout_json"] == layout_antes


def test_get_historial(con_marca, monkeypatch):
    cli, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    plantillas.nueva_version(cx, tid, "", CONTRATO, mensaje_usuario="hola",
                             llm_meta={"modo": "crear", "respuesta": "Listo"}, layout=ESCENA)
    r = cli.get(f"/brands/prueba/templates/{tid}/chat")
    assert r.status_code == 200
    assert r.json()[-1]["mensaje"] == "hola"
    assert r.json()[-1]["respuesta"] == "Listo"


def test_post_409_si_no_es_borrador(con_marca):
    cli, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    db.update(cx, "brand_templates", tid, estado="activa")
    cx.commit()
    antes = len(db.rows(cx, "SELECT id FROM jobs"))
    r = cli.post(f"/brands/prueba/templates/{tid}/chat", json={"mensaje": "x", "modo": "editar"})
    assert r.status_code == 409
    assert len(db.rows(cx, "SELECT id FROM jobs")) == antes


def test_handler_rechaza_si_ya_no_es_borrador(con_marca, monkeypatch):
    _, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    llamado = []
    monkeypatch.setattr(chat, "editar", lambda *a, **k: llamado.append(1))
    jid = jobs.crear(cx, "diseno.chat", marca["id"],
                     {"template_id": tid, "mensaje": "x", "modo": "editar", "escena": ESCENA},
                     creado_por=uid)
    db.update(cx, "brand_templates", tid, estado="activa")
    cx.commit()
    nv = len(plantillas.versiones(cx, tid))
    with pytest.raises(ValueError, match="borrador"):
        handlers.diseno_chat(cx, db.get(cx, "jobs", jid))
    assert not llamado and len(plantillas.versiones(cx, tid)) == nv


def test_handler_exige_modo(con_marca):
    _, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    jid = jobs.crear(cx, "diseno.chat", marca["id"],
                     {"template_id": tid, "mensaje": "x"}, creado_por=uid)
    with pytest.raises(ValueError, match="modo"):
        handlers.diseno_chat(cx, db.get(cx, "jobs", jid))
