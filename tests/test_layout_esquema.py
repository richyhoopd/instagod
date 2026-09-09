"""El esquema de un diseño visual: qué se acepta y qué se rechaza."""
import pytest

from src.plantillas import contrato, layout

CONTRATO = {
    "aspecto": "4:5",
    "base": list(contrato.CAMPOS_BASE),
    "extras": [{"id": "badge", "tipo": "texto", "etiqueta": "Etiqueta"}],
}
FAMILIAS = {"Poppins-Bold", "Tinos", "Anton"}


def _capa_texto(**extra):
    base = {"id": "titular", "tipo": "texto", "x": 70, "y": 940, "w": 940, "h": 280,
            "z": 3, "campo": "titular", "fuente": "Tinos", "tam": 58}
    base.update(extra)
    return base


def _layout(*capas):
    return {"v": 1, "lienzo": {"fondo": "#ffffff"},
            "guias": {"cols": 12, "filas": 15, "iman": 8},
            "capas": list(capas) or [_capa_texto()]}


def test_layout_minimo_es_valido():
    layout.validar(_layout(), CONTRATO, familias=FAMILIAS)


def test_vacio_es_valido_en_los_dos_aspectos():
    for aspecto in ("4:5", "9:16"):
        c = {**CONTRATO, "aspecto": aspecto}
        layout.validar(layout.vacio(aspecto), c, familias=FAMILIAS)


def test_version_desconocida_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="versión"):
        layout.validar({**_layout(), "v": 7}, CONTRATO, familias=FAMILIAS)


def test_ids_repetidos_se_rechazan():
    with pytest.raises(contrato.ContratoInvalido, match="repetido"):
        layout.validar(_layout(_capa_texto(), _capa_texto(z=4)), CONTRATO, familias=FAMILIAS)


def test_id_con_forma_rara_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="nombre"):
        layout.validar(_layout(_capa_texto(id="Titular Grande")), CONTRATO, familias=FAMILIAS)


def test_capa_de_texto_ligada_a_campo_no_declarado_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="no está en el diseño"):
        layout.validar(_layout(_capa_texto(campo="inventado")), CONTRATO, familias=FAMILIAS)


def test_capa_de_texto_sin_campo_ni_literal_se_rechaza():
    capa = _capa_texto()
    del capa["campo"]
    with pytest.raises(contrato.ContratoInvalido, match="qué texto"):
        layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)


def test_capa_de_texto_con_campo_y_literal_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="qué texto"):
        layout.validar(_layout(_capa_texto(texto="Hola")), CONTRATO, familias=FAMILIAS)


def test_texto_literal_si_es_valido():
    capa = _capa_texto(texto="GDL SCENE")
    del capa["campo"]
    layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)


def test_tipografia_fuera_del_catalogo_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="tipografía"):
        layout.validar(_layout(_capa_texto(fuente="Comic Sans")), CONTRATO, familias=FAMILIAS)


def test_sin_catalogo_no_se_valida_la_tipografia():
    layout.validar(_layout(_capa_texto(fuente="Comic Sans")), CONTRATO)


def test_resaltar_sobre_literal_se_rechaza():
    capa = _capa_texto(texto="Hola", resaltar=True)
    del capa["campo"]
    with pytest.raises(contrato.ContratoInvalido, match="resaltado"):
        layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)


def test_imagen_con_archivo_inseguro_se_rechaza():
    capa = {"id": "sticker", "tipo": "imagen", "x": 0, "y": 0, "w": 100, "h": 100,
            "z": 2, "archivo": "../../etc/passwd"}
    with pytest.raises(contrato.ContratoInvalido, match="archivo"):
        layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)


def test_imagen_con_campo_y_archivo_se_rechaza():
    capa = {"id": "foto", "tipo": "imagen", "x": 0, "y": 0, "w": 1080, "h": 880,
            "z": 1, "campo": "imagen", "archivo": "sticker.png"}
    with pytest.raises(contrato.ContratoInvalido, match="de dónde"):
        layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)


def test_color_invalido_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="color"):
        layout.validar(_layout(_capa_texto(color="rojo")), CONTRATO, familias=FAMILIAS)


def test_color_marca_es_valido():
    layout.validar(_layout(_capa_texto(color="marca")), CONTRATO, familias=FAMILIAS)


def test_medidas_fuera_de_rango_se_rechazan():
    with pytest.raises(contrato.ContratoInvalido, match="medida"):
        layout.validar(_layout(_capa_texto(w=99999)), CONTRATO, familias=FAMILIAS)


def test_demasiadas_capas_se_rechazan():
    capas = [_capa_texto(id=f"t{i}", z=i) for i in range(layout.MAX_CAPAS + 1)]
    with pytest.raises(contrato.ContratoInvalido, match="capas"):
        layout.validar(_layout(*capas), CONTRATO, familias=FAMILIAS)


def test_sin_capas_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="vacío"):
        layout.validar({**_layout(), "capas": []}, CONTRATO, familias=FAMILIAS)


def test_vacio_pasa_validacion_contra_el_catalogo_global():
    """El diseño en blanco tiene que sobrevivir al catálogo real, no a uno de mentira."""
    import config
    familias = set(config.SLIDESHOW_FUENTES)
    for aspecto in layout.LIENZO:
        c = {**CONTRATO, "aspecto": aspecto}
        layout.validar(layout.vacio(aspecto), c, familias=familias)


def test_imagen_sin_campo_ni_archivo_se_rechaza():
    """Imagen que no dice de dónde sale es inválida."""
    capa = {"id": "foto", "tipo": "imagen", "x": 0, "y": 0, "w": 1080, "h": 880, "z": 1}
    with pytest.raises(contrato.ContratoInvalido, match="de dónde"):
        layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)


def test_caja_valida():
    """Una capa de caja con color válido pasa la validación."""
    capa = {"id": "fondo_oscuro", "tipo": "caja", "x": 0, "y": 0, "w": 1080, "h": 400,
            "z": 1, "color": "#2a2a2a", "radio": 0}
    layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)


def test_caja_con_color_invalido_se_rechaza():
    """Una capa de caja con color inválido se rechaza."""
    capa = {"id": "fondo_oscuro", "tipo": "caja", "x": 0, "y": 0, "w": 1080, "h": 400,
            "z": 1, "color": "rojo", "radio": 0}
    with pytest.raises(contrato.ContratoInvalido, match="color"):
        layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)
