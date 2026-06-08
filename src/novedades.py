"""Chequeo diario de NOVEDADES de bandas existentes (orquestador del cron).

Encadena los pasos del fetch incremental sin re-revisar lo ya conocido:
  1. ingest_ig.novedades()      — posts nuevos de bandas ya scrapeadas (corta
                                  al primer post conocido; 1 llamada/banda).
  2. classify.clasificar()       — solo bandas con fotos nuevas: usables al
                                  pool de memes, flyers a events.
  3. detect_releases_ig.detectar() — captions nuevos por LLM → releases de IG
                                  (cubre bandas sin Spotify; dedupe vs Spotify).
  4. parse_events.parse_all()    — fecha/lugar de los flyers nuevos.

Aviso por Telegram (sendMessage directo, sin polling) SOLO si hubo novedades o
errores — el día sin nada no genera ruido. Cada paso es tolerante: si uno cae,
los demás corren y el resumen lo reporta. Exit 1 solo si la ingesta (el paso
raíz) truena por completo.

Uso:  python -m src.novedades        (lo corre el LaunchAgent diario de 09:00
                                      y el botón 🔄 Novedades de la GUI)

Spec: docs/superpowers/specs/2026-06-07-fetch-incremental-design.md
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta

from src import classify, db, detect_releases_ig, ingest_ig, parse_events
from src.check_releases import avisar_telegram

# Procesos con los que NO debemos traslaparnos: el pipeline grande comparte la
# ingesta de IG (duplicaría llamadas) y bot.py el chat de aprobación.
_PATRONES_OCUPADO = (r"python.*src\.pipeline", r"python.*bot\.py")


def _proceso_activo() -> bool:
    return any(
        subprocess.run(["pgrep", "-f", p], capture_output=True).returncode == 0
        for p in _PATRONES_OCUPADO
    )


# Señales de que un caption ANUNCIA evento/release (para el monitor de completitud).
_SENALES_EVENTO = ("junio", "julio", "agosto", " pm", "sencillo", "estreno",
                   "disponible", "en vivo", "toca", "concierto", "ep", "álbum", "album")


def _monitor_escapados(cx, dias: int = 30, hoy=None) -> int:
    """Posts RECIENTES (últimos `dias`) con caption de evento, SIN evento y SIN
    analizar. Alarma temprana: tras el backfill debería ser 0 (lo ya analizado
    como 'nada' no cuenta; lo viejo/pasado tampoco)."""
    hoy = hoy or datetime.now()
    desde = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")
    like = " OR ".join("lower(p.caption_original) LIKE ?" for _ in _SENALES_EVENTO)
    params = [f"%{s.strip()}%" for s in _SENALES_EVENTO] + [desde]
    rows = cx.execute(f"""
        SELECT COUNT(DISTINCT p.band_id || ':' || p.source_post_id)
          FROM photos p
         WHERE p.source_post_id IS NOT NULL AND p.caption_original IS NOT NULL
           AND COALESCE(p.evento_analizado, 0) = 0
           AND ({like})
           AND p.fecha >= ?
           AND NOT EXISTS (SELECT 1 FROM events e
                            WHERE e.band_id = p.band_id
                              AND e.source_post_id IN (p.source_post_id,
                                                       'ig:' || p.source_post_id,
                                                       p.source_post_id || '#show'))
    """, params).fetchone()
    return int(rows[0]) if rows else 0


def _resumen_texto(res: dict, rel: dict | None, errores: list[str]) -> str:
    lineas = ["🔄 Novedades @gdlscene"]
    lineas.append(f"Bandas revisadas: {res['bandas_revisadas']} · "
                  f"con novedades: {res['con_novedades']} · "
                  f"fotos nuevas: {res['fotos_nuevas']}")
    if res.get("pendientes"):
        lineas.append(f"⏳ {res['pendientes']} pendientes para la próxima corrida "
                      "(rotación por antigüedad).")
    if res.get("cortado_por_bloqueo"):
        lineas.append("🛑 IG soft-bloqueó el feed: corté la corrida para no "
                      "empeorarlo; se retoman mañana.")
    if rel:
        lineas.append(f"Releases IG: {rel['releases_nuevos']} nuevos "
                      f"({rel['saltados_dedupe']} dedupe, {rel['fallidos']} fallidos)")
        hoy = datetime.now().strftime("%Y-%m-%d")
        for n in rel.get("nuevos", []):
            futuro = (n.get("fecha") or "") > hoy
            ico = "🔜" if futuro else "🎵"
            verbo = "sale" if futuro else "salió"
            lineas.append(f"  {ico} {n['banda']} — {n['titulo']} ({verbo} {n.get('fecha') or '?'})")
    if res.get("fallidas"):
        lineas.append("❌ Bandas fallidas: " + ", ".join(res["fallidas"]))
    for e in errores:
        lineas.append(f"⚠️ {e}")
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    if _proceso_activo():
        print("pipeline/bot activos: me salto esta corrida (no es error).")
        return 0

    # Paso raíz: si la ingesta truena por completo, no hay nada que orquestar.
    try:
        res = ingest_ig.novedades()
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Ingesta de novedades falló: {exc}", file=sys.stderr)
        return 1

    errores: list[str] = []

    handles = sorted({p["ig_handle"] for p in res["posts_nuevos"]})
    if handles:
        try:
            classify.clasificar(handles)
        except Exception as exc:  # noqa: BLE001
            errores.append(f"clasificar falló: {exc}")

    rel = None
    if res["posts_nuevos"]:
        try:
            cx = db.connect()
            db.init_db(cx)
            try:
                rel = detect_releases_ig.detectar(cx, res["posts_nuevos"])
            finally:
                cx.close()
        except Exception as exc:  # noqa: BLE001
            errores.append(f"detección de releases IG falló: {exc}")

        try:
            parse_events.parse_all()
        except Exception as exc:  # noqa: BLE001
            errores.append(f"parseo de flyers falló: {exc}")

    # Red de seguridad: posts con fotos pero SIN evento (la imagen no se detectó
    # como flyer) → se analizan por caption. Idempotente (photos.evento_analizado),
    # ventana amplia. Luego el monitor cuenta lo que AÚN se escapó (debería ser 0).
    escapados = 0
    try:
        cx = db.connect()
        db.init_db(cx)
        try:
            extra = detect_releases_ig.backfill_eventos(cx, dias=30)
            escapados = _monitor_escapados(cx)
        finally:
            cx.close()
        if rel is None:
            rel = extra
        else:
            rel["releases_nuevos"] += extra["releases_nuevos"]
            rel["nuevos"].extend(extra["nuevos"])
    except Exception as exc:  # noqa: BLE001
        errores.append(f"backfill de eventos falló: {exc}")

    if escapados:
        errores.append(f"{escapados} post(s) con caption de evento aún SIN evento "
                       "(revisa /eventos)")
    texto = _resumen_texto(res, rel, errores)
    print(texto)
    hubo_algo = res["fotos_nuevas"] or res.get("fallidas") or errores \
        or (rel and rel["releases_nuevos"])
    if hubo_algo:
        avisar_telegram(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
