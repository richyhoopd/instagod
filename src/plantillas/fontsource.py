"""Tipografías de Fontsource (Google Fonts y más, OFL) instaladas como fuente
propia de la marca. Se baja UN archivo TTF (peso pedido, normal, latin) del CDN
de jsDelivr con la misma descarga cerrada de assets."""
from __future__ import annotations

import json
import os
import re
import tempfile
import time

from src import assets
from src.assets import biblioteca
from src.assets.proveedores import base

_API = "https://api.fontsource.org/v1/fonts"
_HOSTS = ("cdn.jsdelivr.net",)
_TTL = 24 * 3600
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}\Z")
# La familia acaba entre comillas en un @font-face: nada que pueda cerrarlas.
_FAMILIA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}\Z")
_TOPE = 5 * 1024 * 1024
_MAGIC_TTF = (b"\x00\x01\x00\x00", b"OTTO", b"true")


_INVALIDA = "descarga falló: respuesta inválida de fontsource"


def _forma_valida(datos) -> bool:
    return isinstance(datos, list) and all(
        isinstance(f, dict) and isinstance(f.get("id"), str) and isinstance(f.get("family"), str)
        for f in datos)


def _lista() -> list[dict]:
    ruta = assets.CACHE_DIR / "fontsource" / "catalogo.json"
    if ruta.is_file() and time.time() - ruta.stat().st_mtime < _TTL:
        try:
            datos = json.loads(ruta.read_text())
            if _forma_valida(datos):
                return datos
        except ValueError:
            pass  # caché corrupta o de otra forma: se vuelve a pedir
    datos = base.get_json(_API, params={"subsets": "latin", "type": "google"})
    if not _forma_valida(datos):
        raise biblioteca.AssetInvalido(_INVALIDA)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, suffix=".part")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(datos, f)
        os.replace(tmp, ruta)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return datos


def catalogo(q: str = "", *, limite: int = 50) -> list[dict]:
    q = (q or "").strip().lower()
    out = []
    for f in _lista():
        if q and q not in f.get("family", "").lower() and q not in f.get("id", ""):
            continue
        out.append({"id": f["id"], "familia": f["family"], "categoria": f.get("category"),
                    "pesos": f.get("weights", [])})
        if len(out) >= limite:
            break
    return out


def detalle(fid: str) -> dict:
    if not _ID_RE.match(fid or ""):
        raise ValueError("id de tipografía inválido")
    return base.get_json(f"{_API}/{fid}")


def instalar(cx, account_id: int, slug: str, fid: str, peso: int = 400) -> dict:
    biblioteca.exigir_cuenta(cx, account_id, slug)
    info = detalle(fid)
    try:
        url = info["variants"][str(int(peso))]["normal"]["latin"]["url"]["ttf"]
    except (KeyError, TypeError) as e:
        raise ValueError("esa tipografía no tiene ese peso en latin normal") from e
    if not isinstance(url, str):
        raise biblioteca.AssetInvalido(_INVALIDA)
    familia = str(info.get("family") or fid)
    if not _FAMILIA_RE.match(familia):
        raise ValueError("nombre de tipografía no admitido")
    datos = biblioteca.descargar(url, hosts=_HOSTS, tope=_TOPE)
    if not datos.startswith(_MAGIC_TTF):
        raise ValueError("el archivo descargado no es una tipografía TTF/OTF")
    destino = assets.BRANDS_DIR / slug / "fonts" / f"{fid}-{int(peso)}-normal.ttf"
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".part")
    tmp.write_bytes(datos)
    os.replace(tmp, destino)
    cx.execute("INSERT INTO brand_fonts (account_id, familia, archivo) VALUES (?, ?, ?) "
               "ON CONFLICT(account_id, familia) DO UPDATE SET archivo = excluded.archivo",
               (account_id, familia, str(destino.resolve())))
    cx.commit()
    return {"familia": familia, "archivo": str(destino.resolve()), "propia": True}
