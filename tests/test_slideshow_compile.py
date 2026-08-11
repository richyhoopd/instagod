"""Compilador determinista: guion + preset de estilo → contrato Slideshow."""
from __future__ import annotations

from dataclasses import dataclass

import config
from src import slideshow_compile as sc
from src import slideshow_model as sm


@dataclass
class _Img:
    ruta_o_url: str
    source: str = "pexels"


def _guion(n=3):
    slides = [{"text": "Gancho", "rol": "hook", "image_hint": "a"},
              {"text": "Punto uno", "rol": "punto", "image_hint": "b"},
              {"text": "Sígueme", "rol": "cta", "image_hint": "c"}][:n]
    return {"tema": "café", "hook": "Gancho", "caption": "pie", "cta": "Sígueme",
            "slides": slides}


def test_compilar_produce_contrato_valido() -> None:
    imgs = [_Img("/tmp/a.jpg"), _Img("/tmp/b.jpg"), _Img("/tmp/c.jpg")]
    s = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=imgs)
    assert sm.validar(s) == []
    assert len(s.slides) == 3


def test_compilar_aplica_preset_por_rol() -> None:
    imgs = [_Img("/tmp/a.jpg")] * 3
    s = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=imgs)
    preset = config.SLIDESHOW_ESTILOS["tiktok_bold"]
    assert s.slides[0].text_items[0].font == preset["roles"]["hook"]["font"]
    assert s.slides[1].text_items[0].font == preset["roles"]["punto"]["font"]
    assert s.slides[2].is_cta is True


def test_compilar_imagen_none_da_fondo_solido() -> None:
    s = sc.compilar(_guion(), estilo="tiktok_bold",
                    imagenes=[_Img("/tmp/a.jpg"), None, _Img("/tmp/c.jpg")])
    assert s.slides[1].image_urls == []
    assert s.slides[1].background_opacity == 0.0
    assert sm.validar(s) == []


def test_compilar_registra_source_de_la_imagen() -> None:
    s = sc.compilar(_guion(), estilo="tiktok_bold",
                    imagenes=[_Img("/tmp/a.jpg", source="banco")] * 3)
    assert s.slides[0].source == "banco"


def test_compilar_estilo_desconocido() -> None:
    import pytest
    with pytest.raises(KeyError):
        sc.compilar(_guion(), estilo="noexiste", imagenes=[None] * 3)


def test_mismo_guion_dos_estilos_distintos() -> None:
    imgs = [_Img("/tmp/a.jpg")] * 3
    a = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=imgs)
    b = sc.compilar(_guion(), estilo="editorial", imagenes=imgs)
    assert a.slides[0].text_items[0].font != b.slides[0].text_items[0].font
    assert a.slides[0].text_items[0].text == b.slides[0].text_items[0].text


def test_contexto_slide_tiene_llaves_para_la_plantilla() -> None:
    s = sc.compilar(_guion(), estilo="tiktok_bold",
                    imagenes=[_Img("/tmp/a.jpg")] * 3, aspect_ratio="4:5")
    ctx = sc.contexto_slide(s, 0)
    assert ctx["width"] == 1080 and ctx["height"] == 1350
    assert ctx["grid_cols"] == 1 and ctx["grid_rows"] == 1
    assert ctx["image_srcs"][0].startswith("file://")
    assert ctx["items"][0]["px"] > 0
    assert ctx["items"][0]["color"].startswith("#")
    assert ctx["font_faces"][0]["url"].startswith("file://")


def test_contexto_slide_fondo_solido_sin_overlay() -> None:
    s = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=[None] * 3)
    ctx = sc.contexto_slide(s, 0)
    assert ctx["image_srcs"] == []
    assert ctx["overlay_opacity"] == 0.0
    assert ctx["bg_color"] == config.SLIDESHOW_PALETA["negro"]


def test_contexto_slide_fondo_del_preset() -> None:
    """Fondo sólido compilado con estilo=editorial → bg_color=crema (no negro)."""
    s = sc.compilar(_guion(), estilo="editorial", imagenes=[None] * 3)
    ctx = sc.contexto_slide(s, 0)
    assert ctx["image_srcs"] == []
    assert ctx["overlay_opacity"] == 0.0
    assert ctx["bg_color"] == config.SLIDESHOW_PALETA["crema"]


def test_compilar_registra_estilo_en_brief() -> None:
    """compilar registra estilo usado en brief para que contexto_slide lo recupere."""
    imgs = [_Img("/tmp/a.jpg")] * 3
    s = sc.compilar(_guion(), estilo="editorial", imagenes=imgs)
    assert s.brief["estilo"] == "editorial"
    # setdefault: si brief ya tiene estilo, no lo pisa
    s2 = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=imgs,
                     brief={"tema": "test", "estilo": "editorial"})
    assert s2.brief["estilo"] == "editorial"  # respeta el existente
    assert s2.brief["tema"] == "test"  # preserva otros campos


def test_compilar_acepta_estilos_de_marca() -> None:
    estilos = {"pensionmas": {"texto": "blanco", "fondo": "navy",
                              "background_opacity": 0.3,
                              "chrome": {"handle": "@pensionmas", "logo": None},
                              "roles": {"hook": {"font": "Erode-Bold",
                                                 "font_size": "extra_large",
                                                 "text_style": "background",
                                                 "text_vertical_anchor": "center"},
                                        "punto": {"font": "Erode-Semibold",
                                                  "font_size": "large",
                                                  "text_style": "background",
                                                  "text_vertical_anchor": "center"},
                                        "cta": {"font": "Poppins-SemiBold",
                                                "font_size": "medium",
                                                "text_style": "background",
                                                "text_vertical_anchor": "bottom"}}}}
    s = sc.compilar(_guion(), estilo="pensionmas", imagenes=[None] * 3,
                    estilos=estilos, account_slug="pensionmas")
    assert s.brief["fondo"] == "navy"
    assert s.brief["chrome"]["handle"] == "@pensionmas"
    assert s.slides[0].text_items[0].font == "Erode-Bold"
    import config as cfg
    ctx = sc.contexto_slide(s, 0)
    assert ctx["bg_color"] == cfg.SLIDESHOW_PALETA["navy"]
    assert ctx["chrome"] == {"handle": "@pensionmas", "logo_src": None}


def test_contexto_slide_sin_chrome_es_none() -> None:
    s = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=[None] * 3)
    assert sc.contexto_slide(s, 0)["chrome"] is None


def test_font_faces_declaran_formato() -> None:
    s = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=[None] * 3)
    faces = {f["name"]: f["fmt"] for f in sc.contexto_slide(s, 0)["font_faces"]}
    assert faces["Erode-Bold"] == "woff2"
    assert faces["Anton-Regular"] == "truetype"
