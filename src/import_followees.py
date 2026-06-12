"""Importar a quién sigue una cuenta → bandas candidatas (Fase 2, masivo).

Lee la lista de "following" de @gdlscene (o la cuenta que pases) y mete cada
cuenta en `bands` como **candidata**: `activa=0` y una nota "candidata". Así
no entran a la ingesta ni al contenido hasta que TÚ las apruebes en la GUI
(marcando `activa=1` las que sí son bandas, borrando el ruido).

Es idempotente: una cuenta ya importada no se duplica ni se reactiva (respeta
tu curación). Guarda el `full_name` de IG como nombre tentativo y la bio queda
para la ingesta.

Uso:
    python -m src.import_followees                 # following de @gdlscene
    python -m src.import_followees otra_cuenta     # following de otra cuenta
    python -m src.import_followees --limit 50      # corta tras N cuentas
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from curl_cffi.requests.exceptions import HTTPError

from src import db
from src.ingest_ig import IngestRateLimited, SesionRotatoria, fetch_profile

_FOLLOWING_URL = "https://www.instagram.com/api/v1/friendships/{uid}/following/"
_PAGE = 24


def listar_following(session, user_id: str, limite: int | None = None) -> list[dict[str, Any]]:
    """Todas las cuentas que sigue `user_id`, paginando con next_max_id."""
    usuarios: list[dict[str, Any]] = []
    max_id = ""
    while True:
        params = {"count": str(_PAGE)}
        if max_id:
            params["max_id"] = max_id
        resp = session.get(_FOLLOWING_URL.format(uid=user_id), params=params, timeout=30)
        if resp.status_code in (401, 429):
            raise IngestRateLimited(f"HTTP {resp.status_code} listando following")
        resp.raise_for_status()
        data = resp.json()
        usuarios.extend(data.get("users", []))
        if limite and len(usuarios) >= limite:
            return usuarios[:limite]
        max_id = data.get("next_max_id") or ""
        if not max_id:
            return usuarios
        time.sleep(1.5)  # paginación: pausa corta entre páginas


def _listar_con_pool(cuenta: str, limite: int | None) -> list[dict[str, Any]]:
    """Lista el following usando el pool rotatorio: al quemarse una cuenta, rota."""
    rot = SesionRotatoria()
    while rot.disponible():
        try:
            perfil = fetch_profile(rot.session, cuenta)
            print(f"@{cuenta} sigue a {perfil['edge_follow']['count']} cuentas; "
                  f"listando con '{rot.cuenta['label']}'…")
            return listar_following(rot.session, perfil["id"], limite)
        except IngestRateLimited as exc:
            print(f"⚠️ {exc} — quemo '{rot.cuenta['label']}' y roto.")
            rot.rotar_por_quemada()
        except HTTPError as exc:
            # p.ej. 400 checkpoint_required: la cuenta necesita resolver un
            # challenge en el navegador; cuenta como quemada, no como crash.
            print(f"⚠️ {exc} — quemo '{rot.cuenta['label']}' y roto.")
            rot.rotar_por_quemada()
    raise IngestRateLimited("todas las cuentas scraper están en reposo")


def importar(cuenta: str = "gdlscene", limite: int | None = None) -> dict[str, int]:
    """Importa el following como candidatas; devuelve conteos {nuevas, ya, total}.

    Propaga IngestRateLimited si IG limita la sesión (el caller decide cómo avisar).
    """
    cx = db.connect()
    try:
        db.init_db(cx)
        cuentas = _listar_con_pool(cuenta.lstrip("@"), limite)
        print(f"Recibidas {len(cuentas)} cuentas. Insertando candidatas…")

        nuevas = ya = 0
        for u in cuentas:
            handle = u["username"]
            existe = db.rows(cx, "SELECT id FROM bands WHERE ig_handle = ?", (handle,))
            if existe:
                ya += 1
                continue
            nombre = (u.get("full_name") or "").strip() or handle
            db.insert(cx, "bands", nombre=nombre, ig_handle=handle,
                      activa=0, notas="candidata (revisar en GUI)")
            nuevas += 1
        print(f"\n✅ {nuevas} candidatas nuevas · {ya} ya existían.")
        print("Revísalas en la GUI → Bandas → 'Ver archivadas': activa las reales, "
              "borra el ruido. Luego corre la ingesta.")
        return {"nuevas": nuevas, "ya": ya, "total": len(cuentas)}
    finally:
        cx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Importar following → bandas candidatas")
    parser.add_argument("cuenta", nargs="?", default="gdlscene",
                        help="cuenta cuyo 'following' importar (default gdlscene)")
    parser.add_argument("--limit", type=int, default=None, help="máximo de cuentas")
    args = parser.parse_args()
    try:
        importar(args.cuenta, args.limit)
    except IngestRateLimited as exc:
        sys.exit(f"❌ {exc} — IG limitó la sesión; reintenta en unas horas.")
    except KeyboardInterrupt:
        sys.exit("\nImportación interrumpida.")
