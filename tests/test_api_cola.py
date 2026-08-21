"""Cola de contenido vía API: listar, editar, aprobar/rechazar, regenerar, slots."""
from __future__ import annotations

from datetime import datetime

import pytz

import config
from src import db


def _marca(cx, slug="pensionmas"):
    return db.insert(cx, "accounts", slug=slug, ig_handle="@p", nombre="P", ciudad="CDMX")


def _item(cx, account_id, **campos):
    base = dict(tipo="slideshow", account_id=account_id, status="borrador",
               aprobacion="pendiente", caption="hola", imagen_url="http://x/i.png",
               tema_semilla="tema")
    base.update(campos)
    return db.insert(cx, "content_queue", **base)


def test_editor_lista_y_ve_detalle(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    qid = _item(cx, pid)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.get("/brands/pensionmas/queue")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1 and items[0]["id"] == qid and items[0]["estado"] == "pendiente"
    assert set(items[0]) == {"id", "tipo", "estado", "caption", "imagen_url",
                             "scheduled_datetime", "tema_semilla", "template",
                             "error", "creado_por", "aprobado_por"}
    r = cli.get(f"/brands/pensionmas/queue/{qid}")
    assert r.status_code == 200 and r.json()["id"] == qid and r.json()["estado"] == "pendiente"


def test_otra_marca_403_y_qid_ajeno_404(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx, "pensionmas")
    otra = _marca(cx, "otra")
    qid_otra = _item(cx, otra)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    assert cli.get("/brands/otra/queue").status_code == 403
    assert cli.get(f"/brands/pensionmas/queue/{qid_otra}").status_code == 404
    assert cli.get("/brands/pensionmas/queue/999999").status_code == 404
    assert cli.patch(f"/brands/pensionmas/queue/{qid_otra}", json={"caption": "x"}).status_code == 404
    assert cli.post(f"/brands/pensionmas/queue/{qid_otra}/aprobar").status_code == 404
    assert cli.delete(f"/brands/pensionmas/queue/{qid_otra}").status_code == 404


def test_patch_edita_caption_y_reprograma_choque_409(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    qid = _item(cx, pid)
    ocupado = _item(cx, pid, status="programado", aprobacion="aprobado",
                    scheduled_datetime="2026-09-01T19:00:00-06:00")
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.patch(f"/brands/pensionmas/queue/{qid}", json={"caption": "nuevo caption"})
    assert r.status_code == 200 and r.json()["caption"] == "nuevo caption"

    r = cli.patch(f"/brands/pensionmas/queue/{qid}",
                  json={"scheduled_datetime": "2026-09-01T19:00:00-06:00"})
    assert r.status_code == 409
    assert r.json()["error"] == "conflicto" and r.json()["campo"] == "scheduled_datetime"

    r = cli.patch(f"/brands/pensionmas/queue/{qid}",
                  json={"scheduled_datetime": "2026-09-02T19:00:00-06:00"})
    assert r.status_code == 200 and r.json()["scheduled_datetime"] == "2026-09-02T19:00:00-06:00"

    db.update(cx, "content_queue", ocupado, status="publicado")
    r = cli.patch(f"/brands/pensionmas/queue/{ocupado}", json={"caption": "no se puede"})
    assert r.status_code == 422


def test_patch_scheduled_datetime_invalido_422_campo(api_cliente) -> None:
    """G4: un ISO inválido ("mañana") es 422 validacion/scheduled_datetime,
    no un 500 ni un 422 genérico de "estado"."""
    cli, cx, H = api_cliente
    pid = _marca(cx)
    qid = _item(cx, pid)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))

    r = cli.patch(f"/brands/pensionmas/queue/{qid}", json={"scheduled_datetime": "mañana"})

    assert r.status_code == 422
    assert r.json()["error"] == "validacion"
    assert r.json()["campo"] == "scheduled_datetime"
    assert "ISO" in r.json()["detalle"]


def test_aprobar_no_pendiente_422_y_aprobar_ok(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    qid = _item(cx, pid)
    aprobado = _item(cx, pid, aprobacion="aprobado", status="programado")
    uid = H.usuario("e@x.com", marcas=[(pid, "editor")])
    H.login(uid)

    r = cli.post(f"/brands/pensionmas/queue/{aprobado}/aprobar")
    assert r.status_code == 422

    llamadas = []
    monkeypatch.setattr("src.approval.notificar_resolucion",
                        lambda cx, qid, texto: llamadas.append((qid, texto)) or True)
    tz = pytz.timezone(config.TIMEZONE)
    slot_fijo = tz.localize(datetime(2026, 9, 5, 19, 0))
    monkeypatch.setattr("src.scheduler.next_free_slot_db",
                        lambda cx, account_id, **kw: slot_fijo)
    r = cli.post(f"/brands/pensionmas/queue/{qid}/aprobar")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["scheduled_datetime"] == slot_fijo.isoformat()
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "aprobado" and fila["aprobado_por"] == uid
    assert llamadas and llamadas[0][0] == qid


def test_aprobar_valueerror_o_runtimeerror_422_mensaje_fijo(api_cliente, monkeypatch) -> None:
    """G6: solo (ValueError, RuntimeError) de approval.aprobar se traducen a
    422 con mensaje FIJO (nunca str(e), que podría filtrar detalle interno);
    cualquier otra excepción sube tal cual (bug real, no error de usuario)."""
    cli, cx, H = api_cliente
    pid = _marca(cx)
    qid = _item(cx, pid)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))

    def _revienta_runtime(cx, qid, **kw):
        raise RuntimeError("detalle interno sensible que no debe salir")

    monkeypatch.setattr("src.approval.aprobar", _revienta_runtime)
    r = cli.post(f"/brands/pensionmas/queue/{qid}/aprobar")
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "validacion"
    assert body["detalle"] == "No se pudo aprobar: revisa slots y estado de la fila"
    assert "sensible" not in body["detalle"]


def test_aprobar_excepcion_no_contemplada_no_se_traga(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    qid = _item(cx, pid)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))

    def _revienta_attr(cx, qid, **kw):
        raise AttributeError("bug real, no error de usuario")

    monkeypatch.setattr("src.approval.aprobar", _revienta_attr)
    try:
        r = cli.post(f"/brands/pensionmas/queue/{qid}/aprobar")
    except AttributeError:
        pass
    else:
        assert r.status_code == 500


def test_rechazar_no_pendiente_422_y_rechazar_ok(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    qid = _item(cx, pid)
    rechazado = _item(cx, pid, aprobacion="rechazado", status="descartado")
    uid = H.usuario("e@x.com", marcas=[(pid, "editor")])
    H.login(uid)

    r = cli.post(f"/brands/pensionmas/queue/{rechazado}/rechazar")
    assert r.status_code == 422

    llamadas = []
    monkeypatch.setattr("src.approval.notificar_resolucion",
                        lambda cx, qid, texto: llamadas.append((qid, texto)) or True)
    r = cli.post(f"/brands/pensionmas/queue/{qid}/rechazar")
    assert r.status_code == 200
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "rechazado" and fila["aprobado_por"] == uid
    assert llamadas and llamadas[0][1] == "❌ Rechazado desde el portal"


def test_regenerar_solo_slideshow_pendiente_o_rechazado(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    qid = _item(cx, pid, tipo="slideshow")
    no_slideshow = _item(cx, pid, tipo="meme")
    publicado = _item(cx, pid, tipo="slideshow", status="publicado", aprobacion="aprobado")
    uid = H.usuario("e@x.com", marcas=[(pid, "editor")])
    H.login(uid)

    assert cli.post(f"/brands/pensionmas/queue/{no_slideshow}/regenerar").status_code == 422
    assert cli.post(f"/brands/pensionmas/queue/{publicado}/regenerar").status_code == 422

    r = cli.post(f"/brands/pensionmas/queue/{qid}/regenerar")
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    job = db.get(cx, "jobs", job_id)
    assert job["tipo"] == "slideshow.regenerar" and job["account_id"] == pid
    assert job["creado_por"] == uid
    import json
    assert json.loads(job["payload_json"]) == {"queue_id": qid}


def test_eliminar_204_y_422(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    qid = _item(cx, pid)
    publicado = _item(cx, pid, status="publicado", aprobacion="aprobado")
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    assert cli.delete(f"/brands/pensionmas/queue/{publicado}").status_code == 422
    r = cli.delete(f"/brands/pensionmas/queue/{qid}")
    assert r.status_code == 204
    assert db.get(cx, "content_queue", qid)["status"] == "descartado"


def test_slots_proximos_devuelve_n_isos(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.get("/brands/pensionmas/slots/proximos?n=3")
    assert r.status_code == 200
    slots = r.json()
    assert len(slots) == 3
    for s in slots:
        datetime.fromisoformat(s)


def test_slots_proximos_n_fuera_de_rango_422(api_cliente) -> None:
    """G7: n=0 (y n>50) es 422 — sin límite, un n gigante golpea al scheduler
    con una consulta cara."""
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    assert cli.get("/brands/pensionmas/slots/proximos?n=0").status_code == 422
    assert cli.get("/brands/pensionmas/slots/proximos?n=51").status_code == 422


# ---------- PUT /queue/{qid}/slides (edición slide por slide) ----------

def _show_json_api(n=2):
    import json
    slides = [{"image_urls": [], "image_layout": "single",
               "text_items": [{"text": f"texto {i}"}], "is_cta": False,
               "background_opacity": 0.35, "duration": 3.0, "source": "manual"}
              for i in range(n)]
    return json.dumps({"title": "t", "aspect_ratio": "4:5", "slides": slides,
                       "caption": "cap", "language": "es",
                       "brief": {"tema": "t", "estilo": "tiktok_bold"},
                       "formato": "listicle", "account_slug": "pensionmas"})


def test_editar_slides_202_encola_rerender(api_cliente) -> None:
    import json
    cli, cx, H = api_cliente
    pid = _marca(cx)
    qid = _item(cx, pid, tipo="slideshow", status="programado", aprobacion="aprobado",
                slideshow_json=_show_json_api())
    uid = H.usuario("e@x.com", marcas=[(pid, "editor")])
    H.login(uid)

    r = cli.put(f"/brands/pensionmas/queue/{qid}/slides", json={"slides": [
        {"texts": ["hook nuevo"], "image_url": "https://cdn.example.com/a.jpg"},
        {"texts": ["texto 1"], "image_url": None},
    ]})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    job = db.get(cx, "jobs", job_id)
    assert job["tipo"] == "slideshow.rerender" and job["account_id"] == pid
    assert job["creado_por"] == uid
    assert json.loads(job["payload_json"]) == {"queue_id": qid}
    show = json.loads(db.get(cx, "content_queue", qid)["slideshow_json"])
    assert show["slides"][0]["text_items"][0]["text"] == "hook nuevo"


def test_editar_slides_422_por_estructura_y_estado(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    qid = _item(cx, pid, tipo="slideshow", status="programado", aprobacion="aprobado",
                slideshow_json=_show_json_api())
    publicado = _item(cx, pid, tipo="slideshow", status="publicado", aprobacion="aprobado",
                      slideshow_json=_show_json_api())
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))

    # estructura que no coincide (1 slide en vez de 2)
    r = cli.put(f"/brands/pensionmas/queue/{qid}/slides",
                json={"slides": [{"texts": ["a"], "image_url": None}]})
    assert r.status_code == 422
    # estado no editable
    r = cli.put(f"/brands/pensionmas/queue/{publicado}/slides", json={"slides": [
        {"texts": ["a"], "image_url": None}, {"texts": ["b"], "image_url": None}]})
    assert r.status_code == 422
    # url insegura
    r = cli.put(f"/brands/pensionmas/queue/{qid}/slides", json={"slides": [
        {"texts": ["a"], "image_url": "http://localhost/x.jpg"},
        {"texts": ["b"], "image_url": None}]})
    assert r.status_code == 422


def test_editar_slides_qid_ajeno_404(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    otra = _marca(cx, "otra")
    qid_otra = _item(cx, otra, tipo="slideshow", slideshow_json=_show_json_api())
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.put(f"/brands/pensionmas/queue/{qid_otra}/slides", json={"slides": []})
    assert r.status_code == 404
