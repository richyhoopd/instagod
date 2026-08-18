"""Refresh del token de larga duración de Instagram (flujo Instagram Login).

El token de 60 días se refresca contra `graph.instagram.com/refresh_access_token`
con `grant_type=ig_refresh_token`. El mecanismo real es LOCAL: el LaunchAgent
`com.gdlscene.refresh-token` (semanal, scripts/instalar_refresh_token.sh) corre
`python -m src.ig_token --aplicar`, que escribe el token nuevo en `.env` y en el
secret IG_ACCESS_TOKEN del repo vía el `gh` de la máquina (autenticado; el
GITHUB_TOKEN de Actions no puede escribir secrets y por eso el workflow quedó
solo como fallback manual). Sin `--aplicar` solo imprime, para uso a mano.

OJO de Meta: un token con menos de 24 horas de vida NO se puede refrescar
(error 400); el modo --aplicar lo trata como "nada que hacer", no como falla.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import requests

import config

_REPO_GH = "richyhoopd/instagod"
_TOKEN_JOVEN = "less than 24 hours"  # fragmento del error de Meta


def _var_token(slug: str) -> str:
    """Nombre de la var del token de la marca: sin sufijo SOLO para gdlscene."""
    return "IG_ACCESS_TOKEN" if slug == "gdlscene" else f"IG_ACCESS_TOKEN__{slug.upper()}"


def marcas_con_token() -> list[str]:
    """gdlscene + slugs con IG_ACCESS_TOKEN__<SLUG> en el entorno (multi-marca)."""
    out = ["gdlscene"]
    for k in sorted(os.environ):
        if k.startswith("IG_ACCESS_TOKEN__"):
            slug = k.removeprefix("IG_ACCESS_TOKEN__").lower()
            if slug and slug not in out:
                out.append(slug)
    return out


def refresh_long_lived_token(token: str | None = None) -> dict:
    """Refresca un token (default: IG_ACCESS_TOKEN de gdlscene) y devuelve el
    JSON de respuesta de Meta."""
    url = f"{config.IG_GRAPH_BASE.rstrip('/')}/refresh_access_token"
    resp = requests.get(
        url,
        params={"grant_type": "ig_refresh_token",
                "access_token": token or config.IG_ACCESS_TOKEN},
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Refresh falló {resp.status_code}: {resp.text}")
    return resp.json()


def _gh_bin() -> str:
    """Ruta del gh CLI; launchd no trae el PATH del shell."""
    gh = shutil.which("gh")
    if gh:
        return gh
    for candidato in ("/opt/homebrew/bin/gh", "/usr/local/bin/gh"):
        if shutil.which(candidato):
            return candidato
    raise RuntimeError("gh CLI no encontrado: el secret del repo no se puede actualizar")


def aplicar_token(token: str, *, slug: str = "gdlscene", env_path=None,
                  _run=subprocess.run) -> None:
    """Escribe el token en .env (local) y en el secret del repo, con la var
    de la marca (IG_ACCESS_TOKEN o IG_ACCESS_TOKEN__<SLUG>)."""
    from dotenv import set_key

    var = _var_token(slug)
    env_path = env_path or (config.BASE_DIR / ".env")
    set_key(str(env_path), var, token)
    _run([_gh_bin(), "secret", "set", var, "--repo", _REPO_GH,
          "--body", token], check=True, capture_output=True, text=True, timeout=60)


def refrescar_y_aplicar(slug: str = "gdlscene") -> bool:
    """Refresca y persiste el token de UNA marca. True si aplicó; False si el
    token era muy joven o la marca no tiene token en el entorno."""
    actual = config.account_creds(slug).get("IG_ACCESS_TOKEN")
    if not actual:
        print(f"[{slug}] sin {_var_token(slug)} en el entorno: nada que refrescar.")
        return False
    try:
        data = refresh_long_lived_token(actual)
    except RuntimeError as exc:
        if _TOKEN_JOVEN in str(exc):
            print(f"[{slug}] token con <24h de vida: Meta no lo refresca todavía.")
            return False
        raise
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"[{slug}] respuesta sin access_token: {data}")
    aplicar_token(token, slug=slug)
    dias = int(data.get("expires_in", 0)) // 86400
    print(f"[{slug}] token refrescado y aplicado (.env + secret). Vence en ~{dias} días.")
    return True


def refrescar_todas() -> None:
    """Refresca todas las marcas con token; una que falle no bloquea a las
    demás, pero al final se levanta el error (para que el launchd avise)."""
    fallas = []
    for slug in marcas_con_token():
        try:
            refrescar_y_aplicar(slug)
        except Exception as exc:  # noqa: BLE001 — se reporta al final
            fallas.append(f"{slug}: {exc}")
    if fallas:
        raise RuntimeError("Refresh falló en " + "; ".join(fallas))


if __name__ == "__main__":
    if "--aplicar" in sys.argv:
        try:
            refrescar_todas()
        except Exception as exc:  # el log del launchd guarda el detalle
            from src.check_releases import avisar_telegram

            avisar_telegram(f"⚠️ Refresh del token de IG falló: {exc}"[:500])
            raise
    else:
        data = refresh_long_lived_token()
        print(json.dumps(data, indent=2))
        token = data.get("access_token")
        if token:
            # En GitHub Actions este valor se captura y se actualiza el secret IG_ACCESS_TOKEN.
            print(f"\n::add-mask::{token}")
            print("NUEVO IG_ACCESS_TOKEN obtenido (válido ~60 días). Actualiza tu .env y el secret.")
