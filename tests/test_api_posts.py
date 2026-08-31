"""API de posts simples: crear (encola job), listar plantillas y su preview.

Reusa `api_cliente` (tests/conftest.py) para el TestClient + DB temporal +
helpers de sesión, igual que tests/test_api_cola.py. `gdlscene` (account_id=1)
ya viene sembrada por db.init_db().
"""
from __future__ import annotations

import pytest

from src import db, plantillas
from src.plantillas import contrato as c

# Con fondo y tamaño reales (no solo un <div> desnudo): un PNG en blanco
# comprime a unos pocos KB y el test de tamaño (>10 KB) no sirve de nada.
_HTML = """<!doctype html><html><head><style>
 .card { width:1080px; height:1350px; background:{{ color_marca }};
         color:#fff; font-family:sans-serif; font-size:64px;
         display:flex; align-items:center; justify-content:center; }
</style></head><body>
 <div class="card">{{ titular }} — {{ handle }}</div>
 <script>window.__captionFitted = true;</script></body></html>"""


def _ct() -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": []}


@pytest.fixture()
def cx(api_cliente):
    return api_cliente[1]


@pytest.fixture()
def cliente(api_cliente):
    """Cliente autenticado como manager de gdlscene."""
    cli, cx, H = api_cliente
    H.login(H.usuario("manager@x.com", marcas=[(1, "manager")]))
    return cli


@pytest.fixture()
def cliente_editor(api_cliente):
    """Mismo esquema, con rol editor: crear contenido es acción de editor."""
    cli, cx, H = api_cliente
    H.login(H.usuario("editor@x.com", marcas=[(1, "editor")]))
    return cli


@pytest.fixture()
def cliente_ajeno(api_cliente):
    """Usuario válido SIN membresía en gdlscene."""
    cli, cx, H = api_cliente
    H.login(H.usuario("ajeno@x.com"))
    return cli


@pytest.fixture()
def plantilla(cx) -> int:
    """Plantilla activa de gdlscene (account_id=1)."""
    tid = plantillas.crear(cx, 1, "Simple", _HTML, _ct())
    plantillas.activar(cx, tid)
    return tid


@pytest.fixture()
def plantilla_ajena(cx) -> int:
    """Plantilla activa de OTRA cuenta, para probar el aislamiento."""
    otra_id = db.insert(cx, "accounts", slug="otra", ig_handle="otra",
                        nombre="Otra", ciudad="CDMX")
    tid = plantillas.crear(cx, otra_id, "Ajena", _HTML, _ct())
    plantillas.activar(cx, tid)
    return tid


# ---------- POST /brands/{slug}/posts ----------

def test_crear_post_encola_job(cliente, cx, plantilla) -> None:
    r = cliente.post("/brands/gdlscene/posts",
                     json={"template_id": plantilla, "tema": "lo que sea"})
    assert r.status_code == 202
    assert "job_id" in r.json()
    job = db.get(cx, "jobs", r.json()["job_id"])
    assert job["tipo"] == "post.generar" and job["account_id"] == 1


def test_crear_post_con_plantilla_de_otra_marca_es_rechazado(
        cliente, cx, plantilla_ajena) -> None:
    """Aislamiento entre marcas: no puedes usar el diseño de otra cuenta."""
    r = cliente.post("/brands/gdlscene/posts",
                     json={"template_id": plantilla_ajena, "tema": "x"})
    assert r.status_code in (403, 404, 422)
    assert db.rows(cx, "SELECT count(*) c FROM jobs WHERE tipo='post.generar'")[0]["c"] == 0


def test_editor_puede_crear_post(cliente_editor, plantilla) -> None:
    """Crear contenido es acción de editor, no de manager."""
    r = cliente_editor.post("/brands/gdlscene/posts",
                            json={"template_id": plantilla, "tema": "x"})
    assert r.status_code == 202


def test_usuario_sin_membresia_recibe_403(cliente_ajeno, plantilla) -> None:
    r = cliente_ajeno.post("/brands/gdlscene/posts",
                           json={"template_id": plantilla, "tema": "x"})
    assert r.status_code == 403


def test_crear_post_plantilla_inexistente_no_encontrado(cliente, cx) -> None:
    r = cliente.post("/brands/gdlscene/posts",
                     json={"template_id": 999999, "tema": "x"})
    assert r.status_code in (403, 404, 422)
    assert db.rows(cx, "SELECT count(*) c FROM jobs WHERE tipo='post.generar'")[0]["c"] == 0


def test_crear_post_pasa_campos_opcionales_al_payload(cliente, cx, plantilla) -> None:
    import json as _json
    r = cliente.post("/brands/gdlscene/posts", json={
        "template_id": plantilla, "tema": "x",
        "campos": {"titular": "manual"}, "imagen": "https://cdn/x.jpg",
    })
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])
    payload = _json.loads(job["payload_json"])
    assert payload["campos"] == {"titular": "manual"}
    assert payload["imagen"] == "https://cdn/x.jpg"


# ---------- GET /brands/{slug}/templates ----------

def test_listar_plantillas_solo_las_de_la_marca(
        cliente, cx, plantilla, plantilla_ajena) -> None:
    r = cliente.get("/brands/gdlscene/templates")
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert plantilla in ids and plantilla_ajena not in ids


def test_las_plantillas_traen_su_contrato(cliente, plantilla) -> None:
    """El wizard genera el formulario desde `contrato`: si no viaja, no hay UI."""
    fila = next(t for t in cliente.get("/brands/gdlscene/templates").json()
                if t["id"] == plantilla)
    assert "contrato" in fila and "extras" in fila["contrato"]
    assert fila["version_actual"] >= 1   # el ?v= del preview sale de aquí
    assert {"id", "slug", "nombre", "descripcion", "aspecto"} <= set(fila)


def test_listar_plantillas_marca_ajena_403(cliente_ajeno) -> None:
    r = cliente_ajeno.get("/brands/gdlscene/templates")
    assert r.status_code == 403


# ---------- GET /brands/{slug}/templates/{tid}/preview.png ----------

def test_preview_devuelve_png(cliente, plantilla) -> None:
    r = cliente.get(f"/brands/gdlscene/templates/{plantilla}/preview.png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content.startswith(b"\x89PNG") and len(r.content) > 10_000


def test_preview_de_plantilla_ajena_no_se_sirve(cliente, plantilla_ajena) -> None:
    r = cliente.get(f"/brands/gdlscene/templates/{plantilla_ajena}/preview.png")
    assert r.status_code in (403, 404)


def test_preview_de_plantilla_inexistente_404(cliente) -> None:
    r = cliente.get("/brands/gdlscene/templates/999999/preview.png")
    assert r.status_code in (403, 404)


def test_campos_de_muestra_cubre_todos_los_tipos() -> None:
    """Unitario del helper, sin HTTP: una plantilla con un extra de cada
    tipo produce campos que pasan validar_campos."""
    from src.plantillas import preview

    ct = {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": [
        {"id": "t", "tipo": "texto"},
        {"id": "tl", "tipo": "texto_largo"},
        {"id": "n", "tipo": "numero"},
        {"id": "b", "tipo": "booleano"},
        {"id": "l", "tipo": "lista", "min": 2, "max": 4},
        {"id": "i", "tipo": "imagen"},
    ]}
    assert c.validar_campos(preview.campos_de_muestra(ct), ct) == []
