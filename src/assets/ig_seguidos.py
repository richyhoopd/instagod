"""Fuente «Seguidos de IG»: el following de una cuenta semilla, curado por marca,
como banco de fotos y reels en brand_assets.

Generaliza lo de gdlscene (import_followees + ingest_ig) a cualquier marca SIN
tocar `bands`: las cuentas viven en brand_ig_cuentas y los medios en brand_assets.
Reusa el pool de cookies (SesionRotatoria) y su ritmo; no sube la concurrencia.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from curl_cffi.requests.exceptions import HTTPError

from src import db, import_followees, ingest_ig
from src.assets import biblioteca

PROVEEDOR = "ig_seguidos"
ESTADOS = ("candidata", "activa", "descartada")
_HANDLE_RE = re.compile(r"^[a-z0-9._]{1,30}\Z")
LICENCIA = "Instagram (terceros)"
_CODIGO_RE = re.compile(r"[^A-Za-z0-9_-]")
_EXTS = frozenset({"jpg", "png", "webp", "mp4"})
# Tope de cuentas por job `ig.ingerir`: el worker es uno y secuencial, un job sin
# tope (50 cuentas x posts x pausas) lo ocupa horas. El resto se reencola.
MAX_CUENTAS_POR_JOB = 10


@dataclass(frozen=True)
class _Origen:
    handle: str
    codigo: str       # shortcode del post, saneado
    post_id: str
    caption: str


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def normalizar_handle(texto: str) -> str:
    """'  @Cafe.Tacuba ' -> 'cafe.tacuba'. ValueError si no es un handle de IG válido."""
    h = (texto or "").strip().lstrip("@")
    if not h.isascii():      # antes de .lower(): el signo Kelvin (U+212A) bajaría a 'k'
        raise ValueError(f"handle de Instagram inválido: {texto!r}")
    h = h.lower()
    if not _HANDLE_RE.match(h) or ".." in h:
        raise ValueError(f"handle de Instagram inválido: {texto!r}")
    return h


def _fila(cx, account_id: int, handle: str) -> dict[str, Any] | None:
    filas = db.rows(cx, "SELECT * FROM brand_ig_cuentas WHERE account_id = ? AND ig_handle = ?",
                    (account_id, handle))
    return dict(filas[0]) if filas else None


def listar(cx, account_id: int, *, estado: str | None = None) -> list[dict[str, Any]]:
    """Cuentas de la marca: primero candidatas (lo que falta curar), luego activas."""
    sql = "SELECT * FROM brand_ig_cuentas WHERE account_id = ?"
    params: list[Any] = [account_id]
    if estado is not None:
        if estado not in ESTADOS:
            raise ValueError(f"estado inválido: {estado!r}")
        sql += " AND estado = ?"
        params.append(estado)
    sql += (" ORDER BY CASE estado WHEN 'candidata' THEN 0 WHEN 'activa' THEN 1 ELSE 2 END,"
            " ig_handle")
    return [dict(r) for r in db.rows(cx, sql, tuple(params))]


def fijar_estado(cx, account_id: int, handle: str, estado: str) -> dict[str, Any]:
    """Aprueba, descarta o agrega a mano. Si la cuenta no existía, nace con origen 'manual'."""
    if estado not in ESTADOS:
        raise ValueError(f"estado inválido: {estado!r}")
    h = normalizar_handle(handle)
    fila = _fila(cx, account_id, h)
    if fila:
        db.update(cx, "brand_ig_cuentas", fila["id"], estado=estado)
    else:
        db.insert(cx, "brand_ig_cuentas", account_id=account_id, ig_handle=h,
                  nombre=h, estado=estado, origen="manual")
    return _fila(cx, account_id, h)


def importar_seguidos(cx, account_id: int, semilla: str,
                      limite: int | None = None) -> dict[str, int]:
    """Importa el following de `semilla` como candidatas de la marca.

    Nunca toca filas existentes: la curaduría (activa/descartada) manda sobre
    cualquier reimportación. Propaga IngestRateLimited si el pool se agota.

    La semilla la escribe una persona, así que NO se usa `_listar_con_pool` (quema con
    cualquier HTTPError): solo se quema la cookie con `_debe_quemar` (401/403/429 o
    IngestRateLimited). 404 o perfil vacío = LookupError «la semilla no existe»;
    cualquier otro HTTPError (5xx) se propaga sin quemar.
    """
    s = normalizar_handle(semilla)
    rot = ingest_ig.SesionRotatoria()
    usuarios = None
    while rot.disponible():
        try:
            perfil = ingest_ig.fetch_profile(rot.session, s)
            usuarios = import_followees.listar_following(rot.session, perfil["id"], limite)
            break
        except LookupError as exc:
            raise LookupError(f"la semilla @{s} no existe en Instagram") from exc
        except (ingest_ig.IngestRateLimited, HTTPError) as exc:
            if _debe_quemar(exc):
                rot.rotar_por_quemada()
                continue
            if getattr(getattr(exc, "response", None), "status_code", None) == 404:
                raise LookupError(f"la semilla @{s} no existe en Instagram") from exc
            raise
    if usuarios is None:
        raise ingest_ig.IngestRateLimited("todas las cuentas scraper están en reposo")
    nuevas = ya = 0
    for u in usuarios:
        try:
            h = normalizar_handle(str(u.get("username") or ""))
        except ValueError:
            continue
        if _fila(cx, account_id, h):
            ya += 1
            continue
        avatar = u.get("profile_pic_url") or ""
        db.insert(cx, "brand_ig_cuentas", account_id=account_id, ig_handle=h,
                  nombre=(u.get("full_name") or "").strip() or h,
                  origen=f"seguido_de:{s}",
                  avatar_url=avatar if avatar.startswith("https://") else None,
                  privada=1 if u.get("is_private") else 0)
        nuevas += 1
    return {"nuevas": nuevas, "ya": ya, "total": len(usuarios)}


def _medios(item: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """(tipo, url) de cada medio del post: fotos, reels y videos dentro de carruseles."""
    if item.get("media_type") == ingest_ig._MEDIA_CARRUSEL:
        medios = item.get("carousel_media") or []
    else:
        medios = [item]
    for m in medios:
        tipo = m.get("media_type")
        if tipo == ingest_ig._MEDIA_FOTO:
            url = ingest_ig._best_url(m)
            if url:
                yield "imagen", url
        elif tipo == ingest_ig._MEDIA_VIDEO:
            versiones = m.get("video_versions") or []
            if versiones and versiones[0].get("url"):
                yield "video", versiones[0]["url"]


def _registrar(cx, account_id: int, slug: str, origen: _Origen, tmp: Path, *, tipo: str,
               dims: tuple[int, int] | None = None,
               tags_extra: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, bool]:
    """Pasa `tmp` por la puerta de la biblioteca. Devuelve (fila, es_nueva); (None, False)
    si el archivo no es válido, excede el tope o no es del `tipo` pedido.

    Nombre en disco: ig_<sha[:20]>.<ext>, ext de lista cerrada por magic bytes; ningún
    dato de IG (handle, caption, URL) toca la ruta. Tope, magic bytes, duplicados y
    carreras (IntegrityError) los resuelve biblioteca.guardar_bytes.
    """
    if tmp.stat().st_size > biblioteca.TOPES.get(tipo, 0):
        return None, False
    datos = tmp.read_bytes()
    detectado = biblioteca.tipo_de_bytes(datos[:16])
    if detectado is None or detectado[0] != tipo:
        return None, False
    sha = hashlib.sha256(datos).hexdigest()
    previa = db.rows(cx, "SELECT * FROM brand_assets WHERE account_id = ? AND sha = ?",
                     (account_id, sha))
    if previa:   # no resucitar descartados: la ingesta automática nunca llama _rescatar
        return dict(previa[0]), False
    tags = {"fuente": PROVEEDOR, "caption": origen.caption[:500], **(tags_extra or {})}
    meta = {"autor": f"@{origen.handle}", "licencia": LICENCIA,
            "url_origen": f"https://www.instagram.com/p/{origen.codigo}/",
            "ig_handle": origen.handle, "source_post_id": origen.post_id}
    if dims:
        meta["ancho"], meta["alto"] = dims
    try:
        fila, nueva = biblioteca.guardar_bytes(
            cx, account_id, slug, datos, proveedor=PROVEEDOR, meta=meta, tags=tags,
            prefijo="ig_", largo_sha=20, exts=_EXTS)
    except biblioteca.AssetInvalido:
        return None, False
    return fila, nueva


def primer_cuadro(video: Path, destino: Path) -> Path:
    """Primer cuadro del video como PNG (el póster en la biblioteca y en el editor).

    Solo lee archivos locales (-protocol_whitelist file) y nunca stdin. Si ffmpeg
    sale 0 sin escribir el PNG, FileNotFoundError.
    """
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-protocol_whitelist", "file",
                    "-i", str(video), "-frames:v", "1", str(destino)],
                   check=True, capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    if not destino.is_file():
        raise FileNotFoundError(str(destino))
    return destino


def _mp4_valido(ruta: Path) -> bool:
    """Tope de tamaño y magic bytes de mp4, ANTES de dárselo a ffmpeg."""
    if ruta.stat().st_size > biblioteca.TOPES["video"]:
        return False
    with ruta.open("rb") as f:
        return biblioteca.tipo_de_bytes(f.read(16)) == ("video", "mp4")


def _bajar(cx, account_id: int, slug: str, session: Any, origen: _Origen,
           tipo: str, url: str) -> int:
    """Descarga un medio a un tempdir y lo registra. Devuelve 1 si quedó un asset
    nuevo (foto o video), 0 si no; el cuadro de un video nunca cuenta.

    Un video deja dos filas: el mp4 (tags.poster -> su cuadro) y su primer cuadro
    (imagen, tags.cuadro_de_video, buscable como foto). El mp4 se valida (tope y
    magic bytes) antes de correr ffmpeg y se registra primero: si se rechaza no
    queda cuadro huérfano. Sin cuadro (ffmpeg falla, timeout, no escribe el PNG)
    se salta el video entero. El mp4 se guarda primero y, solo si el cuadro quedó en la
    biblioteca (y no está descartado), se le agrega tags.poster con el archivo real del
    cuadro; si no, el mp4 queda sin tags.poster y el cuadro descartado no se resucita.
    """
    with tempfile.TemporaryDirectory() as tmp:
        crudo = Path(tmp) / "crudo"
        if not ingest_ig._download(session, url, crudo):
            return 0
        if tipo == "imagen":
            _, nueva = _registrar(cx, account_id, slug, origen, crudo, tipo="imagen")
            return int(nueva)
        if not _mp4_valido(crudo):
            return 0
        try:
            cuadro = primer_cuadro(crudo, Path(tmp) / "cuadro.png")
            datos = cuadro.read_bytes()
            if biblioteca.tipo_de_bytes(datos[:16]) != ("imagen", "png"):
                return 0
            dims = biblioteca._dims_imagen(datos)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError,
                biblioteca.AssetInvalido):
            return 0
        fila, nueva = _registrar(cx, account_id, slug, origen, crudo, tipo="video", dims=dims)
        if fila is None:
            return 0
        fcuadro, _ = _registrar(cx, account_id, slug, origen, cuadro, tipo="imagen",
                                tags_extra={"cuadro_de_video": True})
        # El póster es el archivo REAL de la fila del cuadro (no un nombre armado a mano).
        # Sin fila o descartada no hay póster: nada colgando ni resucitado.
        if nueva and fcuadro is not None and not fcuadro["descartada"]:
            tags = json.loads(fila["tags_json"] or "{}")
            tags["poster"] = fcuadro["archivo"]
            db.update(cx, "brand_assets", fila["id"],
                      tags_json=json.dumps(tags, ensure_ascii=False))
        return int(nueva)


def _ya_ingerido(cx, account_id: int, handle: str, post_id: str) -> bool:
    return bool(db.rows(
        cx, "SELECT 1 FROM brand_assets WHERE account_id = ? AND proveedor = ?"
            " AND ig_handle = ? AND source_post_id = ? LIMIT 1",
        (account_id, PROVEEDOR, handle, post_id)))


def _ingerir_cuenta(cx, account_id: int, slug: str, cuenta: dict[str, Any],
                    session: Any, por_cuenta: int, conteo: list[int]) -> None:
    """Perfil (bio, privada) + últimos `por_cuenta` posts. Suma los assets nuevos a
    `conteo[0]` conforme se guardan, para que un fallo a medias no los pierda."""
    h = cuenta["ig_handle"]
    perfil = ingest_ig.fetch_profile(session, h)
    privada = bool(perfil.get("is_private"))
    db.update(cx, "brand_ig_cuentas", cuenta["id"],
              nombre=(perfil.get("full_name") or "").strip() or h,
              bio=perfil.get("biography") or None, ig_user_id=str(perfil["id"]),
              privada=int(privada), scraped_at=_ahora(),
              notas="perfil privado: no se puede ingerir" if privada else None)
    cx.commit()
    if privada:
        return
    ingest_ig._sleep()
    for item in ingest_ig.fetch_posts(session, str(perfil["id"]), por_cuenta):
        codigo = _CODIGO_RE.sub("", str(item.get("code") or ""))
        post_id = str(item.get("pk") or item.get("id") or codigo)
        if not codigo or _ya_ingerido(cx, account_id, h, post_id):
            continue
        origen = _Origen(handle=h, codigo=codigo, post_id=post_id,
                         caption=str((item.get("caption") or {}).get("text") or ""))
        bajados = sum(_bajar(cx, account_id, slug, session, origen, tipo, url)
                      for tipo, url in _medios(item))
        conteo[0] += bajados
        if bajados:
            ingest_ig._sleep()


def _debe_quemar(exc: Exception) -> bool:
    """True si el fallo es de la cookie (límite, sesión caída), no de la cuenta consultada.

    IngestRateLimited siempre; HTTPError solo con status 401, 403 o 429. Un 404 o 5xx
    es de ESA cuenta (handle renombrado/borrado) y no debe quemar el pool.
    """
    if isinstance(exc, ingest_ig.IngestRateLimited):
        return True
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None) in (401, 403, 429)


def _sellar(cx, cuenta: dict[str, Any]) -> None:
    """Marca el intento (scraped_at) de una cuenta que falló: si no, seguiría siendo
    «la más vieja» y la cadena de reencolados nunca llegaría a las demás."""
    db.update(cx, "brand_ig_cuentas", cuenta["id"], scraped_at=_ahora())
    cx.commit()


def ingerir(cx, account_id: int, *, por_cuenta: int = 12,
            progreso: Callable[[int, str], None] | None = None,
            desde: str | None = None) -> dict[str, Any]:
    """Baja los últimos `por_cuenta` posts de cada cuenta ACTIVA de la marca.

    Rate limit o HTTPError 401/403/429: quema la cookie, rota y reintenta la MISMA
    cuenta (como import_followees._listar_con_pool). Otro HTTPError (404, 5xx) es
    error de ESA cuenta: va a `errores`, no quema nada ni corta la corrida. Sin
    cookies sanas se corta; si se cortó sin bajar nada, lanza IngestRateLimited
    para que el job termine en error y no en un 'ok' vacío.

    Procesa como máximo MAX_CUENTAS_POR_JOB cuentas, las de scraped_at más viejo primero
    (nunca ingeridas antes). `desde` (opcional) es el sello de inicio de la cadena de reencolados:
    solo son elegibles las cuentas con scraped_at NULL o < desde (las ya intentadas en
    la cadena quedan con scraped_at >= desde, incluso si fallaron). `pendientes` cuenta
    las elegibles que quedaron fuera de este lote: la cadena termina cuando es 0. El progreso se reporta sobre el lote, no sobre el total.
    """
    resultado: dict[str, Any] = {"cuentas": 0, "assets": 0, "errores": [], "cortado": False,
                                 "pendientes": 0}
    # Sin `desde` (llamada suelta) no hay cadena que acotar: todas las activas.
    filtro, params = ("", (account_id,)) if desde is None else (
        " AND (scraped_at IS NULL OR scraped_at < ?)", (account_id, desde))
    todas = db.rows(
        cx, "SELECT * FROM brand_ig_cuentas WHERE account_id = ? AND estado = 'activa'"
            + filtro + " ORDER BY scraped_at IS NOT NULL, scraped_at, ig_handle", params)
    todas = [dict(c) for c in todas]
    cuentas = todas[:MAX_CUENTAS_POR_JOB]
    resultado["pendientes"] = len(todas) - len(cuentas)
    if not cuentas:
        return resultado
    slug = db.get(cx, "accounts", account_id)["slug"]
    rot = ingest_ig.SesionRotatoria()
    for i, cuenta in enumerate(cuentas):
        if progreso:
            progreso(int(100 * i / len(cuentas)), f"@{cuenta['ig_handle']}")
        while True:
            if not rot.disponible():
                resultado["cortado"] = True
                break
            conteo = [0]
            try:
                _ingerir_cuenta(cx, account_id, slug, cuenta, rot.session, por_cuenta, conteo)
                resultado["assets"] += conteo[0]
                resultado["cuentas"] += 1
                break
            except (ingest_ig.IngestRateLimited, HTTPError) as exc:
                resultado["assets"] += conteo[0]   # lo guardado antes del fallo cuenta
                if not _debe_quemar(exc):
                    resultado["errores"].append(
                        f"@{cuenta['ig_handle']}: {type(exc).__name__}: {exc}")
                    _sellar(cx, cuenta)
                    break
                rot.rotar_por_quemada()
            except Exception as exc:  # noqa: BLE001 — una cuenta rota no tira a las demás
                resultado["assets"] += conteo[0]
                resultado["errores"].append(f"@{cuenta['ig_handle']}: {type(exc).__name__}: {exc}")
                _sellar(cx, cuenta)
                break
        if resultado["cortado"]:
            break
    if resultado["cortado"] and resultado["assets"] == 0:
        raise ingest_ig.IngestRateLimited("todas las cuentas scraper están en reposo")
    return resultado
