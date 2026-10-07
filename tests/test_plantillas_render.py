"""Armado del contexto y render de una plantilla de DB."""
from __future__ import annotations

import hashlib

import pytest
from PIL import Image

from src import compose, db, marcas, plantillas
from src.plantillas import contrato as c
from src.plantillas import render as R
from src.seeds import plantillas_gdlscene

_HTML = """<!doctype html><html><head><style>
 .card {{ width:1080px; height:{h}px; background:{{{{ color_marca }}}};
          color:#fff; font-family:sans-serif; font-size:64px;
          display:flex; align-items:center; justify-content:center; }}
</style></head><body>
 <div class="card">{{{{ titular }}}} — {{{{ handle }}}}</div>
 <script>window.__captionFitted = true;</script></body></html>"""

_CAPTION_EQUIVALENCIA = "Banda local revienta el Foro Independencia"
_PLANTILLAS_CON_BADGE = {"clasica", "verde", "anuncio"}
_PLANTILLAS = ("clasica", "verde", "onion", "anuncio")


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _ct(aspecto="4:5", extras=None) -> dict:
    return {"aspecto": aspecto, "base": list(c.CAMPOS_BASE), "extras": extras or []}


def _sha(ruta) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def test_contexto_inyecta_el_nucleo(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    ctx = R.contexto(m, {"titular": "Hola"})
    assert ctx["titular"] == "Hola"
    assert ctx["handle"].startswith("@")
    assert "color_marca" in ctx and "logo" in ctx and "fonts_dir" in ctx


def test_contexto_no_deja_pasar_none_como_imagen(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    ctx = R.contexto(m, {"titular": "Hola", "imagen": None})
    assert ctx["imagen"] == ""  # nunca None: Jinja lo escribiría como "None"


def test_render_produce_png(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = plantillas.crear(cx, m.id, "Prueba", _HTML.format(h=1350), _ct())
    p = plantillas.obtener(cx, tid)
    png = R.render(cx, m, p, {"titular": "HOLA"}, out_path=tmp_path / "a.png")
    assert png.exists() and png.stat().st_size > 10_000
    assert Image.open(png).size == (1080, 1350)


def test_render_respeta_el_aspecto_de_la_plantilla(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = plantillas.crear(cx, m.id, "Vertical", _HTML.format(h=1920),
                           _ct(aspecto="9:16"))
    p = plantillas.obtener(cx, tid)
    png = R.render(cx, m, p, {"titular": "HOLA"}, out_path=tmp_path / "b.png")
    assert Image.open(png).size == (1080, 1920)


def test_render_rechaza_campos_invalidos(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = plantillas.crear(cx, m.id, "Prueba", _HTML.format(h=1350),
                           _ct(extras=[{"id": "pasos", "tipo": "lista",
                                        "min": 3, "max": 3}]))
    p = plantillas.obtener(cx, tid)
    with pytest.raises(R.CamposInvalidos) as exc:
        R.render(cx, m, p, {"titular": "x", "pasos": ["solo uno"]},
                 out_path=tmp_path / "c.png")
    assert "pasos" in str(exc.value)


def test_render_de_la_onion_sembrada_usa_el_filtro(tmp_path) -> None:
    """La plantilla real de gdlscene, con su filtro `resaltar`, renderiza."""
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    plantillas_gdlscene.sembrar(cx, m.id)
    p = plantillas.por_slug(cx, m.id, "onion")
    png = R.render(cx, m, p, {"titular": "Banda local revienta el foro"},
                   out_path=tmp_path / "onion.png")
    assert png.exists() and png.stat().st_size > 10_000


def _contexto_equivalente() -> dict:
    """Copia de `tests/test_equivalencia_plantillas.py::_contexto_equivalente`.

    Se usa aquí solo para calcular el campos_manuales que hace que
    `render.render()` produzca el mismo contexto que ese archivo arma a mano.
    """
    return {"titular": _CAPTION_EQUIVALENCIA, "imagen": "", "inset": "", "logo": "",
            "handle": compose.DEFAULT_HANDLE, "color_marca": "#1b5e3f",
            "fonts_dir": compose.FONTS_DIR.as_uri(),
            "badge": compose._default_badge()}


@pytest.mark.parametrize("slug", _PLANTILLAS)
def test_render_reproduce_el_png_del_archivo_byte_a_byte(slug, tmp_path) -> None:
    """Verificación extra: `render.render()` (no Jinja a mano) debe producir
    el mismo PNG que produce el archivo de `templates/`, igual que ya lo
    comprueba `tests/test_equivalencia_plantillas.py` pero pasando por el
    módulo nuevo de punta a punta (contrato -> contexto -> Jinja -> Chromium).
    """
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    plantillas_gdlscene.sembrar(cx, m.id)

    viejo = compose.compose(caption=_CAPTION_EQUIVALENCIA, foto_url=None,
                            template=slug, out_path=tmp_path / f"archivo_{slug}.png")

    p = plantillas.por_slug(cx, m.id, slug)
    campos = {"titular": _CAPTION_EQUIVALENCIA}
    if slug in _PLANTILLAS_CON_BADGE:
        campos["badge"] = compose._default_badge()
    nuevo = R.render(cx, m, p, campos, out_path=tmp_path / f"nuevo_{slug}.png")

    assert _sha(nuevo) == _sha(viejo), (
        f"render.render() de '{slug}' no reproduce el PNG del archivo de templates/"
    )


def test_contexto_trae_assets_dir(tmp_path) -> None:
    from src.image_sources import BRANDS_DIR
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    ctx = R.contexto(m, {"titular": "x"})
    assert ctx["assets_dir"] == (BRANDS_DIR / m.slug / "assets").as_uri()
    assert R.contexto(m, {}, assets_dir="file:///tmp/a")["assets_dir"] == "file:///tmp/a"
