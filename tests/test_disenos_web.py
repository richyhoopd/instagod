"""Los endpoints del editor de diseños.

Reusa `api_cliente` (tests/conftest.py) para el TestClient + DB temporal,
igual que tests/test_api_posts.py: gdlscene (account_id=1) ya viene sembrada
por db.init_db().
"""
from __future__ import annotations

import pytest

from src import db, plantillas
from src.plantillas import contrato as c
from src.plantillas import escena, layout

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
    assert r.json()["layout"]["capas"][1]["estilo"]["fontSize"] == 64


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


def test_la_lista_dice_el_estado_y_si_se_puede_editar(cliente_manager, marca):
    """La pantalla de Diseños pinta la etiqueta de estado y decide si abre el
    editor o la vista de solo lectura con la lista, sin pedir cada diseño."""
    cliente_manager.post(f"/brands/{marca}/templates",
                         json={"nombre": "Nuevo", "aspecto": "4:5"})
    lista = cliente_manager.get(
        f"/brands/{marca}/templates?estado=borrador").json()
    nuevo = next(d for d in lista if d["nombre"] == "Nuevo")
    assert nuevo["estado"] == "borrador"
    # Nace con capas, así que se puede editar visualmente.
    assert nuevo["editable"] is True
    # El HTML es derivado: la lista nunca lo expone.
    assert "html" not in nuevo


def test_el_catalogo_de_tipografias(cliente_manager, marca):
    r = cliente_manager.get(f"/brands/{marca}/fonts")
    assert r.status_code == 200
    assert all({"familia", "propia"} <= set(f) for f in r.json())
    assert len(r.json()) > 0


def test_la_tipografia_se_sirve_por_familia(cliente_manager, marca):
    """El lienzo del editor necesita los bytes de la tipografía para dibujar con
    ella. Se piden por familia, que es lo único que el catálogo expone."""
    r = cliente_manager.get(f"/brands/{marca}/files/fonts/Poppins-Bold")
    assert r.status_code == 200
    assert r.headers["content-type"] == "font/ttf"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert len(r.content) > 1000


def test_una_tipografia_que_no_esta_en_el_catalogo_es_404(cliente_manager, marca):
    r = cliente_manager.get(f"/brands/{marca}/files/fonts/Comic-Sans")
    assert r.status_code == 404


def test_la_tipografia_propia_apuntando_fuera_de_las_carpetas_no_se_sirve(
        cx, cliente_manager, marca, tmp_path):
    """`archivo` de una tipografía propia sale de la BD: si algún día se sube por
    el portal, este endpoint no puede volverse un lector de archivos arbitrarios."""
    fuera = tmp_path / "robada.ttf"
    fuera.write_bytes(b"x" * 2000)
    db.insert(cx, "brand_fonts", account_id=1, familia="Robada",
              archivo=str(fuera))
    r = cliente_manager.get(f"/brands/{marca}/files/fonts/Robada")
    assert r.status_code == 404


def test_la_tipografia_de_otra_marca_no_se_ve(cx, cliente_manager, marca):
    """Aislamiento: el catálogo es por cuenta, así que una familia de otra marca
    simplemente no existe aquí."""
    otra = db.insert(cx, "accounts", slug="ajena", ig_handle="ajena",
                     nombre="Ajena", ciudad="CDMX")
    db.insert(cx, "brand_fonts", account_id=otra, familia="Ajena-Bold",
              archivo="Poppins-Bold.ttf")
    r = cliente_manager.get(f"/brands/{marca}/files/fonts/Ajena-Bold")
    assert r.status_code == 404


def test_los_stickers_son_las_fotos_de_la_marca(cliente_manager, marca):
    r = cliente_manager.get(f"/brands/{marca}/stickers")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_pedir_vista_previa_encola_un_trabajo(cliente_manager, marca):
    r = cliente_manager.post(f"/brands/{marca}/templates/preview",
                             json={"layout": layout.vacio("4:5"), "aspecto": "4:5"})
    assert r.status_code == 202
    assert isinstance(r.json()["job_id"], int)


def test_una_vista_previa_invalida_se_rechaza_al_encolar(cliente_manager, marca):
    """No se encola trabajo para un diseño que ya sabemos que no compila."""
    malo = {**layout.vacio("4:5"), "capas": []}
    r = cliente_manager.post(f"/brands/{marca}/templates/preview",
                             json={"layout": malo, "aspecto": "4:5"})
    assert r.status_code == 422


def test_una_vista_previa_con_aspecto_inventado_se_rechaza(cliente_manager, marca):
    """El aspecto solo lo revisa `contrato.validar`: sin esa llamada el trabajo
    se encolaba y reventaba con un KeyError dentro del worker."""
    r = cliente_manager.post(
        f"/brands/{marca}/templates/preview",
        json={"layout": layout.vacio("4:5"), "aspecto": "4:5",
              "contrato": {"aspecto": "16:9", "base": list(c.CAMPOS_BASE),
                           "extras": []}})
    assert r.status_code == 422


def test_un_editor_no_puede_pedir_vista_previa(cliente_editor, marca):
    r = cliente_editor.post(f"/brands/{marca}/templates/preview",
                            json={"layout": layout.vacio("4:5"), "aspecto": "4:5"})
    assert r.status_code == 403


def test_pedirle_un_diseno_al_asistente_encola_un_trabajo(cliente_manager, marca):
    r = cliente_manager.post(f"/brands/{marca}/templates/design",
                             json={"instruccion": "algo minimalista", "aspecto": "4:5"})
    assert r.status_code == 202
    assert isinstance(r.json()["job_id"], int)


def test_un_editor_no_puede_pedirle_un_diseno_al_asistente(cliente_editor, marca):
    r = cliente_editor.post(f"/brands/{marca}/templates/design",
                            json={"instruccion": "algo minimalista", "aspecto": "4:5"})
    assert r.status_code == 403


def test_pedirle_un_diseno_partiendo_de_uno_ajeno_es_404(cliente_manager, marca, diseno_ajeno):
    r = cliente_manager.post(
        f"/brands/{marca}/templates/design",
        json={"instruccion": "hazlo más grande", "aspecto": "4:5",
              "template_id": diseno_ajeno})
    assert r.status_code == 404


def test_crear_devuelve_escena_v2(cliente_manager, marca):
    r = cliente_manager.post(f"/brands/{marca}/templates",
                             json={"nombre": "N", "aspecto": "4:5"})
    assert r.status_code == 201
    assert r.json()["layout"]["v"] == 2
    assert r.json()["layout"]["lienzo"]["formato"] == "4x5"


def test_un_v1_guardado_se_devuelve_como_v2(cliente_manager, marca, cx):
    tid = plantillas.crear(cx, 1, "Viejo", "", _ct(), layout=layout.vacio("4:5"))
    r = cliente_manager.get(f"/brands/{marca}/templates/{tid}")
    assert r.json()["layout"]["v"] == 2
    assert plantillas.layout_de(plantillas.obtener(cx, tid))["v"] == 1   # BD intacta


def test_guardar_v2_y_cambiar_de_formato(cliente_manager, marca, cx):
    tid = cliente_manager.post(f"/brands/{marca}/templates",
                               json={"nombre": "F", "aspecto": "4:5"}).json()["id"]
    esc = cliente_manager.get(f"/brands/{marca}/templates/{tid}").json()["layout"]
    esc = escena.reformatear(esc, "9x16")
    r = cliente_manager.patch(f"/brands/{marca}/templates/{tid}", json={"layout": esc})
    assert r.status_code == 200, r.text
    assert r.json()["aspecto"] == "9:16"
    assert r.json()["layout"]["lienzo"]["h"] == 1920
    assert plantillas.layout_de(plantillas.obtener(cx, tid))["v"] == 2


def test_guardar_v2_invalida_da_422(cliente_manager, marca):
    tid = cliente_manager.post(f"/brands/{marca}/templates",
                               json={"nombre": "M", "aspecto": "4:5"}).json()["id"]
    esc = escena.normalizar(None, "4:5")
    esc["capas"][1]["estilo"]["fontFamily"] = "Papyrus"
    r = cliente_manager.patch(f"/brands/{marca}/templates/{tid}", json={"layout": esc})
    assert r.status_code == 422
    assert "tipograf" in r.json()["detail"].lower()


def test_crear_en_1_1(cliente_manager, marca):
    r = cliente_manager.post(f"/brands/{marca}/templates",
                             json={"nombre": "Cuadro", "aspecto": "1:1"})
    assert r.status_code == 201
    assert r.json()["aspecto"] == "1:1"
    assert r.json()["layout"]["lienzo"]["h"] == 1080


def test_vista_previa_acepta_v2(cliente_manager, marca):
    r = cliente_manager.post(f"/brands/{marca}/templates/preview",
                             json={"layout": escena.normalizar(None, "4:5"), "aspecto": "4:5"})
    assert r.status_code == 202
    assert "job_id" in r.json()


def test_vista_previa_v2_invalida_da_422(cliente_manager, marca):
    esc = escena.normalizar(None, "4:5")
    esc["capas"][1]["x"] = "a"
    r = cliente_manager.post(f"/brands/{marca}/templates/preview",
                             json={"layout": esc, "aspecto": "4:5"})
    assert r.status_code == 422


def test_listar_todas(cliente_manager, marca, cx, plantilla_legacy):
    borrador = plantillas.crear(cx, 1, "Borrador", "", _ct(), layout=layout.vacio("4:5"))
    ids_activas = {t["id"] for t in cliente_manager.get(f"/brands/{marca}/templates").json()}
    ids_todas = {t["id"] for t in
                 cliente_manager.get(f"/brands/{marca}/templates?estado=todas").json()}
    assert plantilla_legacy in ids_activas and borrador not in ids_activas
    assert {plantilla_legacy, borrador} <= ids_todas


def test_listar_todas_no_trae_las_de_otra_marca(cliente_manager, marca, diseno_ajeno):
    ids = {t["id"] for t in
           cliente_manager.get(f"/brands/{marca}/templates?estado=todas").json()}
    assert diseno_ajeno not in ids


def test_listar_estado_invalido_da_422(cliente_manager, marca):
    r = cliente_manager.get(f"/brands/{marca}/templates?estado=zzz")
    assert r.status_code == 422


def test_duplicar_guarda_v2(cliente_manager, marca, cx, plantilla_legacy):
    r = cliente_manager.post(f"/brands/{marca}/templates/{plantilla_legacy}/duplicate")
    nuevo = r.json()["id"]
    assert plantillas.layout_de(plantillas.obtener(cx, nuevo))["v"] == 2
