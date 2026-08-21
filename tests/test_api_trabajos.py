"""Slideshows y cola de jobs vía API."""
from __future__ import annotations

import json

from src import db


def _marca(cx, slug="pensionmas", **campos):
    base = dict(slug=slug, ig_handle="@p", nombre="P", ciudad="CDMX")
    base.update(campos)
    return db.insert(cx, "accounts", **base)


def test_editor_crea_slideshow_con_defaults_del_perfil(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx, formatos=json.dumps(["perfil", "libre"]),
                estilos_json=json.dumps({"editorial": {}}),
                fuentes_imagen=json.dumps(["pexels", "unsplash"]))
    uid = H.usuario("e@x.com", marcas=[(pid, "editor")])
    H.login(uid)
    r = cli.post("/brands/pensionmas/slideshows", json={"tema": "un tema cualquiera"})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    job = db.get(cx, "jobs", job_id)
    assert job["tipo"] == "slideshow.generar" and job["account_id"] == pid
    assert job["creado_por"] == uid and job["estado"] == "cola"
    payload = json.loads(job["payload_json"])
    assert payload == {"tema": "un tema cualquiera", "formato": "perfil", "estilo": "editorial",
                       "fuentes": ["pexels", "unsplash"], "n_slides": 6, "aspect": "4:5",
                       "contexto": None}


def test_tema_corto_422(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/slideshows", json={"tema": "ab"})
    assert r.status_code == 422


def test_formato_no_habilitado_422_campo(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx, formatos=json.dumps(["listicle"]))
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/slideshows",
                json={"tema": "tema valido", "formato": "perfil"})
    assert r.status_code == 422 and r.json()["campo"] == "formato"


def test_estilo_inexistente_422_campo(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/slideshows",
                json={"tema": "tema valido", "estilo": "no_existe"})
    assert r.status_code == 422 and r.json()["campo"] == "estilo"


def test_n_slides_fuera_de_rango_422(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    assert cli.post("/brands/pensionmas/slideshows",
                    json={"tema": "tema valido", "n_slides": 0}).status_code == 422
    assert cli.post("/brands/pensionmas/slideshows",
                    json={"tema": "tema valido", "n_slides": 11}).status_code == 422


def test_otra_marca_403(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx, "pensionmas")
    _marca(cx, "otra")
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/otra/slideshows", json={"tema": "tema valido"})
    assert r.status_code == 403
    assert cli.get("/brands/otra/jobs").status_code == 403


def test_jobs_lista_detalle_y_aislamiento(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx, "pensionmas")
    otra = _marca(cx, "otra")
    jid = db.insert(cx, "jobs", tipo="slideshow.generar", account_id=pid,
                    payload_json="{}", estado="ok", progreso=100)
    jid_otra = db.insert(cx, "jobs", tipo="slideshow.generar", account_id=otra,
                         payload_json="{}", estado="cola")
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))

    r = cli.get("/brands/pensionmas/jobs")
    assert r.status_code == 200
    lista = r.json()
    assert len(lista) == 1 and lista[0]["id"] == jid
    assert set(lista[0]) == {"id", "tipo", "estado", "progreso", "log", "queue_id",
                             "created_at", "finished_at"}

    r = cli.get(f"/brands/pensionmas/jobs/{jid}")
    assert r.status_code == 200 and r.json()["id"] == jid

    assert cli.get(f"/brands/pensionmas/jobs/{jid_otra}").status_code == 404
    assert cli.get("/brands/pensionmas/jobs/999999").status_code == 404
    assert cli.post(f"/brands/pensionmas/jobs/{jid_otra}/cancel").status_code == 404

    r = cli.get("/brands/pensionmas/jobs?estado=ok")
    assert [j["id"] for j in r.json()] == [jid]
    r = cli.get("/brands/pensionmas/jobs?estado=cola")
    assert r.json() == []


def test_cancel_en_cola_ok_y_corriendo_422(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    en_cola = db.insert(cx, "jobs", tipo="slideshow.generar", account_id=pid,
                        payload_json="{}", estado="cola")
    corriendo = db.insert(cx, "jobs", tipo="slideshow.generar", account_id=pid,
                          payload_json="{}", estado="corriendo")
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))

    r = cli.post(f"/brands/pensionmas/jobs/{corriendo}/cancel")
    assert r.status_code == 422

    r = cli.post(f"/brands/pensionmas/jobs/{en_cola}/cancel")
    assert r.status_code == 200
    assert db.get(cx, "jobs", en_cola)["estado"] == "cancelado"


def _topic(cx, account_id, **campos):
    base = dict(account_id=account_id, titulo="Nuevo mural en el centro",
               resumen="Un colectivo pintó un mural gigante", url="https://x.com/nota",
               fuente="rss")
    base.update(campos)
    return db.insert(cx, "topic_suggestions", **base)


def test_slideshow_con_topic_id_usa_tema_y_contexto_del_topic(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    tid = _topic(cx, pid)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))

    r = cli.post("/brands/pensionmas/slideshows", json={"topic_id": tid, "tema": "un tema cualquiera"})
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])
    payload = json.loads(job["payload_json"])
    assert payload["topic_id"] == tid
    assert payload["tema"] == "un tema cualquiera"


def test_slideshow_con_topic_id_sin_tema_ni_contexto_usa_defaults_del_topic(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    tid = _topic(cx, pid, titulo="Feria gastronómica en GDL",
                resumen="Más de 40 puestos de comida local", url="https://x.com/feria")
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))

    r = cli.post("/brands/pensionmas/slideshows", json={"topic_id": tid})
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])
    payload = json.loads(job["payload_json"])
    assert payload["topic_id"] == tid
    assert payload["tema"] == "Feria gastronómica en GDL"
    assert payload["contexto"] == "Más de 40 puestos de comida local\nhttps://x.com/feria"


def test_slideshow_topic_sin_url_ni_resumen_no_mete_none_en_contexto(api_cliente) -> None:
    """H7: filtrar None al armar el contexto — un topic sin resumen ni url no
    debe terminar con el texto literal "None" en el prompt del LLM."""
    cli, cx, H = api_cliente
    pid = _marca(cx)
    tid = _topic(cx, pid, resumen=None, url=None)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))

    r = cli.post("/brands/pensionmas/slideshows", json={"topic_id": tid})
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])
    payload = json.loads(job["payload_json"])
    assert payload["contexto"] is None
    assert "None" not in (payload["contexto"] or "")


def test_slideshow_sin_tema_ni_topic_id_422(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/slideshows", json={})
    assert r.status_code == 422


def test_slideshow_topic_id_de_otra_marca_404(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx, "pensionmas")
    otra = _marca(cx, "otra")
    tid = _topic(cx, otra)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/slideshows", json={"topic_id": tid})
    assert r.status_code == 404


def test_slideshow_topic_id_descartado_422(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    tid = _topic(cx, pid, descartado=1)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/slideshows", json={"topic_id": tid})
    assert r.status_code == 422
