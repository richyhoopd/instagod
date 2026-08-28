"""API de planes de contenido masivo."""
import json

from src import db, planes


def _login_editor(api_cliente):
    client, cx, H = api_cliente
    uid = H.usuario("editor@x.mx", marcas=[(1, "editor")])
    H.login(uid)
    return client, cx, uid


def _payload():
    return {"tipo_periodo": "semana", "periodo": "2026-W36",
            "objetivo": "crecer awareness con contenido local",
            "n_piezas": 3, "fuentes_info": ["prompt"]}


def test_crear_plan_encola_job(api_cliente):
    client, cx, uid = _login_editor(api_cliente)
    r = client.post("/brands/gdlscene/plans", json=_payload())
    assert r.status_code == 202, r.text
    body = r.json()
    plan = db.get(cx, "content_plans", body["plan_id"])
    assert plan["estado"] == "proponiendo" and plan["creado_por"] == uid
    job = db.get(cx, "jobs", body["job_id"])
    assert job["tipo"] == "plan.proponer_temas"
    assert json.loads(job["payload_json"])["plan_id"] == body["plan_id"]


def test_crear_plan_valida_periodo_y_topes(api_cliente):
    client, cx, _ = _login_editor(api_cliente)
    malo = dict(_payload(), periodo="2026-09")     # semana con formato de mes
    assert client.post("/brands/gdlscene/plans", json=malo).status_code == 422
    malo = dict(_payload(), n_piezas=31)
    assert client.post("/brands/gdlscene/plans", json=malo).status_code == 422
    malo = dict(_payload(), aspect="3:2")
    assert client.post("/brands/gdlscene/plans", json=malo).status_code == 422
    malo = dict(_payload(), formatos=["inexistente"])
    assert client.post("/brands/gdlscene/plans", json=malo).status_code == 422
    malo = dict(_payload(), fuentes_imagen=["imgur"])
    assert client.post("/brands/gdlscene/plans", json=malo).status_code == 422


def test_marca_ajena_no_ve_planes(api_cliente):
    client, cx, H = api_cliente
    uid = H.usuario("ajeno@x.mx", marcas=[])
    H.login(uid)
    assert client.get("/brands/gdlscene/plans").status_code in (403, 404)


def test_listar_y_detalle(api_cliente):
    client, cx, uid = _login_editor(api_cliente)
    pid = planes.crear(cx, 1, tipo_periodo="mes", periodo="2026-09",
                       objetivo="obj", config={}, creado_por=uid)
    db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="t")
    lista = client.get("/brands/gdlscene/plans").json()
    assert lista[0]["id"] == pid and lista[0]["topics_total"] == 1
    det = client.get(f"/brands/gdlscene/plans/{pid}").json()
    assert len(det["topics"]) == 1 and det["piezas"] == []
    assert client.get("/brands/gdlscene/plans/99999").status_code == 404


def test_curar_topics(api_cliente):
    client, cx, uid = _login_editor(api_cliente)
    pid = planes.crear(cx, 1, tipo_periodo="mes", periodo="2026-09",
                       objetivo="obj", config={}, creado_por=uid)
    db.update(cx, "content_plans", pid, estado="temas")
    tid = db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="tema uno")
    r = client.patch(f"/brands/gdlscene/plans/{pid}/topics/{tid}",
                     json={"estado": "aprobado", "titulo": "tema mejorado"})
    assert r.status_code == 200, r.text
    assert db.get(cx, "plan_topics", tid)["estado"] == "aprobado"
    r = client.post(f"/brands/gdlscene/plans/{pid}/topics",
                    json={"titulo": "manual nuevo"})
    assert r.status_code == 201
    # topic ya generado no se edita
    db.update(cx, "plan_topics", tid, estado="generado", queue_id=1)
    r = client.patch(f"/brands/gdlscene/plans/{pid}/topics/{tid}",
                     json={"titulo": "que no"})
    assert r.status_code == 422


def test_generar_gates(api_cliente):
    client, cx, uid = _login_editor(api_cliente)
    pid = planes.crear(cx, 1, tipo_periodo="mes", periodo="2026-09",
                       objetivo="obj", config={}, creado_por=uid)
    # aún 'proponiendo' → 422
    assert client.post(f"/brands/gdlscene/plans/{pid}/generar").status_code == 422
    db.update(cx, "content_plans", pid, estado="temas")
    # sin temas aprobados → 422
    assert client.post(f"/brands/gdlscene/plans/{pid}/generar").status_code == 422
    db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="t", estado="aprobado")
    r = client.post(f"/brands/gdlscene/plans/{pid}/generar")
    assert r.status_code == 202 and "job_id" in r.json()
    # job vivo → 409
    assert client.post(f"/brands/gdlscene/plans/{pid}/generar").status_code == 409


def test_aprobar_lote(api_cliente, monkeypatch):
    from datetime import datetime

    from api.routers import planes as planes_router

    client, cx, uid = _login_editor(api_cliente)
    pid = planes.crear(cx, 1, tipo_periodo="mes", periodo="2026-09",
                       objetivo="obj", config={}, creado_por=uid)
    db.update(cx, "content_plans", pid, estado="curacion")
    q1 = db.insert(cx, "content_queue", tipo="slideshow", account_id=1, caption="a",
                   imagen_url="[]", plan_id=pid, aprobacion="pendiente", origen="api")
    q2 = db.insert(cx, "content_queue", tipo="slideshow", account_id=1, caption="b",
                   imagen_url="[]", plan_id=pid, aprobacion="pendiente", origen="api")

    def _aprobar_fake(cx_, qid, **kwargs):
        if qid == q2:
            raise ValueError("sin slots")
        db.update(cx_, "content_queue", qid, aprobacion="aprobado", status="programado")
        return datetime(2026, 9, 1, 11, 0)

    monkeypatch.setattr(planes_router.approval, "aprobar", _aprobar_fake)
    r = client.post(f"/brands/gdlscene/plans/{pid}/aprobar", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [a["queue_id"] for a in body["aprobadas"]] == [q1]
    assert body["fallidas"] == [q2]
    assert body["plan_estado"] == "curacion"  # queda 1 pendiente (la fallida)

    def _aprobar_ok(cx_, qid, **kwargs):
        db.update(cx_, "content_queue", qid, aprobacion="aprobado", status="programado")
        return datetime(2026, 9, 1, 15, 0)

    monkeypatch.setattr(planes_router.approval, "aprobar", _aprobar_ok)
    body = client.post(f"/brands/gdlscene/plans/{pid}/aprobar", json={}).json()
    assert body["plan_estado"] == "aprobado"
    assert db.get(cx, "content_plans", pid)["estado"] == "aprobado"


def test_aprobar_subset(api_cliente, monkeypatch):
    from datetime import datetime

    from api.routers import planes as planes_router

    client, cx, uid = _login_editor(api_cliente)
    pid = planes.crear(cx, 1, tipo_periodo="mes", periodo="2026-09",
                       objetivo="obj", config={}, creado_por=uid)
    db.update(cx, "content_plans", pid, estado="curacion")
    q1 = db.insert(cx, "content_queue", tipo="slideshow", account_id=1, caption="a",
                   imagen_url="[]", plan_id=pid, aprobacion="pendiente", origen="api")
    q2 = db.insert(cx, "content_queue", tipo="slideshow", account_id=1, caption="b",
                   imagen_url="[]", plan_id=pid, aprobacion="pendiente", origen="api")
    monkeypatch.setattr(planes_router.approval, "aprobar",
                        lambda cx_, qid, **k: datetime(2026, 9, 1, 11, 0))
    body = client.post(f"/brands/gdlscene/plans/{pid}/aprobar",
                       json={"queue_ids": [q1]}).json()
    assert [a["queue_id"] for a in body["aprobadas"]] == [q1]
    assert q2 not in [a["queue_id"] for a in body["aprobadas"]]
