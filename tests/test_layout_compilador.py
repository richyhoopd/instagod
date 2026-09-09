"""El diseño visual compila a HTML determinista y renderizable."""
from src.plantillas import contrato, layout

CONTRATO = {
    "aspecto": "4:5",
    "base": list(contrato.CAMPOS_BASE),
    "extras": [{"id": "badge", "tipo": "texto", "etiqueta": "Etiqueta"}],
}
# Catálogo inventado para el test: NO es el catálogo global real, pero sigue
# su misma convención (la familia es el nombre completo, como en
# config.SLIDESHOW_FUENTES) porque `vacio()` ya diseña con "Poppins-Bold" —
# un catálogo con la familia "Poppins" a secas nunca la matchearía y
# `layout.validar()` rechazaría cualquier diseño en blanco por tipografía
# fuera de catálogo.
FUENTES = [
    {"familia": "Poppins-Bold", "archivo": "Poppins-Bold.ttf", "propia": False},
    {"familia": "Tinos", "archivo": "Tinos-Bold.ttf", "propia": False},
]


def _layout(*capas, aspecto="4:5"):
    base = layout.vacio(aspecto)
    if capas:
        base["capas"] = list(capas)
    return base


def test_hay_exactamente_un_nodo_card():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert html.count('class="card"') == 1


def test_el_card_mide_el_lienzo_completo():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert "1080px" in html and "1350px" in html
    html916 = layout.a_html(_layout(aspecto="9:16"), {**CONTRATO, "aspecto": "9:16"},
                            fuentes=FUENTES)
    assert "1920px" in html916


def test_el_html_generado_pasa_la_validacion_del_contrato():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    contrato.validar_html(html, CONTRATO)  # no lanza


def test_es_determinista():
    diseno = _layout()
    assert (layout.a_html(diseno, CONTRATO, fuentes=FUENTES)
            == layout.a_html(diseno, CONTRATO, fuentes=FUENTES))


def test_capa_de_texto_ligada_emite_la_variable():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert "{{ titular }}" in html


def test_capa_con_resaltar_emite_el_filtro():
    capa = {"id": "titular", "tipo": "texto", "x": 0, "y": 0, "w": 1080, "h": 300,
            "z": 1, "campo": "titular", "fuente": "Tinos", "tam": 48, "resaltar": True}
    html = layout.a_html(_layout(capa), CONTRATO, fuentes=FUENTES)
    assert "{{ titular|resaltar }}" in html
    contrato.validar_html(html, CONTRATO)


def test_texto_literal_va_escapado_y_sin_jinja():
    capa = {"id": "fijo", "tipo": "texto", "x": 0, "y": 0, "w": 1080, "h": 200,
            "z": 1, "texto": "<script>alert(1)</script> & \"comillas\"",
            "fuente": "Tinos", "tam": 40}
    html = layout.a_html(_layout(capa), CONTRATO, fuentes=FUENTES)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    contrato.validar_html(html, CONTRATO)


def test_capa_de_imagen_por_archivo_usa_fotos_dir():
    capa = {"id": "sticker", "tipo": "imagen", "x": 800, "y": 40, "w": 200, "h": 200,
            "z": 5, "archivo": "corazon.png", "ajuste": "contain"}
    html = layout.a_html(_layout(capa), CONTRATO, fuentes=FUENTES)
    assert "{{ fotos_dir }}/corazon.png" in html
    contrato.validar_html(html, CONTRATO)


def test_capa_de_imagen_por_campo_usa_la_variable():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert "{{ imagen }}" in html


def test_color_marca_compila_a_la_variable():
    capa = {"id": "franja", "tipo": "caja", "x": 0, "y": 800, "w": 1080, "h": 8,
            "z": 2, "color": "marca"}
    html = layout.a_html(_layout(capa), CONTRATO, fuentes=FUENTES)
    assert "{{ color_marca }}" in html
    contrato.validar_html(html, CONTRATO)


def test_el_orden_de_apilado_sale_como_z_index():
    a = {"id": "abajo", "tipo": "caja", "x": 0, "y": 0, "w": 10, "h": 10, "z": 1,
         "color": "#000000"}
    b = {"id": "arriba", "tipo": "caja", "x": 0, "y": 0, "w": 10, "h": 10, "z": 9,
         "color": "#ffffff"}
    html = layout.a_html(_layout(b, a), CONTRATO, fuentes=FUENTES)
    # Se emiten ordenadas por z, no por el orden de la lista.
    assert html.index('id="capa-abajo"') < html.index('id="capa-arriba"')
    assert "z-index:1" in html and "z-index:9" in html


def test_auto_ajuste_solo_si_alguna_capa_lo_pide():
    con_auto = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert "window.__captionFitted" in con_auto

    capa = {"id": "fijo", "tipo": "texto", "x": 0, "y": 0, "w": 1080, "h": 200,
            "z": 1, "texto": "Fijo", "fuente": "Tinos", "tam": 40, "auto": False}
    sin_auto = layout.a_html(_layout(capa), CONTRATO, fuentes=FUENTES)
    assert "__captionFitted" not in sin_auto
    assert "<script" not in sin_auto


def test_las_font_faces_apuntan_a_fonts_dir_y_nunca_a_la_red():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert "@font-face" in html
    assert "{{ fonts_dir }}" in html
    assert "http://" not in html and "https://" not in html


def test_solo_se_emiten_las_fuentes_que_el_diseno_usa():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert "Poppins" in html
    assert "Tinos-Bold" not in html


def test_rotacion_y_opacidad_salen_al_css():
    capa = {"id": "sticker", "tipo": "imagen", "x": 0, "y": 0, "w": 100, "h": 100,
            "z": 1, "archivo": "s.png", "rot": -8, "opacidad": 0.5}
    html = layout.a_html(_layout(capa), CONTRATO, fuentes=FUENTES)
    assert "rotate(-8deg)" in html
    assert "opacity:0.5" in html


def test_no_excede_el_tope_de_html():
    capas = [{"id": f"c{i}", "tipo": "caja", "x": i, "y": i, "w": 10, "h": 10,
              "z": i, "color": "#010101"} for i in range(layout.MAX_CAPAS)]
    html = layout.a_html(_layout(*capas), CONTRATO, fuentes=FUENTES)
    assert len(html) < contrato.MAX_HTML


def test_valida_antes_de_compilar():
    import pytest
    with pytest.raises(contrato.ContratoInvalido):
        layout.a_html({"v": 1, "capas": []}, CONTRATO, fuentes=FUENTES)


def test_fotos_dir_es_campo_de_sistema():
    assert "fotos_dir" in contrato.CAMPOS_SISTEMA
