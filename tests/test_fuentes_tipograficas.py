"""Catálogo tipográfico por marca: globales + propias."""
from __future__ import annotations

import config
from src import db, marcas
from src.plantillas import contrato as c
from src.plantillas import fuentes_tipograficas as ft


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_el_catalogo_trae_las_globales(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    fams = ft.familias(cx, m.id)
    assert "Anton-Regular" in fams and "Tinos-Regular" in fams


def test_tinos_italic_esta_en_el_catalogo() -> None:
    """Existe en disco y las plantillas de gdlscene la usan."""
    assert "Tinos-Italic" in config.SLIDESHOW_FUENTES


def test_las_propias_de_la_marca_se_suman(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    db.insert(cx, "brand_fonts", account_id=m.id, familia="MiFuente",
              archivo="fonts/mifuente.woff2")
    cat = ft.catalogo(cx, m.id)
    propia = next(f for f in cat if f["familia"] == "MiFuente")
    assert propia["propia"] is True
    assert any(f["familia"] == "Anton-Regular" and not f["propia"] for f in cat)


def test_una_propia_pisa_a_la_global_del_mismo_nombre(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    db.insert(cx, "brand_fonts", account_id=m.id, familia="Anton-Regular",
              archivo="fonts/anton-custom.woff2")
    cat = [f for f in ft.catalogo(cx, m.id) if f["familia"] == "Anton-Regular"]
    assert len(cat) == 1 and cat[0]["propia"] is True


def test_el_catalogo_aisla_marcas(tmp_path) -> None:
    cx = _cx(tmp_path)
    otra = db.insert(cx, "accounts", slug="otra", ig_handle="otra",
                     nombre="Otra", ciudad="CDMX")
    db.insert(cx, "brand_fonts", account_id=otra, familia="Ajena",
              archivo="fonts/ajena.woff2")
    m = marcas.cargar(cx, "gdlscene")
    assert "Ajena" not in ft.familias(cx, m.id)
    assert "Ajena" in ft.familias(cx, otra)


def test_validar_fuentes_acepta_las_del_catalogo() -> None:
    html = "<style>.card{font-family:'Anton-Regular',sans-serif}</style>"
    assert c.validar_fuentes(html, {"Anton-Regular"}) == []


def test_validar_fuentes_rechaza_una_inventada() -> None:
    html = "<style>.card{font-family:'Helvetica Neue Ultra',sans-serif}</style>"
    errs = c.validar_fuentes(html, {"Anton-Regular"})
    assert errs and "Helvetica Neue Ultra" in errs[0]


def test_validar_fuentes_tolera_genericas() -> None:
    """sans-serif, serif y monospace no son fuentes que haya que tener."""
    html = "<style>.card{font-family:sans-serif} .x{font-family:monospace}</style>"
    assert c.validar_fuentes(html, set()) == []


def test_html_demasiado_grande_se_rechaza() -> None:
    import pytest
    grande = "<div class='card'>" + "x" * (c.MAX_HTML + 1) + "</div>"
    ct = {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": []}
    with pytest.raises(c.ContratoInvalido, match="grande"):
        c.validar_html(grande, ct)


# --- Pilas CSS y @font-face: lo que aprendimos rechazando gdlscene ---------
#
# Un primer intento de `validar_fuentes` rechazaba LAS CUATRO plantillas que
# gdlscene ya publica. La causa: dos espacios de nombres distintos. Las claves
# del catálogo son nombres de archivo (`Tinos-Regular`) y las plantillas
# declaran su propio @font-face con familias CSS cortas (`Tinos`). Una
# plantilla puede llamar a su familia como quiera; lo que no puede es apuntar
# a un archivo que no existe, o a la red.

_CAT_FAMS = {"Anton-Regular", "Tinos-Regular"}
_CAT_ARCH = {"Anton-Regular.ttf", "Tinos-Regular.ttf"}


def test_una_familia_autodeclarada_es_valida() -> None:
    html = ("<style>@font-face{font-family:'Tinos';"
            "src:url('{{ fonts_dir }}/Tinos-Regular.ttf')}"
            ".card{font-family:'Tinos',serif}</style>")
    assert c.validar_fuentes(html, _CAT_FAMS, archivos=_CAT_ARCH) == []


def test_solo_se_exige_la_primera_familia_de_la_pila() -> None:
    """Así funcionan las pilas CSS: la primera es la intención, el resto es
    degradación elegante. gdlscene escribe 'Tinos','Times New Roman',serif."""
    html = ("<style>@font-face{font-family:'Tinos';"
            "src:url('{{ fonts_dir }}/Tinos-Regular.ttf')}"
            ".card{font-family:'Tinos','Times New Roman',serif}</style>")
    assert c.validar_fuentes(html, _CAT_FAMS, archivos=_CAT_ARCH) == []


def test_la_primera_de_la_pila_si_se_exige() -> None:
    html = "<style>.card{font-family:'Comic Papyrus','Tinos-Regular',serif}</style>"
    errs = c.validar_fuentes(html, _CAT_FAMS, archivos=_CAT_ARCH)
    assert errs and "Comic Papyrus" in errs[0]


def test_rechaza_un_webfont_de_la_red() -> None:
    """El riesgo real: el día que falle el DNS se publica un post con la
    tipografía equivocada, y ya publicado no se arregla."""
    html = ("<style>@font-face{font-family:'Inter';"
            "src:url('https://fonts.gstatic.com/s/inter.woff2')}</style>")
    errs = c.validar_fuentes(html, _CAT_FAMS, archivos=_CAT_ARCH)
    assert errs and "red" in errs[0]


def test_rechaza_un_webfont_protocol_relative() -> None:
    html = ("<style>@font-face{font-family:'Inter';"
            "src:url('//cdn.tipos.com/inter.woff2')}</style>")
    assert c.validar_fuentes(html, _CAT_FAMS, archivos=_CAT_ARCH)


def test_rechaza_un_archivo_que_no_esta_en_el_catalogo() -> None:
    html = ("<style>@font-face{font-family:'X';"
            "src:url('{{ fonts_dir }}/NoExiste.ttf')}</style>")
    errs = c.validar_fuentes(html, _CAT_FAMS, archivos=_CAT_ARCH)
    assert errs and "NoExiste.ttf" in errs[0]


def test_el_parseo_sobrevive_a_las_llaves_de_jinja() -> None:
    """`@font-face\\s*\\{([^}]*)\\}` se corta en el `}}` de {{ fonts_dir }} y
    parsea la plantilla a medias. Por eso las expresiones Jinja se neutralizan
    antes de tocar el CSS."""
    html = ("<style>@font-face{font-family:'Tinos';"
            "src:url('{{ fonts_dir }}/Tinos-Regular.ttf')}</style>")
    assert "Tinos" in c._familias_autodeclaradas(html)


def test_las_cuatro_de_gdlscene_pasan_su_propia_validacion(tmp_path) -> None:
    """El test que cierra el círculo: si el validador rechaza los diseños que
    ya se publican, el validador está mal, no los diseños."""
    from src import marcas, plantillas
    from src.seeds import plantillas_gdlscene

    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    plantillas_gdlscene.sembrar(cx, m.id)
    cat = ft.catalogo(cx, m.id)
    fams = {f["familia"] for f in cat}
    arch = {f["archivo"] for f in cat}
    for t in plantillas.listar(cx, m.id):
        assert c.validar_fuentes(t["html"], fams, archivos=arch) == [], t["slug"]
