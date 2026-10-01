"""Descubrimiento de influencers a partir de cuentas semilla (following/followers).

Embudo, de lo barato a lo caro:
1. `seed`: lista following/followers de una semilla con el pool de cookies
   (`SesionRotatoria`). Las privadas y las ya vistas se descartan SIN lookup.
2. `lookup`: consulta las públicas pendientes por Business Discovery (API
   oficial, ~200 req/h). `NoEsBusiness` → no profesional → descartada. Las que
   pasan el umbral (≥10K, último post < 60 días) piden UN web_profile_info para
   la categoría (`category_name`), que sirve para tirar marcas/negocios.
3. `export`: candidatas por ER desc a CSV (y XLSX con `--xlsx`).

Género, edad y país son ESTIMADOS por heurística de texto (bio, nombre,
categoría). Nada de visión ni LLM.

La DB es propia (`data/influencers.db` o `$INFLUENCERS_DB`); nunca toca gdlscene.db.

Regla del pool: si una sesión se quema (401/429/checkpoint) se marca en reposo y
la corrida se DETIENE. No se rota en bucle: el pool lo comparte gdlscene.

Uso:
    python -m src.influencers seed udg_oficial --following --followers --max-followers 600
    python -m src.influencers lookup --budget 180
    python -m src.influencers export --out data/influencers.csv --xlsx data/influencers.xlsx
    python -m src.influencers stats
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import config

UMBRAL_FOLLOWERS = 10_000
UMBRAL_MACRO = 100_000
DIAS_ACTIVA = 60
POSTS_ER = 12
_PAUSA_GRAPH_S = 1.0

ESTADOS = ("pendiente", "descartada", "candidata", "contactada")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS influencer_candidates (
    handle          TEXT PRIMARY KEY,
    full_name       TEXT,
    followers       INTEGER,
    follows         INTEGER,
    media_count     INTEGER,
    is_private      INTEGER,
    is_verified     INTEGER,
    is_professional INTEGER,
    category        TEXT,
    bio             TEXT,
    website         TEXT,
    er_pct          REAL,
    posts_ultimo    TEXT,
    tier            TEXT,
    fuente          TEXT,
    estado          TEXT NOT NULL DEFAULT 'pendiente',
    motivo_descarte TEXT,
    genero_est      TEXT,
    genero_conf     TEXT,
    edad_est        TEXT,
    edad_conf       TEXT,
    mx_est          TEXT,
    mx_conf         TEXT,
    checked_at      TEXT,
    created_at      TEXT
);
CREATE INDEX IF NOT EXISTS ix_inf_estado ON influencer_candidates(estado);
CREATE TABLE IF NOT EXISTS seed_runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    fuente    TEXT NOT NULL,
    listados  INTEGER NOT NULL,
    nuevas    INTEGER NOT NULL,
    privadas  INTEGER NOT NULL,
    ya_vistas INTEGER NOT NULL,
    ran_at    TEXT NOT NULL
);
"""


class SesionQuemada(Exception):
    """El pool de cookies respondió 401/429/checkpoint: parar la corrida."""


# ---------------------------------------------------------------- DB

def db_path() -> Path:
    env = os.getenv("INFLUENCERS_DB")
    return Path(env) if env else config.BASE_DIR / "data" / "influencers.db"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else db_path()
    if p.name == "gdlscene.db":
        raise RuntimeError("influencers no escribe en gdlscene.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(p)
    cx.row_factory = sqlite3.Row
    cx.executescript(_SCHEMA)
    return cx


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- texto

def _norm(texto: str | None) -> str:
    """minúsculas sin acentos (conserva emojis)."""
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _tiene(texto: str, palabras) -> list[str]:
    return [p for p in palabras if re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", texto)]


# ---------------------------------------------------------------- filtro barato

def filtrar_listado(usuarios: list[dict[str, Any]], vistos: set[str]
                    ) -> tuple[list[dict], list[dict], int]:
    """Separa un listado de following/followers SIN hacer lookup.

    Devuelve (publicas_nuevas, privadas_nuevas, ya_vistas). Las privadas y las
    ya vistas nunca llegan a la API. Dedup también dentro del mismo listado.
    """
    publicas, privadas, ya = [], [], 0
    vistos = set(vistos)
    for u in usuarios:
        handle = (u.get("username") or "").lower()
        if not handle:
            continue
        if handle in vistos:
            ya += 1
            continue
        vistos.add(handle)
        (privadas if u.get("is_private") else publicas).append(u)
    return publicas, privadas, ya


def guardar_listado(cx, fuente: str, usuarios: list[dict[str, Any]]) -> dict[str, int]:
    vistos = {r[0] for r in cx.execute("SELECT handle FROM influencer_candidates")}
    publicas, privadas, ya = filtrar_listado(usuarios, vistos)
    ahora = _ahora()
    for u in privadas:
        cx.execute(
            "INSERT INTO influencer_candidates (handle, fuente, estado, motivo_descarte,"
            " is_private, created_at) VALUES (?, ?, 'descartada', 'privada', 1, ?)",
            (u["username"].lower(), fuente, ahora))
    for u in publicas:
        cx.execute(
            "INSERT INTO influencer_candidates (handle, full_name, fuente, estado,"
            " is_private, is_verified, created_at) VALUES (?, ?, ?, 'pendiente', 0, ?, ?)",
            (u["username"].lower(), (u.get("full_name") or "").strip() or None, fuente,
             1 if u.get("is_verified") else 0, ahora))
    res = {"listados": len(usuarios), "nuevas": len(publicas),
           "privadas": len(privadas), "ya_vistas": ya}
    cx.execute("INSERT INTO seed_runs (fuente, listados, nuevas, privadas, ya_vistas, ran_at)"
               " VALUES (?, ?, ?, ?, ?, ?)",
               (fuente, res["listados"], res["nuevas"], res["privadas"], ya, ahora))
    cx.commit()
    return res


# ---------------------------------------------------------------- métricas

def calcular_er(medias: list[dict[str, Any]], followers: int | None,
                n: int = POSTS_ER) -> float | None:
    """(likes+comments) promedio de los últimos `n` posts / followers × 100.

    Posts con likes ocultos (sin like_count) se ignoran para no subestimar.
    """
    if not followers:
        return None
    validos = [m for m in medias[:n] if m.get("like_count") is not None]
    if not validos:
        return None
    total = sum((m.get("like_count") or 0) + (m.get("comments_count") or 0) for m in validos)
    return round(total / len(validos) / followers * 100, 2)


def ultimo_post(medias: list[dict[str, Any]]) -> datetime | None:
    fechas = []
    for m in medias:
        ts = m.get("timestamp")
        if not ts:
            continue
        try:
            fechas.append(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z"))
        except ValueError:
            continue
    return max(fechas) if fechas else None


def tier_de(followers: int | None) -> str | None:
    if followers is None:
        return None
    if followers >= UMBRAL_MACRO:
        return "macro"
    if followers >= UMBRAL_FOLLOWERS:
        return "micro"
    return "nano"


def motivo_no_candidata(*, is_professional: bool, is_private: bool, followers: int | None,
                        ultimo: datetime | None, es_marca: bool,
                        ahora: datetime | None = None) -> str | None:
    """None si es candidata; si no, el motivo de descarte."""
    ahora = ahora or datetime.now(timezone.utc)
    if is_private:
        return "privada"
    if not is_professional:
        return "no_profesional"
    if (followers or 0) < UMBRAL_FOLLOWERS:
        return "<10k"
    if ultimo is None or (ahora - ultimo).days >= DIAS_ACTIVA:
        return "inactiva"
    if es_marca:
        return "marca"
    return None


# ---------------------------------------------------------------- heurística

_CATEG_MARCA = (
    "restaurant", "restaurante", "cafe", "coffee", "bar", "bakery", "panaderia", "food",
    "comida", "shop", "store", "tienda", "retail", "boutique", "clothing", "ropa",
    "product/service", "producto/servicio", "brand", "marca", "company", "empresa",
    "business", "negocio", "university", "universidad", "college", "school", "escuela",
    "education", "educacion", "educational", "colegio", "media", "news", "noticias",
    "newspaper", "periodico", "magazine", "revista", "radio", "tv", "television",
    "broadcasting", "publisher", "editorial", "organization", "organizacion", "nonprofit",
    "government", "gobierno", "agency", "agencia", "hotel", "travel company", "gym",
    "gimnasio", "salon", "spa", "hospital", "clinic", "clinica", "medical center",
    "pharmacy", "farmacia", "bank", "banco", "real estate", "inmobiliaria", "sports team",
    "club", "community", "comunidad", "venue", "event", "nightlife", "local business",
    "shopping", "beauty, cosmetic", "cosmetics store", "app page", "software",
    "internet company", "advertising", "marketing agency", "library", "biblioteca",
    "museum", "museo", "religious", "church", "iglesia",
)
_TEXTO_MARCA = (
    "envios", "envio", "pedidos", "tienda en linea", "cuenta oficial", "pagina oficial",
    "sucursal", "sucursales", "horario", "reservaciones", "reservas", "s.a. de c.v",
    "sa de cv", "facultad", "departamento de", "coordinacion de", "centro universitario",
    "licenciatura en", "dm para cotizar", "cotizaciones", "mayoreo", "menudeo",
    "catalogo", "abierto de", "lunes a", "delivery", "ventas", "showroom",
)
_CATEG_PERSONA = (
    "creator", "creador", "creadora", "digital creator", "creador digital", "blogger",
    "personal blog", "blog personal", "public figure", "figura publica", "artist",
    "artista", "athlete", "atleta", "musician", "musico", "actor", "actress", "actriz",
    "model", "modelo", "writer", "escritor", "escritora", "comedian", "comediante",
    "gamer", "video creator", "creador de videos", "photographer", "fotografo", "fotografa",
    "dancer", "bailarina", "chef", "entrepreneur", "emprendedor", "emprendedora",
    "fitness trainer", "entrenador personal", "coach", "makeup artist", "maquillista",
    "influencer", "youtuber", "podcaster", "journalist", "periodista",
)

_NOMBRES_F = {
    "maria", "mariana", "fernanda", "daniela", "valeria", "sofia", "camila", "ana",
    "andrea", "paola", "karla", "alejandra", "gabriela", "natalia", "ximena", "regina",
    "renata", "valentina", "isabella", "isabel", "lucia", "paula", "carolina", "diana",
    "monica", "laura", "patricia", "veronica", "adriana", "brenda", "karen", "jessica",
    "michelle", "melissa", "andrea", "montserrat", "montse", "fer", "dani", "vale", "majo",
    "ale", "gaby", "pau", "caro", "jimena", "ximena", "frida", "abril", "elena", "rocio",
    "claudia", "lorena", "fatima", "itzel", "yesenia", "nayeli", "citlali", "sara",
    "sarah", "julia", "emilia", "luisa", "marisol", "denisse", "denise", "estefania",
    "stephanie", "vanessa", "viridiana", "berenice", "erika", "erica", "ivonne", "ingrid",
    "miriam", "tania", "tanya", "beatriz", "cecilia", "silvia", "susana", "teresa",
    "alma", "angela", "angelica", "barbara", "cristina", "dulce", "esmeralda", "evelyn",
    "fabiola", "guadalupe", "lupita", "hannah", "irene", "jacqueline", "jazmin", "joana",
    "johana", "karina", "kenia", "leticia", "lizbeth", "maite", "marcela", "mayra",
    "mildred", "miranda", "nadia", "nancy", "nicole", "noemi", "olivia", "pamela",
    "priscila", "raquel", "rebeca", "rosa", "samantha", "sandra", "sharon", "tamara",
    "victoria", "wendy", "yolanda", "zoe", "ximena", "alexa", "aranza", "arantza",
    "ashley", "constanza", "danna", "dana", "emily", "ivanna", "juliana", "kimberly",
    "mia", "romina", "sofi", "andy", "anahi", "araceli", "azul", "carla", "dafne", "debora",
}
_NOMBRES_M = {
    "juan", "jose", "luis", "carlos", "jorge", "miguel", "alejandro", "eduardo",
    "fernando", "ricardo", "roberto", "daniel", "david", "diego", "javier", "francisco",
    "pablo", "andres", "sergio", "raul", "mario", "oscar", "hector", "manuel", "rafael",
    "arturo", "alberto", "antonio", "emilio", "santiago", "sebastian", "mateo", "matias",
    "rodrigo", "gerardo", "gustavo", "hugo", "ivan", "jesus", "julio", "omar", "pedro",
    "ramon", "ruben", "salvador", "victor", "adrian", "angel", "bruno", "cesar", "christian",
    "cristian", "enrique", "ernesto", "gabriel", "guillermo", "ignacio", "jaime", "joel",
    "kevin", "leonardo", "marco", "marcos", "mauricio", "max", "nicolas", "patricio",
    "rene", "samuel", "tomas", "ulises", "axel", "brandon", "bryan", "emiliano", "erick",
    "fabian", "hernan", "isaac", "jonathan", "leo", "lucas", "martin", "orlando", "saul",
}
_PALABRAS_F = (
    "mama", "mami", "mom", "mamá", "esposa", "hija", "doctora", "dra", "dra.", "psicologa",
    "nutriologa", "abogada", "ingeniera", "maestra", "licenciada", "lic.", "enfermera",
    "estudiante de", "emprendedora", "creadora", "fotografa", "bailarina", "actriz",
    "chica", "mujer", "she/her", "girl", "mujeres", "embarazada", "mamá de",
    "influencer de", "bloguera", "escritora", "periodista", "maquillista",
)
_PALABRAS_M = (
    "papa", "papá", "dad", "esposo", "hijo", "doctor", "dr", "dr.", "psicologo",
    "nutriologo", "abogado", "ingeniero", "maestro", "licenciado", "emprendedor",
    "fotografo", "bailarin", "actor", "chico", "hombre", "he/him", "boy",
)
_MX_FUERTE = (
    "gdl", "guadalajara", "jalisco", "zapopan", "tlaquepaque", "tonala", "tlajomulco",
    "mexico", "méxico", "mx", "cdmx", "monterrey", "mty", "puebla", "queretaro", "qro",
    "tijuana", "merida", "cancun", "oaxaca", "chiapas", "veracruz", "sinaloa", "sonora",
    "chihuahua", "michoacan", "guanajuato", "leon", "aguascalientes", "colima",
    "puerto vallarta", "vallarta", "edomex", "udg", "cucs", "cucea", "iteso", "uag",
    "tec de monterrey", "unam", "ipn", "tapatia", "tapatio", "mexicana", "mexicano",
)
_MX_EXTRANJERO = (
    "argentina", "buenos aires", "colombia", "bogota", "medellin", "chile", "santiago de chile",
    "peru", "lima", "venezuela", "caracas", "espana", "madrid", "barcelona", "ecuador",
    "uruguay", "usa", "los angeles", "miami", "new york", "nyc", "texas", "brasil", "brazil",
    "costa rica", "guatemala", "puerto rico", "republica dominicana", "london", "paris",
)
_PALABRAS_ES = (
    "de", "la", "el", "y", "con", "para", "mi", "que", "en", "los", "las", "vida",
    "amor", "contacto", "colaboraciones", "colabs", "aqui", "hola",
)
_JOVEN = (
    "estudiante", "student", "universidad", "uni", "udg", "cucs", "cucea", "iteso", "tec",
    "carrera", "semestre", "generacion", "gen ", "prepa", "freshman", "university",
    "veinte", "20s", "teen", "bachillerato", "egresada", "egresado",
)
_ADULTA = (
    "mama", "mamá", "mom", "mami", "esposa", "esposo", "papa", "papá", "dad", "embarazada",
    "doctora", "dra", "doctor", "dr", "maestria", "mba", "directora", "director", "ceo",
    "fundadora", "founder", "fundador", "abogada", "abogado", "lic.", "licenciada",
    "psicologa", "psicologo", "nutriologa", "nutriologo", "hijos", "hijas", "boda",
)


def _conf(puntos: int) -> str:
    return "alta" if puntos >= 3 else "media" if puntos == 2 else "baja"


def es_marca(category: str | None, bio: str | None, full_name: str | None) -> bool:
    """True si la cuenta es claramente de una marca/negocio/institución."""
    cat = _norm(category)
    if cat:
        if _tiene(cat, _CATEG_PERSONA):
            return False
        if _tiene(cat, _CATEG_MARCA):
            return True
    texto = _norm(f"{bio or ''} {full_name or ''}")
    return len(_tiene(texto, _TEXTO_MARCA)) >= 2


def estimar_genero(full_name: str | None, bio: str | None,
                   category: str | None = None, handle: str | None = None
                   ) -> tuple[str, str]:
    nombre = _norm(full_name)
    tokens = re.findall(r"[a-z]+", nombre)
    texto = _norm(f"{bio or ''} {category or ''}")
    f = m = 0
    if tokens:
        if tokens[0] in _NOMBRES_F:
            f += 2
        elif tokens[0] in _NOMBRES_M:
            m += 2
    elif handle:
        primero = re.findall(r"[a-z]+", _norm(handle))
        if primero and primero[0] in _NOMBRES_F:
            f += 1
        elif primero and primero[0] in _NOMBRES_M:
            m += 1
    f += min(2, len(_tiene(texto, _PALABRAS_F)))
    m += min(2, len(_tiene(texto, _PALABRAS_M)))
    if "♀" in (bio or "") or "👩" in (bio or ""):
        f += 1
    if "♂" in (bio or "") or "👨" in (bio or ""):
        m += 1
    if f == m:
        return "?", "baja"
    return ("F", _conf(f - m)) if f > m else ("M", _conf(m - f))


def estimar_edad(bio: str | None, category: str | None = None) -> tuple[str, str]:
    texto = _norm(f"{bio or ''} {category or ''}")
    joven = len(_tiene(texto, _JOVEN))
    adulta = len(_tiene(texto, _ADULTA))
    m = re.search(r"(?<!\d)(1[89]|[2-5]\d)\s*(anos|años|y/o|yo)\b", texto)
    if m:
        edad = int(m.group(1))
        return ("18-24" if edad < 25 else "25-34" if edad < 35 else "35+"), "alta"
    if joven > adulta:
        return "18-24", _conf(joven - adulta + 1)
    if adulta > joven:
        return "25-40", _conf(adulta - joven + 1)
    return "?", "baja"


def estimar_mx(full_name: str | None, bio: str | None, category: str | None = None,
               website: str | None = None) -> tuple[str, str]:
    crudo = f"{bio or ''} {full_name or ''}"
    texto = _norm(f"{crudo} {category or ''} {website or ''}")
    puntos = len(_tiene(texto, _MX_FUERTE)) * 2
    if "🇲🇽" in crudo:
        puntos += 3
    if (website or "").lower().rstrip("/").endswith(".mx") or ".mx/" in (website or "").lower():
        puntos += 2
    extranjero = len(_tiene(texto, _MX_EXTRANJERO)) * 2
    if re.search(r"🇦🇷|🇨🇴|🇨🇱|🇵🇪|🇻🇪|🇪🇸|🇺🇸|🇪🇨|🇺🇾|🇧🇷", crudo):
        extranjero += 3
    if puntos > extranjero:
        return "si", _conf(min(3, puntos - extranjero))
    if extranjero > puntos:
        return "no", _conf(min(3, extranjero - puntos))
    if len(_tiene(texto, _PALABRAS_ES)) >= 3:
        return "si", "baja"  # habla español, sin señal de país
    return "?", "baja"


# ---------------------------------------------------------------- seed (cookies)

def _sesion():
    from src.ingest_ig import SesionRotatoria
    rot = SesionRotatoria()
    if not rot.disponible():
        raise SesionQuemada("todas las cuentas scraper están en reposo")
    return rot


def _es_404(exc: Exception) -> bool:
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None) == 404


def _quemar_y_parar(rot, exc: Exception) -> None:
    """Marca la cuenta activa en reposo (persistido) y para. No rota en bucle.

    Un 404 no es quema: es un handle que no existe.
    """
    if _es_404(exc):
        raise LookupError(f"404: el handle no existe ({exc})") from exc
    label = rot.cuenta["label"] if rot.cuenta else "?"
    from src import ig_accounts
    ig_accounts.marcar_quemada(label)
    raise SesionQuemada(f"cuenta scraper '{label}' quemada: {exc}") from exc


def seed(cx, semilla: str, *, following: bool, followers: bool,
         max_followers: int = 600, max_following: int | None = None,
         _rot=None) -> dict[str, dict[str, int]]:
    from curl_cffi.requests.exceptions import HTTPError

    from src.import_followees import listar_followers, listar_following
    from src.ingest_ig import IngestRateLimited, _sleep, fetch_profile

    semilla = semilla.lstrip("@").lower()
    rot = _rot or _sesion()
    out: dict[str, dict[str, int]] = {}
    try:
        perfil = fetch_profile(rot.session, semilla)
    except (IngestRateLimited, HTTPError) as exc:
        _quemar_y_parar(rot, exc)
    uid = perfil["id"]
    print(f"@{semilla}: {perfil.get('edge_followed_by', {}).get('count')} followers, "
          f"sigue a {perfil.get('edge_follow', {}).get('count')} (sesión "
          f"'{rot.cuenta['label']}')")
    tareas = []
    if following:
        tareas.append(("following", listar_following, max_following))
    if followers:
        tareas.append(("followers", listar_followers, max_followers))
    for tipo, fn, tope in tareas:
        _sleep()
        try:
            usuarios = fn(rot.session, uid, tope)
        except (IngestRateLimited, HTTPError) as exc:
            _quemar_y_parar(rot, exc)
        fuente = f"{tipo}:{semilla}"
        out[fuente] = guardar_listado(cx, fuente, usuarios)
        print(f"  {fuente}: {out[fuente]}")
    return out


# ---------------------------------------------------------------- lookup (Graph)

def pendientes(cx, limite: int) -> list[sqlite3.Row]:
    """Pendientes por prioridad: verificadas, luego las de following, luego el resto."""
    return cx.execute(
        "SELECT * FROM influencer_candidates WHERE estado = 'pendiente' "
        "ORDER BY is_verified DESC, (fuente LIKE 'following:%') DESC, rowid LIMIT ?",
        (limite,)).fetchall()


def aplicar_perfil(cx, handle: str, bd: dict[str, Any], category: str | None,
                   *, ahora: datetime | None = None) -> str:
    """Guarda el resultado del lookup y decide estado. Devuelve el estado final."""
    medias = (bd.get("media") or {}).get("data") or []
    followers = bd.get("followers_count")
    ult = ultimo_post(medias)
    bio = (bd.get("biography") or "").strip() or None
    nombre = (bd.get("name") or "").strip() or None
    marca = es_marca(category, bio, nombre)
    motivo = motivo_no_candidata(is_professional=True, is_private=False, followers=followers,
                                 ultimo=ult, es_marca=marca, ahora=ahora)
    g, gc = estimar_genero(nombre, bio, category, handle)
    e, ec = estimar_edad(bio, category)
    mx, mc = estimar_mx(nombre, bio, category, bd.get("website"))
    cx.execute(
        "UPDATE influencer_candidates SET full_name=COALESCE(?, full_name), followers=?,"
        " follows=?, media_count=?, is_professional=1, category=?, bio=?, website=?,"
        " er_pct=?, posts_ultimo=?, tier=?, estado=?, motivo_descarte=?, genero_est=?,"
        " genero_conf=?, edad_est=?, edad_conf=?, mx_est=?, mx_conf=?, checked_at=?"
        " WHERE handle=?",
        (nombre, followers, bd.get("follows_count"), bd.get("media_count"), category, bio,
         bd.get("website") or None, calcular_er(medias, followers),
         ult.date().isoformat() if ult else None, tier_de(followers),
         "candidata" if motivo is None else "descartada", motivo, g, gc, e, ec, mx, mc,
         _ahora(), handle))
    cx.commit()
    return "candidata" if motivo is None else "descartada"


def _descartar(cx, handle: str, motivo: str, *, is_professional: int | None) -> None:
    cx.execute("UPDATE influencer_candidates SET estado='descartada', motivo_descarte=?,"
               " is_professional=?, checked_at=? WHERE handle=?",
               (motivo, is_professional, _ahora(), handle))
    cx.commit()


def necesita_categoria(bd: dict[str, Any]) -> bool:
    """Solo se gasta un web_profile_info en las que ya pasan los umbrales."""
    medias = (bd.get("media") or {}).get("data") or []
    marca_txt = es_marca(None, bd.get("biography"), bd.get("name"))
    return motivo_no_candidata(is_professional=True, is_private=False,
                               followers=bd.get("followers_count"),
                               ultimo=ultimo_post(medias), es_marca=marca_txt) is None


def lookup(cx, budget: int, *, con_categoria: bool = True,
           _fetch: Callable | None = None, _categoria: Callable | None = None,
           _pausa: float = _PAUSA_GRAPH_S) -> dict[str, Any]:
    from src import business_discovery as bdm

    fetch = _fetch or bdm.fetch_cuenta
    res: dict[str, Any] = {"llamadas": 0, "candidatas": 0, "no_profesional": 0,
                           "descartadas": 0, "no_encontradas": 0, "errores": [],
                           "perfiles_scraper": 0, "parada": None}
    ig_id = None if _fetch else bdm.ig_user_id()
    rot = None
    if con_categoria and _categoria is None:
        _categoria, rot = _categoria_por_scraper()
    for fila in pendientes(cx, budget):
        handle = fila["handle"]
        try:
            res["llamadas"] += 1
            bd = fetch(handle, max_posts=POSTS_ER, ig_id=ig_id)
        except bdm.NoEsBusiness:
            _descartar(cx, handle, "no_profesional", is_professional=0)
            res["no_profesional"] += 1
            continue
        except bdm.GraphRateLimited as exc:
            res["parada"] = f"GraphRateLimited: {exc}"
            break
        except bdm.BusinessDiscoveryNoDisponible as exc:
            res["parada"] = f"BusinessDiscoveryNoDisponible: {exc}"
            break
        except LookupError:
            _descartar(cx, handle, "no_encontrada", is_professional=None)
            res["no_encontradas"] += 1
            continue
        except Exception as exc:  # noqa: BLE001 — se queda pendiente
            res["errores"].append(f"@{handle}: {exc}")
            if len(res["errores"]) >= 5:
                res["parada"] = "5 errores no clasificados; corto"
                break
            continue
        finally:
            time.sleep(_pausa)
        category = None
        if con_categoria and necesita_categoria(bd):
            try:
                category = _categoria(handle)
                res["perfiles_scraper"] += 1
            except SesionQuemada as exc:
                # se guarda lo de Graph pero queda pendiente para reconsultar categoría
                res["parada"] = str(exc)
                break
        estado = aplicar_perfil(cx, handle, bd, category)
        res["candidatas" if estado == "candidata" else "descartadas"] += 1
    return res


def _categoria_por_scraper():
    """category_name vía web_profile_info, con el delay humano del pool."""
    from curl_cffi.requests.exceptions import HTTPError

    from src.ingest_ig import IngestRateLimited, _sleep, fetch_profile
    estado: dict[str, Any] = {"rot": None}

    def categoria(handle: str) -> str | None:
        if estado["rot"] is None:
            estado["rot"] = _sesion()
        rot = estado["rot"]
        _sleep()
        try:
            perfil = fetch_profile(rot.session, handle)
        except LookupError:
            return None
        except (IngestRateLimited, HTTPError) as exc:
            if _es_404(exc):
                return None
            _quemar_y_parar(rot, exc)
        return perfil.get("category_name") or perfil.get("business_category_name")

    return categoria, estado


# ---------------------------------------------------------------- reportes

_COLS_EXPORT = ("handle", "url", "full_name", "followers", "tier", "er_pct", "category",
                "genero_est", "genero_conf", "edad_est", "edad_conf", "mx_est", "mx_conf",
                "posts_ultimo", "media_count", "follows", "website", "bio", "fuente")


def candidatas(cx) -> list[dict[str, Any]]:
    filas = cx.execute("SELECT * FROM influencer_candidates WHERE estado IN "
                       "('candidata','contactada') ORDER BY er_pct IS NULL, er_pct DESC"
                       ).fetchall()
    out = []
    for f in filas:
        d = dict(f)
        d["url"] = f"https://www.instagram.com/{d['handle']}/"
        out.append({c: d.get(c) for c in _COLS_EXPORT})
    return out


def embudo(cx) -> list[dict[str, Any]]:
    """Una fila por fuente. Cada handle cuenta en la PRIMERA fuente que lo trajo."""
    listados = {r["fuente"]: (r["l"], r["y"]) for r in cx.execute(
        "SELECT fuente, SUM(listados) l, SUM(ya_vistas) y FROM seed_runs GROUP BY fuente")}
    filas = []
    for r in cx.execute("""
        SELECT fuente,
          SUM(motivo_descarte='privada') privadas,
          SUM(checked_at IS NOT NULL) consultadas,
          SUM(motivo_descarte='no_profesional') no_profesionales,
          SUM(motivo_descarte='<10k') menos_10k,
          SUM(motivo_descarte='inactiva') inactivas,
          SUM(motivo_descarte='marca') marcas,
          SUM(motivo_descarte='no_encontrada') no_encontradas,
          SUM(estado IN ('candidata','contactada')) candidatas,
          SUM(estado='pendiente') pendientes
        FROM influencer_candidates GROUP BY fuente ORDER BY fuente"""):
        d = dict(r)
        d["listados"], d["ya_vistas"] = listados.get(d["fuente"], (None, None))
        filas.append(d)
    return filas


_COLS_EMBUDO = ("fuente", "listados", "ya_vistas", "privadas", "consultadas",
                "no_profesionales", "menos_10k", "inactivas", "marcas", "no_encontradas",
                "candidatas", "pendientes")


def export_csv(cx, out: str | Path) -> int:
    filas = candidatas(cx)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_COLS_EXPORT)
        w.writeheader()
        w.writerows(filas)
    return len(filas)


def export_xlsx(cx, out: str | Path) -> int:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    filas = candidatas(cx)
    wb = Workbook()
    ws = wb.active
    ws.title = "Candidatas"
    cols = [c for c in _COLS_EXPORT if c != "url"] + ["url", "estado_contacto", "notas"]
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True)
    for f in filas:
        ws.append([f.get(c) if c not in ("estado_contacto", "notas") else None for c in cols])
        r = ws.max_row
        h = ws.cell(row=r, column=1)
        h.hyperlink = f["url"]
        h.style = "Hyperlink"
        ws.cell(row=r, column=cols.index("followers") + 1).number_format = "#,##0"
        ws.cell(row=r, column=cols.index("er_pct") + 1).number_format = "0.0"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{max(1, ws.max_row)}"
    anchos = {"handle": 24, "full_name": 26, "bio": 60, "url": 40, "website": 30,
              "category": 22, "fuente": 24, "notas": 40, "estado_contacto": 16}
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = anchos.get(c, 12)

    rs = wb.create_sheet("Resumen")
    rs.append(list(_COLS_EMBUDO))
    for c in rs[1]:
        c.font = Font(bold=True)
    for e in embudo(cx):
        rs.append([e.get(c) for c in _COLS_EMBUDO])
    rs.freeze_panes = "A2"
    rs.column_dimensions["A"].width = 30
    wb.save(out)
    return len(filas)


def stats(cx) -> dict[str, Any]:
    por_estado = {r[0]: r[1] for r in cx.execute(
        "SELECT estado, COUNT(*) FROM influencer_candidates GROUP BY estado")}
    motivos = {r[0]: r[1] for r in cx.execute(
        "SELECT motivo_descarte, COUNT(*) FROM influencer_candidates "
        "WHERE estado='descartada' GROUP BY motivo_descarte")}
    return {"por_estado": por_estado, "motivos": motivos, "embudo": embudo(cx)}


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Descubrimiento de influencers")
    p.add_argument("--db", default=None, help="ruta de la DB (default $INFLUENCERS_DB "
                   "o data/influencers.db)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("handle")
    s.add_argument("--following", action="store_true")
    s.add_argument("--followers", action="store_true")
    s.add_argument("--max-followers", type=int, default=600)
    s.add_argument("--max-following", type=int, default=None)
    lk = sub.add_parser("lookup")
    lk.add_argument("--budget", type=int, required=True)
    lk.add_argument("--sin-categoria", action="store_true",
                    help="no pedir category_name al pool de cookies")
    ex = sub.add_parser("export")
    ex.add_argument("--out", required=True)
    ex.add_argument("--xlsx", default=None, help="ruta del .xlsx adicional")
    sub.add_parser("stats")
    a = p.parse_args(argv)

    cx = connect(a.db)
    print(f"DB: {a.db or db_path()}")
    try:
        if a.cmd == "seed":
            if not (a.following or a.followers):
                p.error("pasa --following y/o --followers")
            try:
                seed(cx, a.handle, following=a.following, followers=a.followers,
                     max_followers=a.max_followers, max_following=a.max_following)
            except SesionQuemada as exc:
                print(f"🛑 {exc}")
                return 2
            except LookupError as exc:
                print(f"❌ {exc}")
                return 3
        elif a.cmd == "lookup":
            res = lookup(cx, a.budget, con_categoria=not a.sin_categoria)
            print(res)
            pend = cx.execute("SELECT COUNT(*) FROM influencer_candidates "
                              "WHERE estado='pendiente'").fetchone()[0]
            print(f"pendientes: {pend}")
            if res["parada"]:
                print(f"🛑 {res['parada']}")
                return 2
        elif a.cmd == "export":
            n = export_csv(cx, a.out)
            print(f"{n} candidatas → {a.out}")
            if a.xlsx:
                export_xlsx(cx, a.xlsx)
                print(f"xlsx → {a.xlsx}")
        elif a.cmd == "stats":
            st = stats(cx)
            print(st["por_estado"])
            print(st["motivos"])
            for e in st["embudo"]:
                print(e)
        return 0
    finally:
        cx.close()


if __name__ == "__main__":
    sys.exit(main())
