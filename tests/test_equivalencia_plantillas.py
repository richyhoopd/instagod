"""Las plantillas migradas a la DB deben dibujar IDÉNTICO a sus archivos.

Es el criterio de aceptación de toda la migración: si este test se pone rojo,
las piezas de gdlscene cambiaron de aspecto sin que nadie lo pidiera.

Compara el PNG byte a byte, no el tamaño del archivo. Un smoke test de
"pesa más de 10 KB" no distingue un post bien compuesto de uno con el handle
mal escrito — que es exactamente el bug que este test encontró: el seed
mapeaba `tag_text` a `handle`, y la plantilla onion pasó de decir "GDLSCENE"
a decir "@gdlscene".
"""
from __future__ import annotations

import hashlib

import pytest

from src import compose, db, plantillas
from src.plantillas import filtros
from src.seeds import plantillas_gdlscene

CAPTION = "Banda local revienta el Foro Independencia"
PLANTILLAS = ("clasica", "verde", "onion", "anuncio")


def _sha(ruta) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    plantillas_gdlscene.sembrar(cx, 1)
    return cx


def _contexto_equivalente() -> dict[str, object]:
    """El contexto que el camino viejo arma dentro de `compose()`.

    Dos cosas que NO son obvias y que ya rompieron la equivalencia una vez:
    - Lo vacío va como "" y nunca como None: `_to_src(None)` devuelve "", y
      Jinja escribiría el None de Python como el texto "None" dentro del CSS.
    - `compose()` sustituye un badge por default cuando no le pasan uno
      (`badge_text or _default_badge()`), así que el badge NO es opcional en
      la práctica: es contenido con un valor por omisión.
    """
    return {"titular": CAPTION, "imagen": "", "inset": "", "logo": "",
            "handle": compose.DEFAULT_HANDLE, "color_marca": "#1b5e3f",
            "fonts_dir": compose.FONTS_DIR.as_uri(),
            "badge": compose._default_badge()}


@pytest.mark.parametrize("slug", PLANTILLAS)
def test_la_plantilla_de_db_dibuja_igual_que_el_archivo(slug, tmp_path) -> None:
    cx = _cx(tmp_path)
    viejo = compose.compose(caption=CAPTION, foto_url=None, template=slug,
                            out_path=tmp_path / f"archivo_{slug}.png")

    fila = plantillas.por_slug(cx, 1, slug)
    html = filtros.entorno().from_string(fila["html"]).render(**_contexto_equivalente())
    nuevo = compose.render_html(html, aspecto="4:5",
                                out_path=tmp_path / f"db_{slug}.png")

    assert _sha(nuevo) == _sha(viejo), (
        f"la plantilla '{slug}' de la DB ya no dibuja igual que "
        f"templates/{plantillas_gdlscene._SEEDS[PLANTILLAS.index(slug)]['archivo']}"
    )


def test_el_render_es_determinista(tmp_path) -> None:
    """Sin esto, el test de arriba no significaría nada."""
    hashes = {
        _sha(compose.compose(caption=CAPTION, foto_url=None, template="clasica",
                             out_path=tmp_path / f"r{i}.png"))
        for i in range(3)
    }
    assert len(hashes) == 1


def test_onion_conserva_el_handle_en_mayusculas(tmp_path) -> None:
    """Regresión directa del bug encontrado: tag_text != handle.

    El camino viejo dibuja el handle sin arroba y en mayúsculas
    (`src/compose.py`, tag_text=handle.lstrip("@").upper()). La plantilla en DB
    lo reproduce con el filtro `etiqueta`.
    """
    cx = _cx(tmp_path)
    html = filtros.entorno().from_string(
        plantillas.por_slug(cx, 1, "onion")["html"]
    ).render(**_contexto_equivalente())
    assert ">GDLSCENE<" in html
    assert ">@gdlscene<" not in html
