"""Planificador mensual de contenido (badges): arma un mes de posts inteligente.

Decide QUÉ banda y QUÉ foto postear cada día del próximo mes, optimizando
tracción:
- Prioriza por impacto: `prioridad` (manual 1-5) y luego `followers_ig`.
- Respeta topes por banda al mes (config.MONTHLY_CAP): P1=5, P2=2, P3/4/5=1.
- Reparte con round-robin (una foto por banda por ronda) para no saturar a una
  banda ni dejar todo al final, y para tocar muchas bandas → más @menciones.
- Solo usa fotos `usable_meme=1` y `usada=0` (las mejores por nitidez primero).

El plan se materializa como filas en `content_queue` (status='borrador',
tipo='meme') con `scheduled_datetime` repartido en el mes. La curación y el
envío a Telegram ocurren después (pantalla /plan + generate_plan.py).

Uso:
    python -m src.planner                 # planea el próximo mes calendario
    python -m src.planner --mes 2026-07   # un mes específico
    python -m src.planner --replan        # borra el borrador del mes y rehace
"""
from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date, datetime, time, timedelta
from typing import Any

import pytz

import config
from src import db


def _cap(prioridad: int | None) -> int:
    return config.MONTHLY_CAP.get(prioridad or 3, 1)


def _slots_del_mes(year: int, month: int) -> list[datetime]:
    """Genera los datetimes del mes: posts_per_day por día, en POSTING_SLOTS."""
    tz = pytz.timezone(config.TIMEZONE)
    horas = []
    for s in (config.POSTING_SLOTS or ["19:00"]):
        hh, mm = s.split(":")
        horas.append(time(int(hh), int(mm)))
    horas = sorted(horas)[: max(1, config.POSTS_PER_DAY)]
    n_days = calendar.monthrange(year, month)[1]
    slots = []
    for d in range(1, n_days + 1):
        for h in horas:
            slots.append(tz.localize(datetime.combine(date(year, month, d), h)))
    return slots


def proximo_mes(hoy: date | None = None) -> tuple[int, int]:
    hoy = hoy or datetime.now(pytz.timezone(config.TIMEZONE)).date()
    return (hoy.year + 1, 1) if hoy.month == 12 else (hoy.year, hoy.month + 1)


def personas_recientes(cx, dias: int, ahora: "datetime | None" = None) -> set[int]:
    """Personas que ya salieron —o están por salir— en un post dentro de `dias`.

    Mira `content_queue` (no `photos.usada`) porque ahí vive la fecha del post.

    Los tres status cuentan como "esa cara ya está comprometida": `listo` es
    aprobado y en cola para publicar (lo inserta la GUI, lo consume
    generate_plan), `en_sheet` está esperando en el Sheet y `publicado` ya
    salió. Dejar `listo` fuera hacía que la anti-repetición viera menos de la
    mitad del embudo (en la DB real: listo=125 vs en_sheet=75 + publicado=37) y
    volviera a proponer una cara que se publica mañana.
    """
    # OJO timezone: default tz-aware (config.TIMEZONE), NO datetime.now() naive
    # (mismo bug que ya mordió a approval.aprobar, ver src/approval.py:44). Con
    # naive, la máquina en otro huso movería el corte respecto a lo que guarda
    # scheduled_datetime (siempre tz-aware) y la ventana quedaría mal calculada.
    ahora = ahora or datetime.now(pytz.timezone(config.TIMEZONE))
    corte = (ahora - timedelta(days=dias)).isoformat()
    filas = db.rows(cx, """
        SELECT DISTINCT p.persona_id
          FROM content_queue q JOIN photos p ON p.id = q.photo_id
         WHERE p.persona_id IS NOT NULL
           AND q.status IN (?, ?, ?)
           AND q.scheduled_datetime >= ?
    """, (db.QUEUE_LISTO, db.QUEUE_EN_SHEET, db.QUEUE_PUBLICADO, corte))
    return {f["persona_id"] for f in filas}


def scores_engagement(cx, account_id: int = 1) -> dict[int, float]:
    """{band_id: score} de engagement.score_plan con los datos de la cuenta.

    Capa IO delgada: el scoring vive en `engagement.score_plan` (PURO) y la
    lectura en `engagement._cargar_bandas`. Aquí solo se conectan.
    """
    from src import engagement

    return engagement.score_plan(engagement._cargar_bandas(cx, account_id))


def seleccionar(cx, max_posts: int, ahora: "datetime | None" = None,
                criterio: str = "impacto") -> list[dict[str, Any]]:
    """Elige (banda, foto) hasta `max_posts`, con topes. Función testeable.

    `criterio`:
      - "impacto" (default, comportamiento histórico): prioridad manual y luego
        followers_ig. No mira nada de lo que pasó en nuestra cuenta.
      - "engagement": ordena por `engagement.score_plan` — cómo le fue a la
        banda EN NUESTRA CUENTA (ER + shares) mezclado con cuánto llevamos sin
        publicarla. `prioridad` queda solo como desempate.

    Devuelve filas en orden de publicación (round-robin por el criterio elegido).
    """
    fotos = db.rows(cx, """
        SELECT p.id AS photo_id, p.band_id, p.nitidez, p.caption_original, p.persona_id,
               b.nombre AS banda_nombre, b.tipo, b.prioridad, b.followers_ig
          FROM photos p JOIN bands b ON b.id = p.band_id
         WHERE p.usable_meme = 1 AND p.usada = 0 AND p.descartada = 0 AND b.activa = 1
           -- Los flyers NO son memes: van solo a los calendarios de eventos.
           AND NOT EXISTS (SELECT 1 FROM events e
                           WHERE e.tipo = 'flyer'
                             AND e.source_post_id = p.source_post_id)
           -- Nada que ya haya estado en la cola (planeado, sugerido a Telegram,
           -- aprobado, rechazado o quitado) se vuelve a sugerir.
           AND p.id NOT IN (SELECT photo_id FROM content_queue WHERE photo_id IS NOT NULL)
         ORDER BY p.nitidez DESC
    """)
    # Anti-repetición POR CARA, no por archivo: lo que el ojo nota es que
    # vuelva a salir la misma persona, no que se repita el mismo jpg.
    recientes = personas_recientes(cx, config.ANTI_REPETICION_DIAS, ahora)
    if recientes:
        frescas = [f for f in fotos if f["persona_id"] not in recientes]
        # Si una banda se queda sin material fresco, mejor repetir cara que
        # dejarla fuera del plan: el filtro es preferencia, no prohibición.
        bandas_frescas = {f["band_id"] for f in frescas}
        fotos = frescas + [f for f in fotos if f["band_id"] not in bandas_frescas]

    # Agrupar por banda, respetando el tope (mejores fotos por nitidez).
    por_banda: dict[int, list[dict]] = {}
    meta: dict[int, dict] = {}
    for f in fotos:
        bid = f["band_id"]
        meta.setdefault(bid, f)
        cupo = _cap(f["prioridad"])
        bucket = por_banda.setdefault(bid, [])
        if len(bucket) < cupo:
            bucket.append(f)

    # Ranking de bandas según el criterio pedido.
    if criterio == "engagement":
        scores = scores_engagement(cx)
        bandas = sorted(por_banda.keys(),
                        key=lambda bid: (-scores.get(bid, 0.0),
                                         meta[bid]["prioridad"] or 3))
    else:
        # Impacto: prioridad asc (1 primero), followers desc.
        bandas = sorted(por_banda.keys(),
                        key=lambda bid: (meta[bid]["prioridad"] or 3,
                                         -(meta[bid]["followers_ig"] or 0)))
    # Round-robin: una foto por banda por ronda, en orden de impacto.
    seleccion: list[dict] = []
    while len(seleccion) < max_posts:
        avanzo = False
        for bid in bandas:
            if por_banda[bid]:
                seleccion.append(por_banda[bid].pop(0))
                avanzo = True
                if len(seleccion) >= max_posts:
                    break
        if not avanzo:
            break  # se agotaron las fotos disponibles
    return seleccion


def pick_replacement(cx, mes: str, excluir_band: int | None = None) -> dict[str, Any] | None:
    """Elige una foto para rellenar el plan: banda NUEVA al mes, respetando topes.

    NUNCA repite una banda/foto que ya estuvo este mes (en plan o DESCARTADA), así
    lo que quitas no regresa. Prefiere bandas que jamás han estado en el mes; si se
    agotan, rellena el cupo de las que están en el plan. None si no hay candidatas.
    """
    # Bandas y fotos ya tocadas este mes (en plan O descartadas) → no repetir.
    tocadas = {r["band_id"] for r in db.rows(cx, """
        SELECT DISTINCT band_id FROM content_queue
         WHERE substr(scheduled_datetime,1,7) = ? AND status IN (?, ?)
    """, (mes, db.QUEUE_BORRADOR, db.QUEUE_DESCARTADO))}
    fotos_usadas = {r["photo_id"] for r in db.rows(cx, """
        SELECT photo_id FROM content_queue
         WHERE substr(scheduled_datetime,1,7) = ? AND status IN (?, ?)
           AND photo_id IS NOT NULL
    """, (mes, db.QUEUE_BORRADOR, db.QUEUE_DESCARTADO))}
    # Cuántas trae cada banda en el plan VIGENTE (borrador) para respetar el tope.
    en_plan = {r["band_id"]: r["n"] for r in db.rows(cx, """
        SELECT band_id, COUNT(*) n FROM content_queue
         WHERE status = ? AND substr(scheduled_datetime,1,7) = ?
         GROUP BY band_id
    """, (db.QUEUE_BORRADOR, mes))}

    fotos = db.rows(cx, """
        SELECT p.id AS photo_id, p.band_id, p.nitidez,
               b.nombre AS banda_nombre, b.tipo, b.prioridad, b.followers_ig
          FROM photos p JOIN bands b ON b.id = p.band_id
         WHERE p.usable_meme = 1 AND p.usada = 0 AND p.descartada = 0 AND b.activa = 1
           AND NOT EXISTS (SELECT 1 FROM events e
                           WHERE e.tipo = 'flyer'
                             AND e.source_post_id = p.source_post_id)
           -- Nada que ya haya estado en la cola (otro mes incluido) ni en lista negra.
           AND p.id NOT IN (SELECT photo_id FROM content_queue WHERE photo_id IS NOT NULL)
         ORDER BY p.nitidez DESC
    """)

    def elegible(f, permitir_en_plan):
        if f["band_id"] == excluir_band:
            return False
        if f["photo_id"] in fotos_usadas:       # esa foto ya estuvo / se descartó
            return False
        if en_plan.get(f["band_id"], 0) >= _cap(f["prioridad"]):
            return False
        # 1ª pasada: SOLO bandas que jamás han estado este mes (genuinamente nuevas).
        if not permitir_en_plan and f["band_id"] in tocadas:
            return False
        return True

    def clave(f):
        return (f["prioridad"] or 3, -(f["followers_ig"] or 0))

    for permitir in (False, True):  # 1ª bandas nuevas al mes; 2ª rellena cupos
        cands = [f for f in fotos if elegible(f, permitir)]
        if cands:
            return sorted(cands, key=clave)[0]
    return None


def _descartar_y_reemplazar(cx, actual: dict[str, Any]) -> dict[str, Any] | None:
    """Marca la fila descartada y mete otra banda nueva en su mismo slot."""
    mes = (actual["scheduled_datetime"] or "")[:7]
    slot = actual["scheduled_datetime"]
    db.update(cx, "content_queue", actual["id"], status=db.QUEUE_DESCARTADO)
    repl = pick_replacement(cx, mes, excluir_band=actual["band_id"])
    if repl is None:
        return None
    new_id = db.insert(cx, "content_queue", tipo="meme", band_id=repl["band_id"],
                       photo_id=repl["photo_id"], status=db.QUEUE_BORRADOR,
                       scheduled_datetime=slot)
    return db.rows(cx, """
        SELECT q.id, q.tema_semilla, q.scheduled_datetime, q.photo_id,
               b.nombre AS banda_nombre, b.tipo, b.prioridad, b.followers_ig
          FROM content_queue q JOIN bands b ON b.id = q.band_id
         WHERE q.id = ?
    """, (new_id,))[0]


def reemplazar(queue_id: int) -> dict[str, Any] | None:
    """Quita una fila del plan (la marca DESCARTADA) y mete otra en su slot.

    Mantiene el plan lleno SIN que lo quitado regrese. Devuelve la fila nueva o
    None si no hubo con qué rellenar (pool agotado).
    """
    cx = db.connect()
    try:
        actual = db.get(cx, "content_queue", queue_id)
        if actual is None:
            return None
        return _descartar_y_reemplazar(cx, actual)
    finally:
        cx.close()


def eliminar(queue_id: int) -> dict[str, Any] | None:
    """Lista negra: marca la foto como descartada (NUNCA volver a sugerir), la saca
    del plan y mete otra banda. La foto no reaparece ni tras reclasificar.
    """
    cx = db.connect()
    try:
        actual = db.get(cx, "content_queue", queue_id)
        if actual is None:
            return None
        if actual.get("photo_id"):
            db.update(cx, "photos", actual["photo_id"], descartada=1, usable_meme=0)
        return _descartar_y_reemplazar(cx, actual)
    finally:
        cx.close()


def marcar_flyer(queue_id: int) -> dict[str, Any] | None:
    """Reclasifica un post del plan como FLYER: lo saca de memes y lo manda a eventos.

    La foto deja de ser usable y se registra como flyer (tipo='flyer', con su ruta)
    para que la sección de Eventos la escanee con OCR/LLM y complete la fecha. El
    slot del plan se rellena con otra banda. Devuelve la fila de reemplazo o None.
    """
    from src.classify import _registrar_flyer
    cx = db.connect()
    try:
        actual = db.get(cx, "content_queue", queue_id)
        if actual is None:
            return None
        if actual.get("photo_id"):
            foto = db.get(cx, "photos", actual["photo_id"])
            if foto:
                db.update(cx, "photos", foto["id"], usable_meme=0)
                _registrar_flyer(cx, foto)  # crea evento flyer (idempotente)
        return _descartar_y_reemplazar(cx, actual)
    finally:
        cx.close()


def reagendar_publicados(year: int, month: int, desde: date | None = None) -> dict[str, int]:
    """Reagenda los posts APROBADOS (publicado) al mes dado, desde hoy, repartidos
    en TODOS los días (un horario por día primero, luego el siguiente). Actualiza
    content_queue Y el Google Sheet (de donde publica el worker).
    """
    from src import sheets
    tz = pytz.timezone(config.TIMEZONE)
    hoy = desde or datetime.now(tz).date()
    primer = hoy.day if (hoy.year == year and hoy.month == month) else 1
    n_days = calendar.monthrange(year, month)[1]
    dias = list(range(primer, n_days + 1))
    horas = []
    for s in (config.POSTING_SLOTS or ["19:00"]):
        hh, mm = s.split(":")
        horas.append(time(int(hh), int(mm)))
    horas = sorted(horas)[: max(1, config.POSTS_PER_DAY)]
    # Reparto: hora externa, día interno → primero llena 1 post en CADA día,
    # luego el 2º horario, etc. Así "llena todos los días" antes de duplicar.
    slots = [tz.localize(datetime.combine(date(year, month, d), h))
             for h in horas for d in dias]

    cx = db.connect()
    try:
        # account_id = 1 (gdlscene): los ids de fila del Sheet son
        # auto-incrementales POR HOJA, así que un sheet_row_id de otra marca
        # puede colisionar con uno de gdlscene. reagendar_publicados solo
        # escribe al Sheet de gdlscene (v1); sin este filtro reagendaría (y
        # empujaría a sheets.update_row) filas de otras marcas por accidente.
        posts = db.rows(cx, """
            SELECT id, sheet_row_id FROM content_queue
             WHERE status = ? AND account_id = 1 ORDER BY scheduled_datetime
        """, (db.QUEUE_PUBLICADO,))
        n = 0
        for post, slot in zip(posts, slots):
            iso = slot.isoformat()
            db.update(cx, "content_queue", post["id"], scheduled_datetime=iso)
            if post["sheet_row_id"]:
                try:
                    sheets.update_row(post["sheet_row_id"], scheduled_datetime=iso)
                except Exception as exc:  # noqa: BLE001
                    print(f"   ⚠️  no se pudo actualizar Sheet fila {post['sheet_row_id']}: {exc}")
            n += 1
        print(f"✅ {n} post(s) reagendados a {year}-{month:02d} desde el día {primer} "
              f"({len(dias)} días, {len(slots)} slots disponibles).")
        return {"reagendados": n, "dias": len(dias)}
    finally:
        cx.close()


def plan_month(year: int, month: int, *, replan: bool = False,
               criterio: str = "impacto") -> dict[str, int]:
    """Materializa el plan del mes en content_queue. Devuelve conteos.

    `criterio` se pasa tal cual a `seleccionar` (ver ahí).
    """
    cx = db.connect()
    try:
        db.init_db(cx)
        slots = _slots_del_mes(year, month)
        # FIX A: no revivir slots ya pasados. plan_month(mes_en_curso) solo agenda
        # de HOY en adelante (para meses futuros no filtra nada: todos los slots
        # son > ahora). Referencia timezone-aware (config.TIMEZONE), igual que el
        # resto del motor (approval/segment_runner).
        ahora = datetime.now(pytz.timezone(config.TIMEZONE))
        slots = [s for s in slots if s > ahora]
        ini = f"{year:04d}-{month:02d}"  # 'YYYY-MM' (no dependas de slots[0])

        # Idempotencia: si ya hay borrador para ese mes, no dupliques (o rehaz).
        existentes = db.rows(cx, """
            SELECT id FROM content_queue
             WHERE status = ? AND substr(scheduled_datetime,1,7) = ?
        """, (db.QUEUE_BORRADOR, ini))
        if existentes and not replan:
            print(f"Ya hay un plan borrador para {ini} ({len(existentes)} posts). "
                  "Usa --replan para rehacerlo.")
            return {"existentes": len(existentes)}
        if existentes and replan:
            # Regenerar NO borra: marca el borrador previo como DESCARTADO. Así
            # seleccionar() (que excluye TODA foto ya vista en la cola) trae fotos
            # DISTINTAS, igual que quitar/eliminar ("lo que quitas no regresa").
            # Borrarlas las sacaba de la cola y, como el ranking es determinista
            # (nitidez DESC), el replan volvía a elegir EXACTAMENTE las mismas.
            cx.execute("""UPDATE content_queue SET status = ?
                          WHERE status = ? AND substr(scheduled_datetime,1,7) = ?""",
                       (db.QUEUE_DESCARTADO, db.QUEUE_BORRADOR, ini))
            cx.commit()

        if not slots:
            print(f"No quedan slots futuros en {ini} (el mes ya transcurrió).")
            return {"posts": 0, "bandas": 0, "slots": 0}

        seleccion = seleccionar(cx, len(slots), ahora=ahora, criterio=criterio)
        if not seleccion:
            print("No hay fotos usables sin usar. Corre el pipeline / cura fotos.")
            return {"posts": 0}

        for f, slot in zip(seleccion, slots):
            db.insert(cx, "content_queue", tipo="meme", band_id=f["band_id"],
                      photo_id=f["photo_id"],
                      tema_semilla=None,  # se cura en /plan; vacío = tema libre
                      status=db.QUEUE_BORRADOR,
                      scheduled_datetime=slot.isoformat())

        bandas_distintas = len({f["band_id"] for f in seleccion})
        print(f"✅ Plan {ini}: {len(seleccion)} posts de {bandas_distintas} banda(s) "
              f"en {len(slots)} slots. Cura en /plan y manda a Telegram.")
        return {"posts": len(seleccion), "bandas": bandas_distintas, "slots": len(slots)}
    finally:
        cx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Planificador mensual de contenido")
    parser.add_argument("--mes", help="YYYY-MM (default: próximo mes)")
    parser.add_argument("--replan", action="store_true", help="rehacer el borrador del mes")
    parser.add_argument("--criterio", choices=("impacto", "engagement"), default="impacto",
                        help="impacto: prioridad+followers (default). "
                             "engagement: desempeño en nuestra cuenta + tiempo sin publicar")
    args = parser.parse_args()
    if args.mes:
        y, m = map(int, args.mes.split("-"))
    else:
        y, m = proximo_mes()
    try:
        plan_month(y, m, replan=args.replan, criterio=args.criterio)
    except KeyboardInterrupt:
        sys.exit("\nPlaneación interrumpida.")
