"""Única puerta al disco de assets de una marca.

Descarga cerrada: solo https, solo hosts cuyas IP resueltas son globales
(nada de 10/8, 127/8, 169.254/16, ::1…), redirects manuales re-validados en
cada salto, allowlist de hosts por proveedor, tope de bytes leído por chunks.
Lo que se guarda pasa por magic bytes; nada se escribe con el nombre que da
el origen: el archivo es <sha[:16]>.<ext>.
⚠️ Queda un TOCTOU de DNS rebinding entre _ips_de y la conexión de requests;
se acepta para este alcance (spec §6).
"""
from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import logging
import os
import re
import socket
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from PIL import Image

import config
from src import assets, db
from src.assets import EXT_FOTO, NOMBRE_FOTO_RE, SLUG_RE, Candidata
from src.assets.proveedores import PROVEEDORES, base

log = logging.getLogger(__name__)

TOPES = {"imagen": 15 * 1024 * 1024, "video": 100 * 1024 * 1024}
_MAX_REDIRECTS = 3
_CHUNK = 64 * 1024
_ARCHIVO_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,120}\Z")
_FTYP_NO_VIDEO = {b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"avif", b"avis"}


class AssetInvalido(ValueError):
    pass


def ruta_de(slug: str, archivo: str) -> Path:
    """Ruta de un asset de la marca. ValueError si slug o archivo no validan o si la
    ruta resuelta (symlinks incluidos) sale del directorio de la marca."""
    if not SLUG_RE.match(slug or "") or not _ARCHIVO_RE.match(archivo or "") or ".." in archivo:
        raise ValueError("ruta de asset inválida")
    ruta = assets.BRANDS_DIR / slug / "assets" / archivo
    if not ruta.resolve().is_relative_to((assets.BRANDS_DIR / slug).resolve()):
        raise ValueError("ruta de asset fuera de la marca")
    return ruta


def _ruta(slug: str, archivo: str) -> Path:
    try:
        return ruta_de(slug, archivo)
    except ValueError as e:
        raise AssetInvalido(str(e)) from e


def _exigir_slug(slug: str) -> None:
    if not SLUG_RE.match(slug or ""):
        raise AssetInvalido("marca inválida")


def _exigir_cuenta(cx, account_id: int, slug: str) -> None:
    """slug válido Y perteneciente a account_id, antes de tocar disco o red."""
    _exigir_slug(slug)
    filas = db.rows(cx, "SELECT 1 FROM accounts WHERE id = ? AND slug = ?", (account_id, slug))
    if not filas:
        raise AssetInvalido("la marca no corresponde a la cuenta")


def tipo_de_bytes(cabeza: bytes) -> tuple[str, str] | None:
    if cabeza.startswith(b"\xff\xd8\xff"):
        return "imagen", "jpg"
    if cabeza.startswith(b"\x89PNG\r\n\x1a\n"):
        return "imagen", "png"
    if cabeza[:4] == b"RIFF" and cabeza[8:12] == b"WEBP":
        return "imagen", "webp"
    if cabeza[:6] in (b"GIF87a", b"GIF89a"):
        return "imagen", "gif"
    if cabeza[4:8] == b"ftyp" and cabeza[8:12] not in _FTYP_NO_VIDEO:
        return "video", "mp4"
    if cabeza.startswith(b"\x1a\x45\xdf\xa3"):
        return "video", "webm"
    return None


def _ips_de(host: str) -> list[str]:
    return [ai[4][0] for ai in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]


def _validar_url(url: str, hosts: tuple[str, ...] | None) -> None:
    partes = urlsplit(url)
    host = (partes.hostname or "").lower()
    if partes.scheme != "https" or not host:
        raise AssetInvalido("solo se descargan URLs https")
    if hosts is not None and not any(host == h or host.endswith("." + h) for h in hosts):
        raise AssetInvalido(f"host no permitido para este proveedor: {host}")
    try:
        ips = _ips_de(host)
    except (socket.gaierror, UnicodeError) as e:
        raise AssetInvalido(f"el host no resuelve: {host}") from e
    try:
        if not ips or not all(ipaddress.ip_address(ip.split("%")[0]).is_global for ip in ips):
            raise AssetInvalido(f"host no público: {host}")
    except ValueError as e:
        if isinstance(e, AssetInvalido):
            raise
        raise AssetInvalido(f"IP inválida para {host}") from e


def _host_de(url: str) -> str:
    try:
        return urlsplit(url).hostname or "?"
    except ValueError:
        return "?"


def descargar(url: str, *, hosts: tuple[str, ...] | None, tope: int) -> bytes:
    """Descarga cerrada. Todo fallo sale como AssetInvalido sin URL ni query en el mensaje."""
    try:
        return _descargar(url, hosts, tope)
    except AssetInvalido:
        raise
    except requests.HTTPError as e:
        estado = getattr(getattr(e, "response", None), "status_code", None)
        raise AssetInvalido(f"descarga falló: HTTP {estado} en {_host_de(url)}") from None
    except (requests.RequestException, ValueError) as e:
        raise AssetInvalido(f"descarga falló: {type(e).__name__} en {_host_de(url)}") from None


def _descargar(url: str, hosts: tuple[str, ...] | None, tope: int) -> bytes:
    for _ in range(_MAX_REDIRECTS + 1):
        _validar_url(url, hosts)
        with requests.get(url, stream=True, allow_redirects=False, timeout=base.TIMEOUT,
                          headers={"User-Agent": base.UA}) as r:
            if r.is_redirect:
                destino = r.headers.get("Location")
                if not destino:
                    raise AssetInvalido("redirect sin destino")
                url = urljoin(url, destino)
                continue
            r.raise_for_status()
            largo = r.headers.get("Content-Length", "")
            if largo.isdigit() and int(largo) > tope:
                raise AssetInvalido("el archivo excede el tope")
            piezas, total = [], 0
            for chunk in r.iter_content(_CHUNK):
                total += len(chunk)
                if total > tope:
                    raise AssetInvalido("el archivo excede el tope")
                piezas.append(chunk)
            return b"".join(piezas)
    raise AssetInvalido("demasiados redirects")


def _dims_imagen(datos: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(datos)) as im:
            im.verify()
        with Image.open(io.BytesIO(datos)) as im:
            return im.size
    except Exception as e:  # noqa: BLE001 — cualquier fallo de Pillow = archivo corrupto
        raise AssetInvalido("la imagen está dañada") from e


def guardar_bytes(cx, account_id: int, slug: str, datos: bytes, *, proveedor: str,
                  meta: dict | None = None, tags: list[str] | None = None
                  ) -> tuple[dict, bool]:
    _exigir_cuenta(cx, account_id, slug)
    detectado = tipo_de_bytes(datos[:16])
    if detectado is None:
        raise AssetInvalido("formato no soportado (jpg, png, webp, gif, mp4, webm)")
    tipo, ext = detectado
    if len(datos) > TOPES[tipo]:
        raise AssetInvalido("el archivo excede el tope")
    sha = hashlib.sha256(datos).hexdigest()
    previas = db.rows(cx, "SELECT * FROM brand_assets WHERE account_id = ? AND sha = ?",
                      (account_id, sha))
    if previas:
        return dict(previas[0]), False
    meta = meta or {}
    ancho, alto = _dims_imagen(datos) if tipo == "imagen" else (meta.get("ancho"), meta.get("alto"))
    archivo = f"{sha[:16]}.{ext}"
    destino = _ruta(slug, archivo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    _ruta(slug, archivo)   # re-valida contención ya con el directorio creado
    creado = not destino.exists()
    # Nombre temporal único (O_EXCL, sin seguir symlinks) en el mismo directorio.
    fd, tmp_nombre = tempfile.mkstemp(dir=destino.parent, prefix=archivo + ".", suffix=".part")
    tmp = Path(tmp_nombre)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
        os.replace(tmp, destino)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    try:
        aid = db.insert(cx, "brand_assets", account_id=account_id, tipo=tipo, archivo=archivo,
                        sha=sha, proveedor=proveedor, autor=meta.get("autor"),
                        licencia=meta.get("licencia"), url_origen=meta.get("url_origen"),
                        ig_handle=meta.get("ig_handle"),
                        source_post_id=meta.get("source_post_id"),
                        ancho=ancho, alto=alto,
                        tags_json=json.dumps(tags, ensure_ascii=False) if tags else None)
    except sqlite3.IntegrityError:
        # Carrera: otra llamada guardó los mismos bytes entre el SELECT y el INSERT
        # (UNIQUE account_id, sha). El archivo es el mismo y lo referencia su fila: no se borra.
        previas = db.rows(cx, "SELECT * FROM brand_assets WHERE account_id = ? AND sha = ?",
                          (account_id, sha))
        if previas:
            return dict(previas[0]), False
        if creado:
            destino.unlink(missing_ok=True)
        raise
    except BaseException:
        if creado:   # no dejar un archivo huérfano que ninguna fila referencia
            destino.unlink(missing_ok=True)
        raise
    cx.commit()
    return dict(db.get(cx, "brand_assets", aid)), True


def _importar_local(cx, account_id: int, slug: str, cand: Candidata, tags) -> dict:
    _exigir_cuenta(cx, account_id, slug)
    carpeta, _, nombre = cand.url[len("local:"):].partition("/")
    if carpeta == "assets":
        _ruta(slug, nombre)  # valida el nombre
        filas = db.rows(cx, "SELECT * FROM brand_assets WHERE account_id = ? AND archivo = ?",
                        (account_id, nombre))
        if not filas:
            raise AssetInvalido("ese asset no existe en esta marca")
        return dict(filas[0])
    if (carpeta == "fotos" and NOMBRE_FOTO_RE.match(nombre) and ".." not in nombre
            and Path(nombre).suffix.lower() in EXT_FOTO):
        base_marca = (assets.BRANDS_DIR / slug).resolve()
        origen = assets.BRANDS_DIR / slug / "fotos" / nombre
        if origen.is_symlink() or not origen.resolve().is_relative_to(base_marca):
            raise AssetInvalido("ruta local inválida")
        if not origen.is_file():
            raise AssetInvalido("esa foto no existe")
        if origen.stat().st_size > TOPES["imagen"]:
            raise AssetInvalido("el archivo excede el tope")
        return guardar_bytes(cx, account_id, slug, origen.read_bytes(), proveedor="carpeta",
                             meta={"licencia": "propia"}, tags=tags)[0]
    raise AssetInvalido("ruta local inválida")


def importar(cx, account_id: int, slug: str, cand: Candidata, *,
             tags: list[str] | None = None) -> dict:
    _exigir_cuenta(cx, account_id, slug)
    if cand.url.startswith("local:"):
        return _importar_local(cx, account_id, slug, cand, tags)
    if cand.proveedor == "carpeta":   # carpeta es solo local: jamás sale a la red
        raise AssetInvalido("carpeta solo admite archivos locales")
    cls = PROVEEDORES.get(cand.proveedor)
    if cls is None or cand.tipo not in cls.tipos:
        raise AssetInvalido("proveedor inválido")
    datos = descargar(cand.url, hosts=cls.hosts, tope=TOPES[cand.tipo])
    detectado = tipo_de_bytes(datos[:16])
    if detectado is None or detectado[0] != cand.tipo:
        raise AssetInvalido("el archivo no es del tipo esperado")
    fila, nueva = guardar_bytes(cx, account_id, slug, datos, proveedor=cand.proveedor,
                                meta=cand.a_dict(), tags=tags)
    if nueva:
        try:
            cls(cx=cx, account_id=account_id, slug=slug, creds=config.account_creds(slug),
                config={}).registrar_descarga(cand)
        except Exception as e:  # noqa: BLE001 — el tracking nunca rompe un import
            log.warning("registrar_descarga %s falló: %s", cand.proveedor, type(e).__name__)
    return fila
