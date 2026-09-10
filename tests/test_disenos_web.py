"""Los endpoints del editor de diseños.

Reusa `api_cliente` (tests/conftest.py) para el TestClient + DB temporal,
igual que tests/test_api_posts.py: gdlscene (account_id=1) ya viene sembrada
por db.init_db().
"""
from __future__ import annotations

import pytest

from src import db, plantillas
from src.plantillas import contrato as c
from src.plantillas import layout

_HTML_LEGACY = """<!doctype html><html><head><style>
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
def marca() -> str:
    return "gdlscene"


@pytest.fixture()
def cliente_manager(api_cliente):
    """Cliente autenticado como manager de gdlscene."""
    cli, cx, H = api_cliente
    H.login(H.usuario("manager@x.com", marcas=[(1, "manager")]))
    return cli


@pytest.fixture()
def cliente_editor(api_cliente):
    """Mismo esquema, con rol editor."""
    cli, cx, H = api_cliente
    H.login(H.usuario("editor@x.com", marcas=[(1, "editor")]))
    return cli


@pytest.fixture()
def plantilla_legacy(cx) -> int:
    """Diseño legacy de gdlscene: HTML a mano, sin layout."""
    tid = plantillas.crear(cx, 1, "Legacy", _HTML_LEGACY, _ct())
    plantillas.activar(cx, tid)
    return tid


@pytest.fixture()
def diseno_ajeno(cx) -> int:
    """Diseño de OTRA cuenta, para probar el aislamiento entre marcas."""
    otra_id = db.insert(cx, "accounts", slug="otra", ig_handle="otra",
                        nombre="Otra", ciudad="CDMX")
    tid = plantillas.crear(cx, otra_id, "Ajeno", _HTML_LEGACY, _ct())
    plantillas.activar(cx, tid)
    return tid


def test_crear_diseno_arranca_con_un_lienzo_vacio(cliente_manager, marca):
    r = cliente_manager.post(f"/brands/{marca}/templates",
                             json={"nombre": "Nuevo", "aspecto": "4:5"})
    assert r.status_code == 201
    datos = r.json()
    assert datos["editable"] is True
    assert len(datos["layout"]["capas"]) == 2


def test_un_editor_no_puede_crear_disenos(cliente_editor, marca):
    r = cliente_editor.post(f"/brands/{marca}/templates",
                            json={"nombre": "Nuevo", "aspecto": "4:5"})
    assert r.status_code == 403


def test_guardar_crea_una_version_nueva(cliente_manager, marca):
    tid = cliente_manager.post(f"/brands/{marca}/templates",
                               json={"nombre": "V", "aspecto": "4:5"}).json()["id"]
    nuevo_layout = layout.vacio("4:5")
    nuevo_layout["capas"][1]["tam"] = 90
    r = cliente_manager.patch(f"/brands/{marca}/templates/{tid}",
                              json={"layout": nuevo_layout, "mensaje": "Titular más grande"})
    assert r.status_code == 200
    assert r.json()["version_actual"] == 2
    versiones = cliente_manager.get(f"/brands/{marca}/templates/{tid}/versions").json()
    assert len(versiones) == 2
    assert versiones[0]["mensaje"] == "Titular más grande"


def test_guardar_un_diseno_invalido_explica_el_problema(cliente_manager, marca):
    tid = cliente_manager.post(f"/brands/{marca}/templates",
                               json={"nombre": "V", "aspecto": "4:5"}).json()["id"]
    nuevo_layout = layout.vacio("4:5")
    nuevo_layout["capas"][1]["fuente"] = "Papyrus"
    r = cliente_manager.patch(f"/brands/{marca}/templates/{tid}", json={"layout": nuevo_layout})
    assert r.status_code == 422
    assert "tipograf" in r.json()["detail"].lower()


def test_revertir_recupera_la_version_anterior(cliente_manager, marca):
    tid = cliente_manager.post(f"/brands/{marca}/templates",
                               json={"nombre": "V", "aspecto": "4:5"}).json()["id"]
    nuevo_layout = layout.vacio("4:5")
    nuevo_layout["capas"][1]["tam"] = 90
    cliente_manager.patch(f"/brands/{marca}/templates/{tid}", json={"layout": nuevo_layout})
    r = cliente_manager.post(f"/brands/{marca}/templates/{tid}/revert/1")
    assert r.status_code == 200
    assert r.json()["layout"]["capas"][1]["tam"] == 64


def test_un_diseno_legacy_se_ve_pero_no_se_edita(cliente_manager, marca, plantilla_legacy):
    r = cliente_manager.get(f"/brands/{marca}/templates/{plantilla_legacy}")
    assert r.status_code == 200
    assert r.json()["editable"] is False
    assert r.json()["layout"] is None


def test_duplicar_un_legacy_lo_vuelve_editable(cliente_manager, marca, plantilla_legacy):
    r = cliente_manager.post(f"/brands/{marca}/templates/{plantilla_legacy}/duplicate")
    assert r.status_code == 201
    assert r.json()["editable"] is True
    assert "editable" in r.json()["nombre"]


def test_no_se_puede_tocar_el_diseno_de_otra_marca(cliente_manager, marca, diseno_ajeno):
    r = cliente_manager.get(f"/brands/{marca}/templates/{diseno_ajeno}")
    assert r.status_code == 404


def test_activar_y_archivar(cliente_manager, marca):
    tid = cliente_manager.post(f"/brands/{marca}/templates",
                               json={"nombre": "V", "aspecto": "4:5"}).json()["id"]
    assert cliente_manager.post(
        f"/brands/{marca}/templates/{tid}/activate").json()["estado"] == "activa"
    assert cliente_manager.post(
        f"/brands/{marca}/templates/{tid}/archive").json()["estado"] == "archivada"


def test_la_lista_por_defecto_solo_trae_activas(cliente_editor, cliente_manager, marca):
    cliente_manager.post(f"/brands/{marca}/templates",
                         json={"nombre": "Borrador", "aspecto": "4:5"})
    nombres = [p["nombre"] for p in
               cliente_editor.get(f"/brands/{marca}/templates").json()]
    assert "Borrador" not in nombres
    nombres = [p["nombre"] for p in cliente_manager.get(
        f"/brands/{marca}/templates?estado=borrador").json()]
    assert "Borrador" in nombres


def test_el_catalogo_de_tipografias(cliente_manager, marca):
    r = cliente_manager.get(f"/brands/{marca}/fonts")
    assert r.status_code == 200
    assert all({"familia", "propia"} <= set(f) for f in r.json())
    assert len(r.json()) > 0


def test_los_stickers_son_las_fotos_de_la_marca(cliente_manager, marca):
    r = cliente_manager.get(f"/brands/{marca}/stickers")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
