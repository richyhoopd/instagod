"""Compilador de escena v2 a HTML+CSS+Jinja."""
from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from src.plantillas import contrato, layout
from src.plantillas import escena as E
from src.plantillas.filtros import entorno
from tests.test_escena_esquema import CONTRATO, _escena

FUENTES = [{"familia": "Poppins-Bold", "archivo": "Poppins-Bold.ttf", "propia": False},
           {"familia": "Tinos", "archivo": "Tinos-Bold.ttf", "propia": False}]
SNAPSHOT = Path(__file__).parent / "fixtures" / "escena" / "basica.html"


def test_cumple_lo_que_exigen_contrato_y_compose():
    html = E.a_html(_escena(), CONTRATO, fuentes=FUENTES)
    contrato.validar_html(html, CONTRATO)
    assert contrato.validar_fuentes(html, {"Poppins-Bold", "Tinos"},
                                    archivos={"Poppins-Bold.ttf", "Tinos-Bold.ttf"}) == []
    assert html.count('class="card"') == 1
    assert html == E.a_html(_escena(), CONTRATO, fuentes=FUENTES)       # determinista


def test_snapshot():
    html = E.a_html(_escena(), CONTRATO, fuentes=FUENTES)
    assert html == SNAPSHOT.read_text(encoding="utf-8")


def test_tokens_spans_y_texto_fijo():
    html = E.a_html(_escena(), CONTRATO, fuentes=FUENTES)
    assert "color:#1C1A23" in html                                  # token:ink
    assert '<span style="color:#F5C842">' in html                    # span token:accent
    assert "white-space:pre-line" in html                            # \n del texto fijo
    assert "text-wrap:balance" in html
    assert "letter-spacing:-0.03em" in html


def test_imagen_con_campo_y_src_de_respaldo():
    html = E.a_html(_escena(), CONTRATO, fuentes=FUENTES)
    assert "{{ imagen or (assets_dir ~ '/abc123.png') }}" in html
    assert "border-radius:48px" in html
    assert "drop-shadow(0 24px 48px rgba(61,53,128,.35))" in html


def test_marca_shape_svg():
    html = E.a_html(_escena(), CONTRATO, fuentes=FUENTES)
    assert "background:{{ color_marca }}" in html                    # fill token:marca
    assert "url('{{ assets_dir }}/logo.svg')" in html
    assert "<svg" not in html


def test_ocultas_y_grupos_no_se_pintan():
    esc = _escena()
    html = E.a_html(esc, CONTRATO, fuentes=FUENTES)
    assert "capa-c_clip" not in html                                 # oculta
    assert "capa-g_marca" not in html                                # group no pinta
    esc["capas"][5]["oculta"] = True
    html = E.a_html(esc, CONTRATO, fuentes=FUENTES)
    assert "capa-c_logo" not in html and "capa-c_caja" not in html   # hijos del grupo oculto


def test_video_visible():
    esc = _escena()
    esc["capas"][4]["oculta"] = False
    esc["capas"][4]["poster"] = "assets/clip.jpg"
    html = E.a_html(esc, CONTRATO, fuentes=FUENTES)
    assert ('<video src="{{ assets_dir }}/clip.mp4" poster="{{ assets_dir }}/clip.jpg" '
            'muted playsinline preload="auto"') in html
    assert "border-radius:50%" in html


def test_fondos():
    esc = _escena()
    esc["lienzo"]["fondo"] = {"tipo": "imagen", "valor": "fotos/f.jpg"}
    assert "url('{{ fotos_dir }}/f.jpg')" in E.a_html(esc, CONTRATO)
    esc["lienzo"]["fondo"] = {"tipo": "gradiente", "valor": "linear-gradient(#000000, #ffffff)"}
    assert "background:linear-gradient(#000000, #ffffff)" in E.a_html(esc, CONTRATO)


def test_auto_ajuste_y_resaltar():
    v2 = E.v1_a_v2(layout.vacio("4:5"), "4:5")
    ct = {"aspecto": "4:5", "base": list(contrato.CAMPOS_BASE), "extras": []}
    html = E.a_html(v2, ct, fuentes=FUENTES)
    assert "window.__captionFitted" in html and "data-fit" in html
    v2["capas"][1]["auto"] = False
    v2["capas"][1]["resaltar"] = True
    html = E.a_html(v2, ct, fuentes=FUENTES)
    assert "window.__captionFitted" not in html
    assert "{{ titular|resaltar }}" in html


def test_solo_las_fuentes_usadas():
    html = E.a_html(_escena(), CONTRATO, fuentes=FUENTES)
    assert "Poppins-Bold.ttf" in html and "Tinos-Bold.ttf" not in html


def test_valida_antes_de_compilar():
    esc = _escena()
    esc["capas"][0]["estilo"]["fontFamily"] = "Papyrus"
    with pytest.raises(E.EscenaInvalida, match="tipografía"):
        E.a_html(esc, CONTRATO, fuentes=FUENTES)


def test_el_html_renderiza_con_jinja():
    esc = copy.deepcopy(_escena())
    html = E.a_html(esc, CONTRATO, fuentes=FUENTES)
    salida = entorno().from_string(html).render(
        titular="Hola", imagen="", handle="@x", logo="", color_marca="#ff0000",
        badge="", fonts_dir="file:///f", fotos_dir="file:///p", assets_dir="file:///a")
    assert "file:///a/abc123.png" in salida                           # imagen vacía -> respaldo
    assert "background:#ff0000" in salida


# ---------------------------------------------------------------------------
# Seguridad: nada de la escena llega a style="..."/url('...')/Jinja sin pasar
# por la lista blanca de validar, y el texto fijo se escapa.
# ---------------------------------------------------------------------------

def test_spans_cuentan_puntos_de_codigo_no_utf16():
    """desde/hasta son índices de str de Python; un emoji cuenta 1 (en UTF-16, 2)."""
    esc = _escena()
    capa = esc["capas"][0]
    capa["texto"] = "😀 hola mundo"
    capa["estilo"]["spans"] = [{"desde": 2, "hasta": 6, "color": "token:accent"}]
    html = E.a_html(esc, CONTRATO, fuentes=FUENTES)
    assert '<span style="color:#F5C842">hola</span>' in html


def test_texto_fijo_se_escapa():
    esc = _escena()
    capa = esc["capas"][0]
    capa["texto"] = '<script>alert(1)</script> & "x" {a} {% '.replace("{% ", "{ %")
    capa["estilo"]["spans"] = []
    html = E.a_html(esc, CONTRATO, fuentes=FUENTES)
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp;" in html


def test_llaves_sueltas_del_texto_fijo_no_son_jinja():
    esc = _escena()
    capa = esc["capas"][0]
    capa["texto"] = "a { b } % c # d"
    capa["estilo"]["spans"] = []
    html = E.a_html(esc, CONTRATO, fuentes=FUENTES)
    salida = entorno().from_string(html).render(
        titular="", imagen="", handle="", logo="", color_marca="#ff0000", badge="",
        fonts_dir="f", fotos_dir="p", assets_dir="a")
    assert "a { b } % c # d" in salida


@pytest.mark.parametrize("texto", ["{{ 7*7 }}", "{% if 1 %}x{% endif %}", "{# c #}"])
def test_texto_fijo_no_cuela_jinja(texto):
    esc = _escena()
    esc["capas"][0]["texto"] = texto
    esc["capas"][0]["estilo"]["spans"] = []
    with pytest.raises(E.EscenaInvalida, match="llaves de plantilla"):
        E.a_html(esc, CONTRATO, fuentes=FUENTES)


def _con(capa: int, ruta: list[str], valor) -> dict:
    esc = _escena()
    destino = esc["capas"][capa]
    for k in ruta[:-1]:
        destino = destino[k]
    destino[ruta[-1]] = valor
    return esc


ATAQUES = [
    ("fontFamily", _con(0, ["estilo", "fontFamily"], "x';}body{background:red")),
    ("fontFamily", _con(0, ["estilo", "fontFamily"], "{{ config }}")),
    ("color", _con(0, ["estilo", "color"], "red;background:url(http://x)")),
    ("color", _con(0, ["estilo", "color"], "#fff}{{ 1 }}")),
    ("span", _con(0, ["estilo", "spans"], [{"desde": 0, "hasta": 3, "color": 'red"onload="x'}])),
    ("letterSpacing", _con(0, ["estilo", "letterSpacing"], "1px;x:y")),
    ("filter", _con(1, ["estilo", "filter"], "blur(2px);background:url(http://x)")),
    ("filter", _con(1, ["estilo", "filter"], "url(http://x)")),
    ("filter", _con(1, ["estilo", "filter"], "blur(1px)}{{ 1 }}")),
    ("mascara", _con(1, ["mascara"], "rounded:4px;x:y")),
    ("src", _con(1, ["src"], "assets/a');background:url('http://x")),
    ("src", _con(1, ["src"], "assets/../../etc/passwd")),
    ("src", _con(3, ["src"], "http://x/logo.svg")),
    ("fill", _con(2, ["estilo", "fill"], "red;x:y")),
    ("gradiente", _con(2, ["estilo", "borderColor"], "{{ x }}")),
    ("campo", _con(1, ["campo"], "imagen }}{{ config")),
]


@pytest.mark.parametrize("nombre,esc", ATAQUES)
def test_los_ataques_no_llegan_al_html(nombre, esc):
    with pytest.raises(E.EscenaInvalida):
        E.a_html(esc, CONTRATO, fuentes=FUENTES)


@pytest.mark.parametrize("valor", ["linear-gradient(red);x:y", "linear-gradient(red)}{{ 1 }}",
                                   "linear-gradient(url(http://x))", "red"])
def test_fondo_gradiente_hostil(valor):
    esc = _escena()
    esc["lienzo"]["fondo"] = {"tipo": "gradiente", "valor": valor}
    with pytest.raises(E.EscenaInvalida):
        E.a_html(esc, CONTRATO, fuentes=FUENTES)


def test_entrada_mal_tipada_es_escena_invalida_no_typeerror():
    for esc in (None, [], "x", {"v": 2}, {"v": 2, "lienzo": 3}):
        with pytest.raises(E.EscenaInvalida):
            E.a_html(esc, CONTRATO, fuentes=FUENTES)


def test_solo_salen_expresiones_jinja_de_la_lista_blanca():
    """Lo único con {{ }} o {% %} en la salida son variables declaradas o de sistema."""
    esc = _escena()
    esc["capas"][0]["texto"] = "<b>&</b> { } % #"
    esc["capas"][0]["estilo"]["spans"] = []
    html = E.a_html(esc, CONTRATO, fuentes=FUENTES)
    assert "{%" not in html and "{#" not in html
    permitidas = set(contrato.variables_declaradas(CONTRATO)) | {
        "fonts_dir", "fotos_dir", "assets_dir", "color_marca"}
    for expr in re.findall(r"\{\{(.*?)\}\}", html):
        expr = re.sub(r"'[^']*'", "", expr)                      # literales de texto
        nombres = set(re.findall(r"[a-z_][a-z0-9_]*", expr)) - {"or"}
        assert nombres <= permitidas, expr


@pytest.mark.lento
def test_paridad_de_pixeles_v1_y_v2(tmp_path):
    """El mismo diseño v1 y su conversión salen iguales de Chromium (<=1 % de píxeles)."""
    from PIL import Image, ImageChops

    from src import compose

    foto = tmp_path / "foto.png"
    Image.new("RGB", (1080, 1350), (40, 90, 160)).save(foto)
    ct = {"aspecto": "4:5", "base": list(contrato.CAMPOS_BASE), "extras": []}
    v1 = layout.vacio("4:5")
    v1["capas"].append({"id": "caja", "tipo": "caja", "x": 0, "y": 1200, "w": 1080,
                        "h": 150, "z": 0, "color": "marca", "radio": 24, "rot": 0,
                        "opacidad": 1})
    ctx = dict(titular="Hola Guadalajara, esto es una prueba", imagen=foto.as_uri(),
               handle="@x", logo="", color_marca="#ff3366",
               fonts_dir=compose.FONTS_DIR.as_uri(), fotos_dir=tmp_path.as_uri(),
               assets_dir=tmp_path.as_uri())
    salidas = []
    for nombre, html in (("v1", layout.a_html(v1, ct, fuentes=FUENTES)),
                         ("v2", E.a_html(E.v1_a_v2(v1, "4:5"), ct, fuentes=FUENTES))):
        destino = tmp_path / f"{nombre}.png"
        compose.render_html(entorno().from_string(html).render(**ctx), aspecto="4:5",
                            out_path=destino)
        salidas.append(Image.open(destino).convert("RGB"))
    diff = ImageChops.difference(*salidas)
    distintos = sum(1 for p in diff.getdata() if max(p) > 8)
    assert distintos / (1080 * 1350) <= 0.01


# ---------------------------------------------------------------------------
# Revisión: campos ligados a imagen/video y nombres dentro de {{ }}
# ---------------------------------------------------------------------------

CONTRATO_IMG = {"aspecto": "4:5", "base": list(contrato.CAMPOS_BASE),
                "extras": [{"id": "badge", "tipo": "texto", "etiqueta": "Etiqueta"},
                           {"id": "foto2", "tipo": "imagen", "etiqueta": "Foto 2"}]}


@pytest.mark.parametrize("campo", ["titular", "handle", "color_marca", "badge"])
@pytest.mark.parametrize("capa", [1, 4])        # image y video
def test_imagen_y_video_solo_se_ligan_a_campos_de_imagen(capa, campo):
    esc = _escena()
    esc["capas"][capa]["campo"] = campo
    with pytest.raises(E.EscenaInvalida, match="c_foto|c_clip"):
        E.a_html(esc, CONTRATO_IMG, fuentes=FUENTES)


def test_imagen_se_liga_a_imagen_o_extra_de_tipo_imagen():
    esc = _escena()
    esc["capas"][1]["campo"] = "foto2"
    html = E.a_html(esc, CONTRATO_IMG, fuentes=FUENTES)
    assert "{{ foto2 or (assets_dir ~ '/abc123.png') }}" in html
    for campo in ("imagen", "logo"):        # logo: también entra por _to_src (ver reporte)
        esc["capas"][1]["campo"] = campo
        E.a_html(esc, CONTRATO_IMG, fuentes=FUENTES)


def test_extra_con_id_hostil_no_llega_a_jinja():
    ct = {"aspecto": "4:5", "base": list(contrato.CAMPOS_BASE),
          "extras": [{"id": "x }}{{ y", "tipo": "texto", "etiqueta": "x"}]}
    esc = _escena()
    esc["capas"][0]["campo"] = "x }}{{ y"
    with pytest.raises(E.EscenaInvalida, match="identificador|nombre"):
        E.a_html(esc, ct, fuentes=FUENTES)


def test_el_titular_hostil_no_se_ejecuta_en_el_render():
    """Con campo imagen legítimo el dato vive en {{ }}; el atacante no puede ligar el titular."""
    esc = _escena()
    esc["capas"][1]["campo"] = "titular"
    with pytest.raises(E.EscenaInvalida):
        E.a_html(esc, CONTRATO, fuentes=FUENTES)
