"""Recetas por marca y planeador multimarca (spec 2026-10-06 feeds/recetas).

Una receta convierte una entidad del catálogo (`brand_entities`, alimentada
por `src.feeds`) en una pieza: carrusel 4:5, carrusel 9:16 o post. El prompt
es Jinja con `{{ item }}`; la voz de la marca la agrega `generate_slideshow`
(m.voz) — la receta solo pone estructura, datos y la regla de cifras.

Planeador: por cada slot elige receta por `peso` (round-robin ponderado,
determinista) y una entidad activa del tipo de la receta fuera de
`cooldown_dias` para ESA receta, prefiriendo entidades nunca usadas y luego
las más nuevas. El cooldown sale de `content_queue.formato_patron =
'receta:<slug>'` + `entity_id` (piezas no descartadas) y de los jobs
`receta.generar` aún en cola.
"""
from __future__ import annotations

import calendar
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable

import config
from src import db, entidades

FORMATOS = ("post", "carrusel 4:5", "carrusel 9:16")
_ASPECTO = {"post": "4:5", "carrusel 4:5": "4:5", "carrusel 9:16": "9:16"}

_REGLA_CIFRAS = (
    "REGLA DE CIFRAS (dura): ningún número que no esté en FACTS — ni años, ni "
    "distancias, ni conteos, ni porcentajes. Copia las cifras de FACTS tal cual, "
    "con su moneda. No numeres los slides."
)

_BLOQUE_DATOS = """\
DATOS VERIFICADOS (FACTS) — únicas cifras citables:
{% for k, v in item.facts.items() %}- {{ k }}: {{ v }}
{% endfor %}{% if item.unverified %}
SIN CONFIRMAR — no lo afirmes; si lo mencionas, di que está por confirmar: {{ item.unverified | join(', ') }}
{% endif %}{% if item.summary %}
Resumen: {{ item.summary }}{% endif %}{% if item.body %}
Descripción: {{ item.body }}{% endif %}
Liga de la ficha: {{ item.url }}
"""

PROMPT_FICHA = (
    "RECETA ficha-carrusel. Carrusel-ficha de «{{ item.title }}» ({{ item.type }}).\n"
    "Slide 1 (hook): qué es y dónde, en una frase; sin adjetivos de folleto.\n"
    "Slides intermedios: UN dato por slide, en este orden si existe en FACTS: "
    "ubicación, superficie, precio, régimen legal, servicios, cercanía al mar.\n"
    "Último slide (cta): una sola acción — ver la ficha completa en el sitio.\n"
    "Caption: 2-3 frases con los datos clave y la liga de la ficha.\n\n"
    + _BLOQUE_DATOS + "\n" + _REGLA_CIFRAS
)

PROMPT_TIP = (
    "RECETA tip-con-ejemplo. Un tip práctico para comprar bien en la costa de "
    "Jalisco (régimen legal, escrituración, fideicomiso, servicios, uso de "
    "suelo), ilustrado con «{{ item.title }}» ({{ item.type }}) como ejemplo.\n"
    "Slide 1 (hook): el tip como afirmación concreta, no como pregunta.\n"
    "Slides intermedios: explica el tip en pasos cortos; UN slide final de "
    "'Ejemplo:' con este inmueble y sus datos de FACTS.\n"
    "Si el dato que el tip necesita está SIN CONFIRMAR, no uses este inmueble "
    "como ejemplo de ese dato: elige otro aspecto del tip.\n"
    "Último slide (cta): una sola acción — ver la ficha en el sitio.\n\n"
    + _BLOQUE_DATOS + "\n" + _REGLA_CIFRAS
)

SEMILLA_MELAQUECAPITAL: list[dict[str, Any]] = [
    {"slug": "ficha-carrusel", "item_types": ["property", "lot"],
     "formato": "carrusel 4:5", "n_slides": 6, "estilo": "melaque_postal",
     "formato_guion": "libre", "prompt": PROMPT_FICHA, "peso": 3,
     "cooldown_dias": 30},
    {"slug": "tip-con-ejemplo", "item_types": ["property", "lot"],
     "formato": "carrusel 4:5", "n_slides": 6, "estilo": "melaque_solido",
     "formato_guion": "libre", "prompt": PROMPT_TIP, "peso": 2,
     "cooldown_dias": 45},
    # Variante vertical del tip (TikTok, temporal: sale como ZIP de PNG).
    {"slug": "tip-con-ejemplo-9x16", "item_types": ["property", "lot"],
     "formato": "carrusel 9:16", "n_slides": 6, "estilo": "melaque_solido",
     "formato_guion": "libre", "prompt": PROMPT_TIP, "peso": 1,
     "cooldown_dias": 45},
]


# ------------------------------------------------------------------- catálogo

def sembrar(cx, account_id: int, semilla: list[dict[str, Any]]) -> int:
    """Inserta las recetas que falten por slug (idempotente; no pisa ediciones)."""
    existentes = {r["slug"] for r in db.rows(
        cx, "SELECT slug FROM brand_recipes WHERE account_id = ?", (account_id,))}
    n = 0
    for r in semilla:
        if r["slug"] in existentes:
            continue
        db.insert(cx, "brand_recipes", account_id=account_id,
                  **{**r, "item_types": json.dumps(r["item_types"])})
        n += 1
    return n


def _fila(r: dict) -> dict:
    out = dict(r)
    try:
        out["item_types"] = json.loads(r.get("item_types") or "[]")
    except (TypeError, ValueError):
        out["item_types"] = []
    return out


def listar(cx, account_id: int, *, solo_activas: bool = True) -> list[dict]:
    sql = "SELECT * FROM brand_recipes WHERE account_id = ?"
    if solo_activas:
        sql += " AND activa = 1"
    return [_fila(r) for r in db.rows(cx, sql + " ORDER BY id", (account_id,))]


def por_slug(cx, account_id: int, slug: str) -> dict | None:
    filas = db.rows(cx, "SELECT * FROM brand_recipes WHERE account_id = ? AND slug = ?",
                    (account_id, slug))
    return _fila(filas[0]) if filas else None


# ------------------------------------------------------------------- render

def _texto(v: Any) -> str:
    if isinstance(v, dict):
        return str(v.get("es") or next((x for x in v.values() if x), "") or "")
    return str(v or "")


def item_de(fila: dict) -> dict:
    """La entidad como `item` para el Jinja de la receta."""
    a = entidades.atributos_de(fila)
    cdn = a.get("media_cdn") or {}
    media = [cdn.get(m.get("url")) or m.get("url")
             for m in (a.get("media") or [])
             if isinstance(m, dict) and m.get("kind", "image") == "image"]
    titulo = a.get("title")
    return {
        "id": fila["slug"], "type": fila["tipo"],
        "title": _texto(titulo) or fila["nombre"],
        "title_en": titulo.get("en") if isinstance(titulo, dict) else None,
        "summary": _texto(a.get("summary")), "body": _texto(a.get("body")),
        "url": a.get("url") or "", "status": a.get("status"),
        "facts": a.get("facts") if isinstance(a.get("facts"), dict) else {},
        "unverified": a.get("unverified") or [], "tags": a.get("tags") or [],
        "media": [u for u in media if u],
    }


def render_prompt(receta: dict, item: dict) -> str:
    from jinja2.sandbox import SandboxedEnvironment
    env = SandboxedEnvironment(autoescape=False, trim_blocks=False)
    return env.from_string(receta["prompt"]).render(item=item).strip()


def generar_desde_entidad(cx, account_id: int, receta_slug: str, entidad_id: int, *,
                          progreso: Callable[[int, str], None] | None = None,
                          creado_por: int | None = None,
                          scheduled_datetime: str | None = None,
                          generar: Callable[..., int | None] | None = None) -> int | None:
    """Genera la pieza de la receta para la entidad y la manda a aprobación.

    Lanza ValueError si la receta/entidad no aplica; `CifrasFueraDeFacts` si el
    guion insiste en cifras fuera de `facts` (la pieza se descarta).
    """
    from src import generate_slideshow
    receta = por_slug(cx, account_id, receta_slug)
    if receta is None or not receta["activa"]:
        raise ValueError(f"receta {receta_slug!r} no existe o está inactiva")
    fila = entidades.obtener(cx, entidad_id)
    if fila is None or fila["account_id"] != account_id:
        raise ValueError("la entidad no existe o no es de esta marca")
    if not fila["activa"]:
        raise ValueError("la entidad no está activa (status != active)")
    if receta["item_types"] and fila["tipo"] not in receta["item_types"]:
        raise ValueError(f"la receta {receta_slug} no aplica a tipo {fila['tipo']!r}")
    marca = db.rows(cx, "SELECT slug FROM accounts WHERE id = ?", (account_id,))[0]["slug"]
    item = item_de(fila)
    generar = generar or generate_slideshow.generar
    n = 1 if receta["formato"] == "post" else int(receta["n_slides"])
    return generar(
        cx, item["title"], marca=marca, formato=receta.get("formato_guion"),
        estilo=receta.get("estilo"), n_slides=n,
        aspect=_ASPECTO[receta["formato"]], contexto=render_prompt(receta, item),
        progreso=progreso, creado_por=creado_por,
        hechos=item["facts"], no_verificados=item["unverified"],
        entity_id=fila["id"], receta=receta["slug"],
        imagenes_preferidas=item["media"] or None,
        extra_brief={"slot_planeado": scheduled_datetime} if scheduled_datetime else None)


# ------------------------------------------------------------------ planeador

def _utc_naive(v: datetime | str) -> datetime:
    if isinstance(v, str):
        v = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if v.tzinfo is not None:
        v = v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


def _historial(cx, account_id: int, ahora: datetime) -> list[tuple[str, int, datetime]]:
    """(receta, entity_id, cuando) de piezas hechas o por hacer."""
    out = []
    for r in db.rows(cx, """
            SELECT formato_patron, entity_id, created_at FROM content_queue
             WHERE account_id = ? AND entity_id IS NOT NULL
               AND formato_patron LIKE 'receta:%' AND status != 'descartado'
               AND COALESCE(aprobacion, '') != 'rechazado'""", (account_id,)):
        out.append((r["formato_patron"][len("receta:"):], r["entity_id"],
                    _utc_naive(r["created_at"])))
    for j in db.rows(cx, "SELECT payload_json FROM jobs WHERE tipo = 'receta.generar' "
                         "AND account_id = ? AND estado IN ('cola', 'corriendo')",
                     (account_id,)):
        try:
            p = json.loads(j["payload_json"] or "{}")
            cuando = _utc_naive(p["scheduled_datetime"]) if p.get("scheduled_datetime") else ahora
            out.append((p["receta"], int(p["entidad_id"]), cuando))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def planear(cx, account_id: int, slots: list[datetime | str], *,
            ahora: datetime | None = None) -> list[dict]:
    """Asigna (receta, entidad) a cada slot. PURO salvo lecturas de DB.

    Slot sin receta elegible (sin entidades fuera de cooldown) → `receta=None`
    con `motivo`, para que el caller lo muestre en vez de rellenar a la fuerza.
    """
    ahora = _utc_naive(ahora or datetime.now(timezone.utc))
    recetas = [r for r in listar(cx, account_id) if int(r["peso"] or 0) > 0]
    ents = entidades.listar(cx, account_id, solo_activas=True)
    usos = _historial(cx, account_id, ahora)
    ultimo: dict[tuple[str, int], datetime] = {}
    total_usos: dict[int, int] = {}
    for rec, eid, cuando in usos:
        if (rec, eid) not in ultimo or cuando > ultimo[(rec, eid)]:
            ultimo[(rec, eid)] = cuando
        total_usos[eid] = total_usos.get(eid, 0) + 1

    corriente = {r["slug"]: 0 for r in recetas}
    plan: list[dict] = []
    for slot in slots:
        t = _utc_naive(slot)

        def _libres(r: dict) -> list[dict]:
            cd = timedelta(days=int(r["cooldown_dias"] or 0))
            return [e for e in ents
                    if (not r["item_types"] or e["tipo"] in r["item_types"])
                    and ((r["slug"], e["id"]) not in ultimo
                         or t - ultimo[(r["slug"], e["id"])] >= cd)]

        elegibles = [(r, _libres(r)) for r in recetas]
        elegibles = [(r, libres) for r, libres in elegibles if libres]
        salida = {"slot": slot.isoformat() if isinstance(slot, datetime) else slot}
        if not elegibles:
            plan.append({**salida, "receta": None, "entidad_id": None,
                         "motivo": "sin entidades activas fuera de cooldown"})
            continue
        # Round-robin ponderado suave (determinista): suma peso, gana el mayor,
        # se le resta el total de los elegibles.
        total = sum(int(r["peso"]) for r, _ in elegibles)
        for r, _ in elegibles:
            corriente[r["slug"]] += int(r["peso"])
        receta, libres = max(elegibles, key=lambda x: (corriente[x[0]["slug"]], -x[0]["id"]))
        corriente[receta["slug"]] -= total
        # Nuevas primero (nunca usadas en ninguna receta), luego menos usadas,
        # luego la más nueva (id mayor).
        ent = min(libres, key=lambda e: (total_usos.get(e["id"], 0), -e["id"]))
        ultimo[(receta["slug"], ent["id"])] = t
        total_usos[ent["id"]] = total_usos.get(ent["id"], 0) + 1
        plan.append({**salida, "receta": receta["slug"], "formato": receta["formato"],
                     "entidad_id": ent["id"], "entidad": ent["nombre"],
                     "entidad_slug": ent["slug"]})
    return plan


def slots_mes(posting_slots: list[str] | None, year: int, month: int,
              piezas: int) -> list[datetime]:
    """`piezas` slots repartidos parejo en el mes, en los horarios de la marca."""
    import pytz
    tz = pytz.timezone(config.TIMEZONE)
    horas = sorted(time(int(h), int(m)) for h, m in
                   (s.split(":") for s in (posting_slots or config.POSTING_SLOTS or ["19:00"])))
    horas = horas[: max(1, config.POSTS_PER_DAY)]
    todos = [tz.localize(datetime.combine(date(year, month, d), h))
             for d in range(1, calendar.monthrange(year, month)[1] + 1) for h in horas]
    piezas = max(1, min(piezas, len(todos)))
    paso = len(todos) / piezas
    return [todos[int(i * paso)] for i in range(piezas)]


def encolar_plan(cx, account_id: int, plan: list[dict], *,
                 creado_por: int | None = None) -> list[int]:
    """Un job `receta.generar` por slot asignado. Devuelve los job ids."""
    from src import jobs
    ids = []
    for p in plan:
        if not p.get("receta"):
            continue
        ids.append(jobs.crear(cx, "receta.generar", account_id,
                              {"receta": p["receta"], "entidad_id": p["entidad_id"],
                               "scheduled_datetime": p["slot"]},
                              creado_por=creado_por))
    return ids
