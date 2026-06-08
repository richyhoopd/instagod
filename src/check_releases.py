"""Cron de releases: revisa Spotify y avisa por Telegram (sin polling).

Pensado para launchd (1×/día): itera bandas activas con `spotify_id`, registra
releases nuevos en `events` (tipo='release', con portada) reutilizando
`enrich_spotify._registrar_releases`, y si hubo nuevos manda UN mensaje simple
al chat de Telegram vía sendMessage HTTP directo — sin polling, así nunca
choca con bot.py.

Si otro proceso tiene el lock de Spotify (pipeline corriendo), se salta la
corrida en silencio: mañana hay otra. Ante 429 corta limpio; el dedupe hace
idempotente la siguiente corrida.

Uso:
    python -m src.check_releases            # corrida normal (cron)
    python -m src.check_releases --dry-run  # sin Telegram, solo imprime
"""
from __future__ import annotations

import argparse
import sys
import time

import requests
from spotipy import SpotifyException

import config
from src import db
from src.enrich_spotify import (
    RateLimitado,
    SpotifyOcupado,
    _checar_429,
    _registrar_releases,
    get_client,
    spotify_lock,
)

_MAX_LINEAS = 30  # 30 × ~80 chars ≈ 2400, bien bajo el límite de 4096 de Telegram


def formato_mensaje(nuevos: list[dict]) -> str:
    """Arma el aviso de Telegram: una línea por release, vacío si no hay."""
    if not nuevos:
        return ""
    cuerpo = nuevos[:_MAX_LINEAS]
    sobrantes = len(nuevos) - len(cuerpo)
    lineas = [f"🎵 {len(nuevos)} release(s) nuevos en la escena:"]
    lineas += [f"• {n['banda']} — {n['titulo']} ({n['fecha']})" for n in cuerpo]
    if sobrantes:
        lineas.append(f"…y {sobrantes} más (ver GUI → Calendarios).")
    else:
        lineas.append("Genera la tarjeta desde la GUI → Calendarios.")
    return "\n".join(lineas)


def avisar_telegram(texto: str) -> bool:
    """sendMessage directo (sin polling). True si Telegram aceptó."""
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        print("Sin TELEGRAM_BOT_TOKEN/CHAT_ID: no aviso.", file=sys.stderr)
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": config.TELEGRAM_CHAT_ID, "text": texto}, timeout=15)
    except requests.RequestException as exc:
        # Mac recién despierta sin red: el aviso se pierde (los releases ya
        # quedaron en la DB), pero el cron no debe tronar por esto.
        print(f"Telegram inalcanzable: {exc}", file=sys.stderr)
        return False
    if not r.ok:
        print(f"Telegram rechazó el aviso ({r.status_code}): {r.text[:200]}",
              file=sys.stderr)
    return r.ok


def _check_deezer(cx) -> list[dict]:
    """Releases nuevos vía Deezer de las bandas con deezer_status='ok'."""
    from src import deezer

    bandas = db.rows(cx, "SELECT * FROM bands WHERE deezer_status = 'ok' "
                         "AND deezer_id IS NOT NULL")
    if not bandas:
        return []
    out: list[dict] = []
    print(f"Deezer: revisando {len(bandas)} banda(s)…")
    for band in bandas:
        try:
            hallados = deezer.registrar_releases(cx, band["id"], band["deezer_id"])
        except deezer.DeezerError as exc:
            print(f"▶ {band['nombre']}: ❌ Deezer {exc}")
            continue
        for n in hallados:
            out.append({"banda": band["nombre"], "titulo": n["titulo"],
                        "fecha": n["release_date"]})
            print(f"▶ {band['nombre']}: 🆕 {n['titulo']} ({n['release_date']})")
    return out


def check(dry_run: bool = False) -> list[dict]:
    """Una pasada completa (Deezer + Spotify). Devuelve los releases nuevos."""
    cx = db.connect()
    nuevos: list[dict] = []
    try:
        db.init_db(cx)
        # Deezer es la fuente primaria (sin auth ni cap); dedup compartido en events.
        nuevos.extend(_check_deezer(cx))
        # Spotify queda como fuente secundaria para las que tengan id.
        bandas = [b for b in db.list_bands(cx)
                  if b.get("spotify_id") and db.es_musical(b)]
        if bandas:
            sp = get_client()
            print(f"Spotify: revisando {len(bandas)} banda(s)…")
            for band in bandas:
                try:
                    hallados = _registrar_releases(sp, cx, band["id"], band["spotify_id"])
                except SpotifyException as exc:
                    _checar_429(exc)
                    print(f"▶ {band['nombre']}: ❌ ({exc.http_status})")
                    continue
                for n in hallados:
                    nuevos.append({"banda": band["nombre"], **n})
                    print(f"▶ {band['nombre']}: 🆕 {n['titulo']} ({n['fecha']})")
                time.sleep(config.SPOTIFY_THROTTLE_S)
    finally:
        cx.close()
    if nuevos and not dry_run:
        if not avisar_telegram(formato_mensaje(nuevos)):
            print("⚠️ El aviso de Telegram no salió (ver stderr).")
    print(f"Listo: {len(nuevos)} release(s) nuevos.")
    return nuevos


def main() -> int:
    parser = argparse.ArgumentParser(description="Cron de releases de Spotify")
    parser.add_argument("--dry-run", action="store_true", help="no manda Telegram")
    args = parser.parse_args()
    try:
        with spotify_lock():
            check(dry_run=args.dry_run)
    except SpotifyOcupado:
        print("⏭ Spotify en uso (¿pipeline corriendo?); me salto esta corrida.")
        return 0
    except RateLimitado as exc:
        print(f"🛑 {exc} Lo registrado quedó; la próxima corrida continúa.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
