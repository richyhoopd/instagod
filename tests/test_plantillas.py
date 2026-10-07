"""CRUD y versionado de plantillas de marca."""
from __future__ import annotations

import json

import pytest

from src import db, plantillas
from src.plantillas import contrato as c
from src.plantillas import layout


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _ct(extras=None) -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": extras or []}


_HTML = ("<div class='card' style='color:{{ color_marca }}'>"
         "<img src='{{ imagen }}'><h1>{{ titular }}</h1>"
         "<img src='{{ logo }}'><span>{{ handle }}</span></div>")


def test_crear_deja_v1(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Clásica", _HTML, _ct(), origen="seed")
    fila = plantillas.obtener(cx, tid)
    assert fila["slug"] == "clasica"
    assert fila["version_actual"] == 1
    assert len(plantillas.versiones(cx, tid)) == 1


def test_crear_rechaza_html_con_variable_inventada(tmp_path) -> None:
    cx = _cx(tmp_path)
    malo = _HTML + "{{ inventada }}"
    with pytest.raises(c.ContratoInvalido):
        plantillas.crear(cx, 1, "Mala", malo, _ct())
    assert plantillas.listar(cx, 1) == []


def test_crear_rechaza_contrato_sin_campo_base(tmp_path) -> None:
    cx = _cx(tmp_path)
    ct = _ct()
    ct["base"] = ["titular"]
    with pytest.raises(c.ContratoInvalido):
        plantillas.crear(cx, 1, "Mala", _HTML, ct)


def test_nueva_version_incrementa_y_no_pisa(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Clásica", _HTML, _ct())
    v2 = plantillas.nueva_version(cx, tid, _HTML.replace("</div>", "<!--verde--></div>"),
                                  _ct(), mensaje_usuario="hazla verde")
    assert v2 == 2
    assert plantillas.obtener(cx, tid)["version_actual"] == 2
    assert "verde" in plantillas.obtener(cx, tid)["html"]
    assert "verde" not in plantillas.version(cx, tid, 1)["html"]


def test_revertir_agrega_version_nueva(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Clásica", _HTML, _ct())
    plantillas.nueva_version(cx, tid, _HTML.replace("</div>", "<!--v2--></div>"), _ct())
    v3 = plantillas.revertir(cx, tid, 1)
    assert v3 == 3
    assert len(plantillas.versiones(cx, tid)) == 3
    assert plantillas.obtener(cx, tid)["html"] == _HTML


def test_listar_filtra_por_estado_y_cuenta(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Activa", _HTML, _ct())
    plantillas.crear(cx, 1, "Borrador", _HTML, _ct())
    plantillas.activar(cx, tid)
    activas = plantillas.listar(cx, 1, estado="activa")
    assert [t["nombre"] for t in activas] == ["Activa"]


def test_contrato_de_tolera_json_roto(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Clásica", _HTML, _ct())
    db.update(cx, "brand_templates", tid, contrato_json="{roto")
    assert plantillas.contrato_de(plantillas.obtener(cx, tid)) == {}


def test_extras_del_contrato_se_pueden_usar_en_el_html(tmp_path) -> None:
    cx = _cx(tmp_path)
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}])
    html = _HTML + "{% for p in pasos %}<li>{{ p }}</li>{% endfor %}"
    tid = plantillas.crear(cx, 1, "Tips", html, ct)
    assert plantillas.obtener(cx, tid) is not None


def test_crear_guarda_layout_y_lo_devuelve(tmp_path) -> None:
    cx = _cx(tmp_path)
    layout = {"v": 1, "lienzo": {"fondo": "#ffffff"}, "guias": {"cols": 12, "filas": 15,
                                                                  "iman": 8},
              "capas": [{"id": "titular", "tipo": "texto", "x": 0, "y": 0, "w": 1080,
                         "h": 200, "z": 1, "campo": "titular", "fuente": "Poppins-Bold",
                         "tam": 48}]}
    tid = plantillas.crear(cx, 1, "Con layout", _HTML, _ct(), layout=layout)
    fila = plantillas.obtener(cx, tid)
    assert plantillas.layout_de(fila) == layout
    assert plantillas.es_editable(fila) is True


def test_plantilla_sin_layout_es_legacy(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Sin layout", _HTML, _ct())
    fila = plantillas.obtener(cx, tid)
    assert plantillas.layout_de(fila) is None
    assert plantillas.es_editable(fila) is False


def test_nueva_version_guarda_el_layout_en_la_version(tmp_path) -> None:
    cx = _cx(tmp_path)
    layout = {"v": 1, "lienzo": {"fondo": "#ffffff"}, "guias": {"cols": 12, "filas": 15,
                                                                  "iman": 8},
              "capas": [{"id": "titular", "tipo": "texto", "x": 0, "y": 0, "w": 1080,
                         "h": 200, "z": 1, "campo": "titular", "fuente": "Poppins-Bold",
                         "tam": 48}]}
    tid = plantillas.crear(cx, 1, "Versionada", _HTML, _ct(), layout=layout)
    otro = {**layout, "lienzo": {"fondo": "#000000"}}
    plantillas.nueva_version(cx, tid, _HTML, _ct(), layout=otro)
    v2 = plantillas.version(cx, tid, 2)
    assert json.loads(v2["layout_json"])["lienzo"]["fondo"] == "#000000"
    assert plantillas.layout_de(plantillas.obtener(cx, tid))["lienzo"][
        "fondo"] == "#000000"


def test_con_layout_el_html_se_deriva_y_se_ignora_el_que_mandan(tmp_path) -> None:
    cx = _cx(tmp_path)
    layout_ = layout.vacio("4:5")
    tid = plantillas.crear(cx, 1, "Derivado", "<p>basura que se ignora</p>",
                           _ct(), layout=layout_)
    fila = plantillas.obtener(cx, tid)
    assert "basura" not in fila["html"]
    assert 'class="card"' in fila["html"]
    assert "{{ titular }}" in fila["html"]


def test_sin_layout_el_html_se_guarda_tal_cual(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Legacy", _HTML, _ct())
    assert plantillas.obtener(cx, tid)["html"] == _HTML


def test_legacy_con_tipografia_fuera_del_catalogo_no_se_guarda(tmp_path) -> None:
    """Sin layout también se valida: `validar_fuentes` protege al HTML a mano,
    no solo al que compila el editor visual."""
    cx = _cx(tmp_path)
    html = _HTML + "<style>.card{font-family:'Papyrus'}</style>"
    with pytest.raises(c.ContratoInvalido):
        plantillas.crear(cx, 1, "Papyrus a mano", html, _ct())
    assert plantillas.listar(cx, 1) == []


def test_layout_invalido_no_se_guarda(tmp_path) -> None:
    cx = _cx(tmp_path)
    malo = {**layout.vacio("4:5"), "capas": []}
    with pytest.raises(c.ContratoInvalido):
        plantillas.crear(cx, 1, "Malo", "", _ct(), layout=malo)
    assert plantillas.listar(cx, 1) == []


def test_tipografia_fuera_del_catalogo_de_la_marca_no_se_guarda(tmp_path) -> None:
    cx = _cx(tmp_path)
    diseno = layout.vacio("4:5")
    diseno["capas"][1]["fuente"] = "Papyrus"
    with pytest.raises(c.ContratoInvalido, match="tipografía"):
        plantillas.crear(cx, 1, "Papyrus", "", _ct(), layout=diseno)


def test_fuente_propia_de_la_marca_si_se_acepta(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "brand_fonts", account_id=1, familia="Papyrus",
              archivo="papyrus.woff2")
    cx.commit()
    diseno = layout.vacio("4:5")
    diseno["capas"][1]["fuente"] = "Papyrus"
    tid = plantillas.crear(cx, 1, "Papyrus", "", _ct(), layout=diseno)
    assert "Papyrus" in plantillas.obtener(cx, tid)["html"]


def test_el_preview_se_recalcula_si_cambia_solo_el_layout(tmp_path) -> None:
    """Dos layouts distintos que compilan a HTMLs distintos no comparten PNG."""
    from src.plantillas import preview
    cx = _cx(tmp_path)
    l1 = layout.vacio("4:5")
    l2 = {**l1, "lienzo": {"fondo": "#123456"}}
    tid = plantillas.crear(cx, 1, "Cacheada", "", _ct(), layout=l1)
    c1 = preview.clave_de(plantillas.obtener(cx, tid))
    plantillas.nueva_version(cx, tid, "", _ct(), layout=l2)
    c2 = preview.clave_de(plantillas.obtener(cx, tid))
    assert c1 != c2


def test_revertir_recupera_el_layout_viejo(tmp_path) -> None:
    cx = _cx(tmp_path)
    layout = {"v": 1, "lienzo": {"fondo": "#ffffff"}, "guias": {"cols": 12, "filas": 15,
                                                                  "iman": 8},
              "capas": [{"id": "titular", "tipo": "texto", "x": 0, "y": 0, "w": 1080,
                         "h": 200, "z": 1, "campo": "titular", "fuente": "Poppins-Bold",
                         "tam": 48}]}
    tid = plantillas.crear(cx, 1, "Reversible", _HTML, _ct(), layout=layout)
    plantillas.nueva_version(cx, tid, _HTML, _ct(),
                             layout={**layout, "lienzo": {"fondo": "#000000"}})
    plantillas.revertir(cx, tid, 1)
    assert plantillas.layout_de(plantillas.obtener(cx, tid))["lienzo"][
        "fondo"] == "#ffffff"


# ---------- despacho v1/v2 ----------

def test_crear_y_versionar_con_escena_v2(tmp_path) -> None:
    from src.plantillas import escena
    cx = _cx(tmp_path)
    esc = escena.normalizar(None, "4:5")
    tid = plantillas.crear(cx, 1, "V2", "", _ct(), layout=esc)
    fila = plantillas.obtener(cx, tid)
    assert plantillas.layout_de(fila)["v"] == 2
    assert 'class="card"' in fila["html"] and "capa-titular" in fila["html"]
    esc["capas"][1]["estilo"]["fontSize"] = 90
    plantillas.nueva_version(cx, tid, "", _ct(), layout=esc)
    assert "font-size:90px" in plantillas.obtener(cx, tid)["html"]


def test_escena_v2_invalida_es_contrato_invalido(tmp_path) -> None:
    from src.plantillas import escena
    cx = _cx(tmp_path)
    esc = escena.normalizar(None, "4:5")
    esc["capas"][1]["estilo"]["fontFamily"] = "Papyrus"
    with pytest.raises(plantillas.ContratoInvalido, match="tipograf"):
        plantillas.crear(cx, 1, "Mala", "", _ct(), layout=esc)


def test_escena_de_normaliza_y_layout_de_no(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "V1", "", _ct(), layout=layout.vacio("4:5"))
    fila = plantillas.obtener(cx, tid)
    assert plantillas.layout_de(fila)["v"] == 1
    assert plantillas.escena_de(fila)["v"] == 2
    assert plantillas.escena_de(fila)["lienzo"]["formato"] == "4x5"


def test_escena_de_un_legacy_es_none(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Legacy", _HTML, _ct())
    assert plantillas.escena_de(plantillas.obtener(cx, tid)) is None


def test_compilar_despacha_por_version() -> None:
    from src.plantillas import escena
    ct = _ct()
    assert plantillas.compilar(layout.vacio("4:5"), ct) == layout.a_html(layout.vacio("4:5"), ct)
    esc = escena.normalizar(None, "4:5")
    assert plantillas.compilar(esc, ct) == escena.a_html(esc, ct)
    with pytest.raises(plantillas.ContratoInvalido):
        plantillas.validar_diseno({"v": 3}, ct)


@pytest.mark.parametrize("malo", [{"v": 3}, {"v": "2"}, {}, {"v": None}, [], "x", None])
def test_version_desconocida_o_malformada_es_contrato_invalido(malo) -> None:
    with pytest.raises(plantillas.ContratoInvalido):
        plantillas.compilar(malo, _ct())
    with pytest.raises(plantillas.ContratoInvalido):
        plantillas.validar_diseno(malo, _ct())


def test_v1_en_servicio_html_identico_al_compilador_v1(tmp_path) -> None:
    """Las plantillas v1 de producción deben dar el mismo HTML que antes."""
    cx = _cx(tmp_path)
    lay = layout.vacio("4:5")
    tid = plantillas.crear(cx, 1, "V1", "", _ct(), layout=lay)
    assert plantillas.obtener(cx, tid)["html"] == layout.a_html(
        lay, _ct(), fuentes=plantillas.fuentes_tipograficas.catalogo(cx, 1))
