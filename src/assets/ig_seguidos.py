"""Fuente «Seguidos de IG»: el following de una cuenta semilla, curado por marca,
como banco de fotos y reels en brand_assets.

Generaliza lo de gdlscene (import_followees + ingest_ig) a cualquier marca SIN
tocar `bands`: las cuentas viven en brand_ig_cuentas y los medios en brand_assets.
Reusa el pool de cookies (SesionRotatoria) y su ritmo; no sube la concurrencia.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import db, import_followees, ingest_ig
from src.assets import biblioteca

PROVEEDOR = "ig_seguidos"
ESTADOS = ("candidata", "activa", "descartada")
_HANDLE_RE = re.compile(r"^[a-z0-9._]{1,30}\Z")
LICENCIA = "Instagram (terceros)"
_CODIGO_RE = re.compile(r"[^A-Za-z0-9_-]")
_EXTS = frozenset({"jpg", "png", "webp", "mp4"})


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
    h = (texto or "").strip().lstrip("@").lower()
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
    """
    s = normalizar_handle(semilla)
    usuarios = import_followees._listar_con_pool(s, limite)
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
    """Primer cuadro del video como PNG (el póster en la biblioteca y en el editor)."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                    "-frames:v", "1", str(destino)],
                   check=True, capture_output=True, timeout=60)
    return destino


def _bajar(cx, account_id: int, slug: str, session: Any, origen: _Origen,
           tipo: str, url: str) -> int:
    """Descarga un medio a un tempdir y lo registra. Devuelve los assets nuevos.

    Un video deja dos filas: su primer cuadro (imagen, buscable como foto) y el
    mp4, que apunta al cuadro en tags.poster. Sin cuadro no se guarda el video.
    Solo el video cuenta como asset nuevo; el cuadro es su póster.
    """
    with tempfile.TemporaryDirectory() as tmp:
        crudo = Path(tmp) / "crudo"
        if not ingest_ig._download(session, url, crudo):
            return 0
        if tipo == "imagen":
            _, nueva = _registrar(cx, account_id, slug, origen, crudo, tipo="imagen")
            return int(nueva)
        try:
            cuadro = primer_cuadro(crudo, Path(tmp) / "cuadro.png")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return 0
        poster, _ = _registrar(cx, account_id, slug, origen, cuadro, tipo="imagen",
                               tags_extra={"cuadro_de_video": True})
        if poster is None:
            return 0
        _, nueva = _registrar(cx, account_id, slug, origen, crudo, tipo="video",
                              dims=(poster["ancho"], poster["alto"]),
                              tags_extra={"poster": poster["archivo"]})
        return int(nueva)


def _ya_ingerido(cx, account_id: int, handle: str, post_id: str) -> bool:
    return bool(db.rows(
        cx, "SELECT 1 FROM brand_assets WHERE account_id = ? AND proveedor = ?"
            " AND ig_handle = ? AND source_post_id = ? LIMIT 1",
        (account_id, PROVEEDOR, handle, post_id)))


def _ingerir_cuenta(cx, account_id: int, slug: str, cuenta: dict[str, Any],
                    session: Any, por_cuenta: int) -> int:
    """Perfil (bio, privada) + últimos `por_cuenta` posts. Devuelve assets nuevos."""
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
        return 0
    ingest_ig._sleep()
    nuevos = 0
    for item in ingest_ig.fetch_posts(session, str(perfil["id"]), por_cuenta):
        codigo = _CODIGO_RE.sub("", str(item.get("code") or ""))
        post_id = str(item.get("pk") or item.get("id") or codigo)
        if not codigo or _ya_ingerido(cx, account_id, h, post_id):
            continue
        origen = _Origen(handle=h, codigo=codigo, post_id=post_id,
                         caption=str((item.get("caption") or {}).get("text") or ""))
        bajados = sum(_bajar(cx, account_id, slug, session, origen, tipo, url)
                      for tipo, url in _medios(item))
        nuevos += bajados
        if bajados:
            ingest_ig._sleep()
    return nuevos


def ingerir(cx, account_id: int, *, por_cuenta: int = 12,
            progreso: Callable[[int, str], None] | None = None) -> dict[str, Any]:
    """Baja los últimos `por_cuenta` posts de cada cuenta ACTIVA de la marca."""
    resultado: dict[str, Any] = {"cuentas": 0, "assets": 0, "errores": [], "cortado": False}
    cuentas = listar(cx, account_id, estado="activa")
    if not cuentas:
        return resultado
    slug = db.get(cx, "accounts", account_id)["slug"]
    rot = ingest_ig.SesionRotatoria()
    for i, cuenta in enumerate(cuentas):
        if progreso:
            progreso(int(100 * i / len(cuentas)), f"@{cuenta['ig_handle']}")
        try:
            resultado["assets"] += _ingerir_cuenta(cx, account_id, slug, cuenta,
                                                   rot.session, por_cuenta)
            resultado["cuentas"] += 1
        except ingest_ig.IngestRateLimited:
            raise
        except Exception as exc:  # noqa: BLE001 — una cuenta rota no tira a las demás
            resultado["errores"].append(f"@{cuenta['ig_handle']}: {type(exc).__name__}: {exc}")
    return resultado
