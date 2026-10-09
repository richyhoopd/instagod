"""Del HTML de un kind a una escena v2: el navegador mide, Python traduce.

Ver el DSL en `plantillas/kinds/__init__.py` (data-tipo, data-id, ...).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .. import compose
from ..assets import biblioteca

W, H = 1080, 1350
_RGB = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")
_CLAVES_FUENTE = ("proveedor", "autor", "licencia", "url", "ig_handle")
_ALINEA = {"start": "left", "left": "left", "center": "center", "end": "right", "right": "right",
           "justify": "left"}

_JS = r"""
() => {
  const card = document.querySelector('.card');
  const base = card.getBoundingClientRect();
  const rotDe = (tf) => {
    if (!tf || tf === 'none') return 0;
    const m = new DOMMatrix(tf);
    return Math.round(Math.atan2(m.b, m.a) * 18000 / Math.PI) / 100;
  };
  const PROPS = ['fontFamily','fontSize','fontWeight','lineHeight','letterSpacing','color',
    'textAlign','textTransform','whiteSpace','backgroundColor','backgroundSize',
    'backgroundPosition','borderTopLeftRadius','borderTopWidth','borderTopStyle',
    'borderTopColor','filter','mixBlendMode','paddingTop','paddingRight','paddingBottom',
    'paddingLeft'];
  const textoDe = (el) => {
    let texto = '';
    const spans = [];
    const walk = (n) => {
      for (const c of n.childNodes) {
        if (c.nodeType === 3) texto += c.nodeValue.replace(/[ \t\r\n]+/g, ' ');
        else if (c.nodeName === 'BR') texto += '\n';
        else if (c.dataset && c.dataset.acento !== undefined) {
          const desde = texto.length;
          walk(c);
          spans.push({desde, hasta: texto.length, color: getComputedStyle(c).color});
        } else walk(c);
      }
    };
    walk(el);
    return {texto, spans};
  };
  const limpiarSvg = (svg) => {
    const copia = svg.cloneNode(true);
    for (const n of [copia, ...copia.querySelectorAll('*')]) {
      for (const a of [...n.attributes]) {
        if (a.name.startsWith('data-') || a.name === 'class' || a.name === 'style') n.removeAttribute(a.name);
      }
    }
    return copia.outerHTML;
  };
  const capas = [];
  for (const el of card.querySelectorAll(':scope > [data-tipo]')) {
    const cs = getComputedStyle(el);
    const rot = rotDe(cs.transform);
    const previo = el.style.transform;
    el.style.transform = 'none';
    const r = el.getBoundingClientRect();
    el.style.transform = previo;
    const d = el.dataset;
    const estilo = {};
    for (const p of PROPS) estilo[p] = cs[p];
    estilo.textWrapMode = cs.getPropertyValue('text-wrap-mode') || 'wrap';
    estilo.textWrapStyle = cs.getPropertyValue('text-wrap-style') || 'auto';
    const bg = cs.backgroundImage.match(/url\("?(.*?)"?\)/);
    const capa = {tipo: d.tipo, id: d.id, nombre: d.nombre || d.id, campo: d.campo || null,
      anclaje: d.anclaje || null, valign: d.valign || 'top',
      x: r.left - base.left, y: r.top - base.top, w: r.width, h: r.height, rot,
      opacity: parseFloat(cs.opacity), src: d.src || null, srcUrl: bg ? bg[1] : null,
      recorte: d.recorte !== undefined,
      fuenteAsset: d.fuenteAsset ? JSON.parse(d.fuenteAsset) : null,
      texto: null, spans: null, svg: null, cs: estilo};
    if (d.tipo === 'text' || d.tipo === 'caja') Object.assign(capa, textoDe(el));
    if (d.tipo === 'svg') capa.svg = limpiarSvg(el.querySelector('svg'));
    capas.push(capa);
  }
  return {fondo: {color: getComputedStyle(card).backgroundColor,
                  aplanar: !!card.querySelector('[data-aplanar]')}, capas};
}
"""

_OCULTAR = "() => { for (const el of document.querySelectorAll('.card > [data-tipo]')) el.style.visibility = 'hidden'; }"


# ---------- colores ----------

def css_a_color(css: str | None) -> str | None:
    m = _RGB.fullmatch((css or "").strip())
    if not m:
        return None
    r, g, b = (round(float(v)) for v in m.groups()[:3])
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    if a <= 0.001:
        return None
    if a >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r},{g},{b},{round(a, 3):g})"


def _normal(valor: str) -> str:
    v = valor.strip().lower()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return f"#{h}"
    return css_a_color(v) or v


def tokenizar(color: str | None, tokens: dict[str, str]) -> str | None:
    if color is None:
        return None
    for nombre, valor in tokens.items():
        if _normal(valor) == color:
            return f"token:{nombre}"
    return color


# ---------- medidas ----------

def _px(v: str | None) -> float:
    try:
        return float(str(v).removesuffix("px"))
    except ValueError:
        return 0.0


def anclaje_por_tercio(y: float, h: float) -> str:
    centro = y + h / 2
    if centro < H / 3:
        return "top"
    if centro > 2 * H / 3:
        return "bottom"
    return "center"


def _comunes(c: dict, z: int, *, x=None, y=None, w=None, h=None, cid=None, nombre=None) -> dict:
    x = c["x"] if x is None else x
    y = c["y"] if y is None else y
    w = c["w"] if w is None else w
    h = c["h"] if h is None else h
    capa = {"id": cid or c["id"], "nombre": (nombre or c["nombre"] or c["id"])[:80],
            "x": round(x), "y": round(y),
            "w": max(1, math.ceil(w - 0.01)), "h": max(1, math.ceil(h - 0.01)),
            "rot": float(c["rot"] or 0), "opacity": round(float(c["opacity"]), 3), "z": z,
            "bloqueada": False, "oculta": False,
            "anclaje": c["anclaje"] or anclaje_por_tercio(y, h)}
    if c.get("campo"):
        capa["campo"] = c["campo"]
    return capa


def _estilo_texto(cs: dict, tokens: dict, valign: str) -> dict:
    fs = _px(cs["fontSize"]) or 16.0
    lh = cs["lineHeight"]
    lh = round(_px(lh) / fs, 3) if str(lh).endswith("px") else 1.2
    peso = min(900, max(100, int(round(int(float(cs["fontWeight"])) / 100) * 100)))
    estilo: dict[str, Any] = {
        "fontFamily": cs["fontFamily"].split(",")[0].strip().strip("'\""),
        "fontSize": round(fs), "fontWeight": peso, "lineHeight": min(3.0, max(0.8, lh)),
        "color": tokenizar(css_a_color(cs["color"]), tokens) or "#000000",
        "textAlign": _ALINEA.get(cs["textAlign"], "left"),
        "textTransform": "uppercase" if cs["textTransform"] == "uppercase" else "none",
        "verticalAlign": valign if valign in ("top", "center", "bottom") else "top",
    }
    if cs.get("whiteSpace") == "nowrap" or cs.get("textWrapMode") == "nowrap":
        estilo["textWrap"] = "nowrap"
    elif cs.get("textWrapStyle") in ("balance", "pretty"):
        estilo["textWrap"] = cs["textWrapStyle"]
    else:
        estilo["textWrap"] = "wrap"
    ls = cs.get("letterSpacing", "normal")
    if str(ls).endswith("px") and _px(ls) != 0:
        estilo["letterSpacing"] = f"{_px(ls) / fs:.3f}em"
    return estilo


def _texto(c: dict, z: int, tokens: dict, **geo) -> dict:
    capa = _comunes(c, z, **geo)
    capa["tipo"] = "text"
    capa["texto"] = (c["texto"] or "").replace("{{", "{ {")[:1000]
    estilo = _estilo_texto(c["cs"], tokens, "center" if c["tipo"] == "caja" else c["valign"])
    if c.get("spans") and not c.get("campo"):
        estilo["spans"] = [{"desde": s["desde"], "hasta": s["hasta"],
                            "color": tokenizar(css_a_color(s["color"]), tokens)}
                           for s in c["spans"] if s["hasta"] > s["desde"]]
    capa["estilo"] = estilo
    return capa


def _radio(cs: dict, w: float, h: float) -> int:
    r = cs.get("borderTopLeftRadius", "0px")
    if str(r).endswith("%"):
        return round(min(w, h) / 2)
    return round(min(_px(r), h / 2, w / 2))


def _shape(c: dict, z: int, tokens: dict, **geo) -> dict:
    capa = _comunes(c, z, **geo)
    cs = c["cs"]
    capa["tipo"] = "shape"
    capa["forma"] = "ellipse" if str(cs["borderTopLeftRadius"]).endswith("%") else "rect"
    estilo: dict[str, Any] = {"fill": tokenizar(css_a_color(cs["backgroundColor"]), tokens)
                              or "rgba(0,0,0,0)"}
    if capa["forma"] == "rect":
        estilo["radius"] = _radio(cs, capa["w"], capa["h"])
    if cs.get("borderTopStyle") not in (None, "none") and _px(cs["borderTopWidth"]) > 0:
        estilo["borderWidth"] = round(_px(cs["borderTopWidth"]))
        estilo["borderColor"] = tokenizar(css_a_color(cs["borderTopColor"]), tokens)
    if cs.get("filter") not in (None, "none"):
        estilo["filter"] = cs["filter"]
    if cs.get("mixBlendMode") not in (None, "normal"):
        estilo["mixBlendMode"] = cs["mixBlendMode"]
    capa["estilo"] = estilo
    return capa


def _eje(valor: str, bajo: str, alto: str) -> str:
    v = valor.strip().lower()
    if v in (bajo, "0%", "0", "0px"):
        return bajo
    if v in (alto, "100%"):
        return alto
    return "center"


def _posicion(css: str | None) -> str:
    """background-position computado (p. ej. "50% 50%") a una palabra de `escena.POSICIONES`."""
    partes = (css or "").split()
    if len(partes) != 2:
        return "center"
    x = _eje(partes[0], "left", "right")
    y = _eje(partes[1], "top", "bottom")
    return x if y == "center" else f"{x} {y}"


def _imagen(c: dict, z: int) -> dict:
    capa = _comunes(c, z)
    cs = c["cs"]
    capa["tipo"] = "image"
    capa["ajuste"] = "contain" if cs["backgroundSize"] == "contain" else "cover"
    radio = cs["borderTopLeftRadius"]
    if str(radio).endswith("%"):
        capa["mascara"] = "circle"
    elif _px(radio) > 0:
        capa["mascara"] = f"rounded:{round(_px(radio))}"
    else:
        capa["mascara"] = "none"
    capa["recorte"] = bool(c.get("recorte"))
    if c.get("src"):
        capa["src"] = c["src"]
    if c.get("fuenteAsset"):
        capa["fuente_asset"] = {k: (str(c["fuenteAsset"][k])[:500]
                                    if c["fuenteAsset"].get(k) is not None else None)
                                for k in _CLAVES_FUENTE}
    estilo = {"objectPosition": _posicion(cs.get("backgroundPosition"))}
    if cs.get("filter") not in (None, "none"):
        estilo["filter"] = cs["filter"]
    capa["estilo"] = estilo
    return capa


def _svg(c: dict, z: int, slug: str) -> dict:
    datos = c["svg"].encode("utf-8")
    nombre = hashlib.sha1(datos).hexdigest()[:16] + ".svg"
    destino = biblioteca.ruta_de(slug, nombre)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    capa = _comunes(c, z)
    capa.update({"tipo": "svg", "src": f"assets/{nombre}", "ajuste": "contain"})
    return capa


def a_escena(datos: dict, *, slug: str, tokens: dict, fuente: str,
             fondo_png: bytes | None) -> tuple[dict, dict]:
    capas: list[dict] = []
    muestras: dict[str, str] = {}
    for i, c in enumerate(datos["capas"]):
        z = (i + 1) * 10
        tipo = c["tipo"]
        if tipo == "text":
            capas.append(_texto(c, z, tokens))
        elif tipo == "caja":
            cs = c["cs"]
            pt, pr, pb, pl = (_px(cs[k]) for k in ("paddingTop", "paddingRight",
                                                   "paddingBottom", "paddingLeft"))
            capas.append(_shape(c, z, tokens, cid=f"{c['id']}_fondo",
                                nombre=f"{c['nombre']} (fondo)"))
            capas.append(_texto(c, z + 5, tokens, x=c["x"] + pl, y=c["y"] + pt,
                                w=c["w"] - pl - pr, h=c["h"] - pt - pb))
        elif tipo == "shape":
            capas.append(_shape(c, z, tokens))
        elif tipo == "image":
            capas.append(_imagen(c, z))
        elif tipo == "svg":
            capas.append(_svg(c, z, slug))
        else:
            raise ValueError(f"data-tipo desconocido: {tipo!r}")
        if c.get("campo"):
            muestras[c["campo"]] = c["texto"] if tipo in ("text", "caja") else (c.get("srcUrl") or "")
    if datos["fondo"]["aplanar"] and fondo_png:
        nombre = f"fondo_{uuid.uuid4().hex[:12]}.png"
        destino = biblioteca.ruta_de(slug, nombre)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(fondo_png)
        fondo = {"tipo": "imagen", "valor": f"assets/{nombre}"}
    else:
        fondo = {"tipo": "color",
                 "valor": tokenizar(css_a_color(datos["fondo"]["color"]), tokens) or "#ffffff"}
    escena = {"v": 2, "lienzo": {"w": W, "h": H, "formato": "4x5", "fondo": fondo},
              "tokens": {"colores": dict(tokens), "fuente": fuente}, "capas": capas}
    return escena, muestras


def _medir(html: str) -> tuple[bytes, dict, bytes | None]:
    from playwright.sync_api import sync_playwright

    compose.OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".html", dir=compose.OUT_DIR,
                                     delete=False, encoding="utf-8") as f:
        f.write(html)
        ruta = Path(f.name)
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch()
            try:
                pag = nav.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
                pag.goto(ruta.as_uri(), wait_until="networkidle")
                pag.evaluate("() => document.fonts.ready")
                card = pag.locator(".card")
                png = card.screenshot(type="png")
                datos = pag.evaluate(_JS)
                fondo_png = None
                if datos["fondo"]["aplanar"]:
                    pag.evaluate(_OCULTAR)
                    fondo_png = card.screenshot(type="png")
                return png, datos, fondo_png
            finally:
                nav.close()
    finally:
        ruta.unlink(missing_ok=True)


def extraer(html: str, *, slug: str, tokens: dict[str, str], fuente: str) -> tuple[bytes, dict, dict]:
    png, datos, fondo_png = _medir(html)
    escena, muestras = a_escena(datos, slug=slug, tokens=tokens, fuente=fuente, fondo_png=fondo_png)
    return png, escena, muestras


__all__ = ["extraer", "a_escena", "css_a_color", "tokenizar", "anclaje_por_tercio", "json"]
