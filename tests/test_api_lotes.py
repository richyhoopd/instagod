"""API de lotes de memes de banda (gdlscene): planear con criterios, curar, mandar."""
from __future__ import annotations

import json
from datetime import date

from src import db


def _mes_futuro() -> str:
    """Un mes con TODOS sus slots por delante (plan_month ignora los pasados)."""
    hoy = date.today()
    y, m = (hoy.year + 1, hoy.month) if hoy.month == 12 else (hoy.year, hoy.month + 1)
    if m == 12:
        y, m = y + 1, 1
    else:
        m += 1
    return f"{y:04d}-{m:02d}"


def _seed_fotos(cx, n_bandas=4, n_fotos=8) -> None:
    for i in range(n_bandas):
        bid = db.insert(cx, "bands", nombre=f"Banda{i}", prioridad=1,
                        followers_ig=1000 - i, activa=1, tipo="banda")
        for j in range(n_fotos):
            db.insert(cx, "photos", band_id=bid, path=f"b{i}_{j}.jpg",
                      usable_meme=1, usada=0, nitidez=100.0)


def _login_editor(api_cliente):
    client, cx, H = api_cliente
    uid = H.usuario("editor@x.mx", marcas=[(1, "editor")])
    H.login(uid)
    return client, cx, uid


def test_crear_lote_materializa_borrador(api_cliente):
    client, cx, _ = _login_editor(api_cliente)
    _seed_fotos(cx)
    mes = _mes_futuro()
    r = client.post("/brands/gdlscene/lotes", json={"mes": mes, "criterio": "impacto"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mes"] == mes and body["resumen"]["posts"] > 0
    assert len(body["piezas"]) == body["resumen"]["posts"]
    pieza = body["piezas"][0]
    assert pieza["banda"].startswith("Banda") and pieza["photo_id"]
    assert pieza["scheduled_datetime"].startswith(mes)
    filas = db.rows(cx, "SELECT * FROM content_queue WHERE tipo = 'meme'")
    assert filas and all(f["status"] == db.QUEUE_BORRADOR for f in filas)


def test_mes_invalido_y_criterio_invalido(api_cliente):
    client, _, _ = _login_editor(api_cliente)
    assert client.post("/brands/gdlscene/lotes",
                       json={"mes": "2026-13"}).status_code == 422
    assert client.post("/brands/gdlscene/lotes",
                       json={"mes": "2026-10", "criterio": "vibes"}).status_code == 422


def test_segundo_lote_del_mismo_mes_pide_replan(api_cliente):
    client, cx, _ = _login_editor(api_cliente)
    _seed_fotos(cx)
    mes = _mes_futuro()
    assert client.post("/brands/gdlscene/lotes", json={"mes": mes}).status_code == 201
    r = client.post("/brands/gdlscene/lotes", json={"mes": mes})
    assert r.status_code == 409 and r.json()["campo"] == "replan"
    # Con replan sí: el borrador viejo queda descartado, no borrado.
    r = client.post("/brands/gdlscene/lotes", json={"mes": mes, "replan": True})
    assert r.status_code == 201, r.text
    descartadas = cx.execute(
        "SELECT COUNT(*) FROM content_queue WHERE status = ?",
        (db.QUEUE_DESCARTADO,)).fetchone()[0]
    assert descartadas > 0


def test_otra_marca_sin_recetas_no_planea(api_cliente):
    """Ya no hay 422 fijo por no ser gdlscene: sin recetas → 422 sin_recetas;
    la lista de lotes de memes queda vacía y la curación de memes sigue vedada."""
    client, cx, H = api_cliente
    aid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="pm",
                    nombre="Pensión+", ciudad="GDL")
    uid = H.usuario("pm@x.mx", marcas=[(aid, "editor")])
    H.login(uid)
    r = client.post("/brands/pensionmas/lotes", json={"mes": "2026-10"})
    assert r.status_code == 422 and r.json()["error"] == "sin_recetas"
    assert client.get("/brands/pensionmas/lotes").json() == []
    assert client.patch("/brands/pensionmas/lotes/piezas/1",
                        json={"tema_semilla": "x"}).status_code == 422


def test_marca_con_recetas_planea_sin_tocar_memes(api_cliente):
    from src import entidades, recetas
    client, cx, H = api_cliente
    aid = db.insert(cx, "accounts", slug="melaquecapital", ig_handle="mc",
                    nombre="MWRS", ciudad="Melaque")
    recetas.sembrar(cx, aid, recetas.SEMILLA_MELAQUECAPITAL)
    for i in range(3):
        entidades.crear(cx, aid, f"Lote {i}", "lot", slug=f"lote-{i}")
    uid = H.usuario("mc@x.mx", marcas=[(aid, "editor")])
    H.login(uid)
    r = client.post("/brands/melaquecapital/lotes",
                    json={"mes": _mes_futuro(), "piezas": 4})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["estrategia"] == "recetas" and len(body["plan"]) == 4
    assert all(p["receta"] for p in body["plan"]) and body["jobs"] == []
    assert db.rows(cx, "SELECT COUNT(*) n FROM content_queue")[0]["n"] == 0
    r = client.post("/brands/melaquecapital/lotes",
                    json={"mes": _mes_futuro(), "piezas": 2, "generar": True})
    assert len(r.json()["jobs"]) == 2
    tipos = {j["tipo"] for j in db.rows(cx, "SELECT tipo FROM jobs")}
    assert tipos == {"receta.generar"}


def test_sin_permiso_sobre_la_marca(api_cliente):
    client, _, H = api_cliente
    uid = H.usuario("ajeno@x.mx", marcas=[])
    H.login(uid)
    assert client.get("/brands/gdlscene/lotes").status_code in (403, 404)


def test_editar_tema_semilla(api_cliente):
    client, cx, _ = _login_editor(api_cliente)
    _seed_fotos(cx)
    mes = _mes_futuro()
    qid = client.post("/brands/gdlscene/lotes",
                      json={"mes": mes}).json()["piezas"][0]["id"]
    r = client.patch(f"/brands/gdlscene/lotes/piezas/{qid}",
                     json={"tema_semilla": "  ensayo en bodega  "})
    assert r.status_code == 200 and r.json()["tema_semilla"] == "ensayo en bodega"
    assert db.get(cx, "content_queue", qid)["tema_semilla"] == "ensayo en bodega"
    # Vacío = tema libre, no cadena vacía.
    client.patch(f"/brands/gdlscene/lotes/piezas/{qid}", json={"tema_semilla": "   "})
    assert db.get(cx, "content_queue", qid)["tema_semilla"] is None


def test_eliminar_pieza_pone_la_foto_en_lista_negra(api_cliente):
    client, cx, _ = _login_editor(api_cliente)
    _seed_fotos(cx)
    mes = _mes_futuro()
    pieza = client.post("/brands/gdlscene/lotes", json={"mes": mes}).json()["piezas"][0]
    r = client.delete(f"/brands/gdlscene/lotes/piezas/{pieza['id']}")
    assert r.status_code == 200, r.text
    foto = db.get(cx, "photos", pieza["photo_id"])
    assert foto["descartada"] == 1 and foto["usable_meme"] == 0
    # La pieza sale del borrador y entra otra en su slot.
    vieja = db.get(cx, "content_queue", pieza["id"])
    assert vieja["status"] == db.QUEUE_DESCARTADO
    nuevas = client.get(f"/brands/gdlscene/lotes/{mes}").json()["piezas"]
    assert pieza["id"] not in [p["id"] for p in nuevas]


def test_cambiar_pieza_no_la_regresa(api_cliente):
    client, cx, _ = _login_editor(api_cliente)
    _seed_fotos(cx)
    mes = _mes_futuro()
    pieza = client.post("/brands/gdlscene/lotes", json={"mes": mes}).json()["piezas"][0]
    assert client.post(
        f"/brands/gdlscene/lotes/piezas/{pieza['id']}/cambiar").status_code == 200
    foto = db.get(cx, "photos", pieza["photo_id"])
    assert foto["descartada"] == 0  # cambiar NO es lista negra
    assert db.get(cx, "content_queue", pieza["id"])["status"] == db.QUEUE_DESCARTADO


def test_curar_pieza_ajena_o_ya_enviada(api_cliente):
    client, cx, _ = _login_editor(api_cliente)
    _seed_fotos(cx)
    mes = _mes_futuro()
    qid = client.post("/brands/gdlscene/lotes",
                      json={"mes": mes}).json()["piezas"][0]["id"]
    assert client.patch("/brands/gdlscene/lotes/piezas/999999",
                        json={"tema_semilla": "x"}).status_code == 404
    db.update(cx, "content_queue", qid, aprobacion="pendiente")
    r = client.patch(f"/brands/gdlscene/lotes/piezas/{qid}", json={"tema_semilla": "x"})
    assert r.status_code == 409


def test_enviar_encola_job_en_el_worker(api_cliente):
    client, cx, uid = _login_editor(api_cliente)
    _seed_fotos(cx)
    mes = _mes_futuro()
    client.post("/brands/gdlscene/lotes", json={"mes": mes})
    r = client.post(f"/brands/gdlscene/lotes/{mes}/enviar")
    assert r.status_code == 202, r.text
    job = db.get(cx, "jobs", r.json()["job_id"])
    assert job["tipo"] == "lote.enviar" and job["account_id"] == 1
    assert job["creado_por"] == uid
    assert json.loads(job["payload_json"])["mes"] == mes
    # Dos envíos del mismo mes no se pisan.
    assert client.post(f"/brands/gdlscene/lotes/{mes}/enviar").status_code == 409
    assert client.get(f"/brands/gdlscene/lotes/{mes}").json()["job_id"] == job["id"]


def test_enviar_mes_vacio(api_cliente):
    client, _, _ = _login_editor(api_cliente)
    assert client.post(f"/brands/gdlscene/lotes/{_mes_futuro()}/enviar").status_code == 409


def test_listar_meses_con_borrador(api_cliente):
    client, cx, _ = _login_editor(api_cliente)
    _seed_fotos(cx)
    mes = _mes_futuro()
    client.post("/brands/gdlscene/lotes", json={"mes": mes})
    lista = client.get("/brands/gdlscene/lotes").json()
    assert [m["mes"] for m in lista] == [mes]
    assert lista[0]["piezas"] > 0 and lista[0]["job_id"] is None


def test_servir_foto(api_cliente, tmp_path):
    client, cx, _ = _login_editor(api_cliente)
    archivo = tmp_path / "foto.jpg"
    archivo.write_bytes(b"\xff\xd8\xff\xdb jpeg falso")
    bid = db.insert(cx, "bands", nombre="B", prioridad=1, activa=1)
    pid = db.insert(cx, "photos", band_id=bid, path=str(archivo), usable_meme=1)
    r = client.get(f"/brands/gdlscene/lotes/foto/{pid}")
    assert r.status_code == 200 and r.content.startswith(b"\xff\xd8")
    assert client.get("/brands/gdlscene/lotes/foto/999999").status_code == 404
