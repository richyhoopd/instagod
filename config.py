"""Carga de variables de entorno y constantes globales del bot @gdlscene.

Único punto de acceso a la configuración. Importa desde aquí, no leas
os.environ directo en los módulos.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get(key: str, default: str | None = None, *, required: bool = False) -> str | None:
    val = os.getenv(key, default)
    if required and not val:
        raise RuntimeError(f"Falta la variable de entorno requerida: {key}")
    return val


# ---------- IA / Captions ----------
LLM_PROVIDER = (_get("LLM_PROVIDER", "deepseek") or "deepseek").lower()
DEEPSEEK_API_KEY = _get("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = _get("DEEPSEEK_MODEL", "deepseek-chat")
ANTHROPIC_API_KEY = _get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# Temperatura del LLM: más alta = captions más locos/impredecibles (DeepSeek va 0-2).
CAPTION_TEMPERATURE = float(_get("CAPTION_TEMPERATURE", "1.2") or "1.2")

# ---------- Google Sheets ----------
GOOGLE_SA_JSON = _get("GOOGLE_SA_JSON", "./secrets/google-sa.json")
# OAuth de usuario (cuando la org bloquea llaves de service account):
GOOGLE_OAUTH_CLIENT = _get("GOOGLE_OAUTH_CLIENT", "./secrets/oauth-client.json")
GOOGLE_AUTHORIZED_USER = _get("GOOGLE_AUTHORIZED_USER", "./secrets/authorized-user.json")
SHEET_ID = _get("SHEET_ID")

# ---------- Cloudinary ----------
CLOUD_NAME = _get("CLOUD_NAME")
CLOUDINARY_API_KEY = _get("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = _get("CLOUDINARY_API_SECRET")

# ---------- Telegram ----------
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _get("TELEGRAM_CHAT_ID")

# ---------- Instagram / Meta ----------
IG_USER_ID = _get("IG_USER_ID")
IG_ACCESS_TOKEN = _get("IG_ACCESS_TOKEN")
INSTAGRAM_APP_ID = _get("INSTAGRAM_APP_ID")
INSTAGRAM_APP_SECRET = _get("INSTAGRAM_APP_SECRET")
META_APP_ID = _get("META_APP_ID")
IG_GRAPH_BASE = _get("IG_GRAPH_BASE", "https://graph.instagram.com")
IG_API_VERSION = _get("IG_API_VERSION", "v23.0")

# ---------- X / Twitter (OAuth 1.0: tokens sin expiración) ----------
X_API_KEY = _get("X_API_KEY")
X_API_SECRET = _get("X_API_SECRET")
X_ACCESS_TOKEN = _get("X_ACCESS_TOKEN")
X_ACCESS_SECRET = _get("X_ACCESS_SECRET")
# Kill switch por red: "0" la apaga sin tocar las demás.
CROSSPOST_X = (_get("CROSSPOST_X", "1") or "1") != "0"

# ---------- Facebook (Página; token permanente derivado de user token largo) ----------
FB_PAGE_ID = _get("FB_PAGE_ID")
FB_PAGE_ACCESS_TOKEN = _get("FB_PAGE_ACCESS_TOKEN")
FB_GRAPH_BASE = _get("FB_GRAPH_BASE", "https://graph.facebook.com")
FB_API_VERSION = _get("FB_API_VERSION", "v25.0")
CROSSPOST_FB = (_get("CROSSPOST_FB", "1") or "1") != "0"

# ---------- Scraping de Instagram (cuenta secundaria, Fase 2) ----------
IG_SCRAPER_USER = _get("IG_SCRAPER_USER")
IG_SCRAPER_PASSWORD = _get("IG_SCRAPER_PASSWORD")
# IG amarra el sessionid al user-agent que lo creó ("useragent mismatch" si no
# coincide): debe ser EXACTAMENTE el navigator.userAgent del navegador de origen.
IG_SCRAPER_UA = _get("IG_SCRAPER_UA")
# Cookie sessionid importada del navegador (URL-encoded, tal cual DevTools).
# Login por script dispara checkpoints; la cookie del navegador es la vía estable.
IG_SCRAPER_SESSIONID = _get("IG_SCRAPER_SESSIONID")
IG_INGEST_MAX_POSTS = int(_get("IG_INGEST_MAX_POSTS", "12") or "12")
# Modo NOVEDADES: el feed de IG aguanta ~33 llamadas por ventana antes de
# soft-bloquear (401). Revisamos solo las N bandas más "viejas de revisar" por
# corrida (rotación por scraped_at) y cortamos tras M 401 seguidos para no
# profundizar el bloqueo. El cron diario cubre todas en pocos días.
NOVEDADES_BANDAS_POR_CORRIDA = int(_get("NOVEDADES_BANDAS_POR_CORRIDA", "25") or "25")
NOVEDADES_MAX_BLOQUEOS = int(_get("NOVEDADES_MAX_BLOQUEOS", "3") or "3")
# Pool de cuentas scraper: al quemarse una (401/429), reposa estas horas antes
# de reintentarla. Las cuentas viven en data/ig_accounts.json (ver ig_accounts).
SCRAPER_COOLDOWN_HORAS = int(_get("SCRAPER_COOLDOWN_HORAS", "12") or "12")
IG_ACCOUNTS_PATH = _get("IG_ACCOUNTS_PATH", "./data/ig_accounts.json")
IG_INGEST_DELAY_MIN = float(_get("IG_INGEST_DELAY_MIN", "4") or "4")
IG_INGEST_DELAY_MAX = float(_get("IG_INGEST_DELAY_MAX", "10") or "10")
# Sesión de instaloader cacheada: evita relogins (cada login es señal de riesgo).
IG_SESSION_FILE = _get("IG_SESSION_FILE", "./secrets/ig_scraper_session")

# ---------- Spotify (Fase 4) ----------
# OJO: la cuenta dueña de la app en developer.spotify.com debe tener Premium.
SPOTIFY_CLIENT_ID = _get("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = _get("SPOTIFY_CLIENT_SECRET")
# Releases con menos de N días se registran como evento tipo 'release'.
SPOTIFY_RELEASE_DAYS = int(_get("SPOTIFY_RELEASE_DAYS", "30") or "30")
# Pausa entre bandas al llamar Spotify (anti rate-limit; ~2 llamadas/banda).
SPOTIFY_THROTTLE_S = float(_get("SPOTIFY_THROTTLE_S", "0.6") or "0.6")
# Lock para que dos procesos (pipeline, cron, GUI) no llamen Spotify a la vez.
SPOTIFY_LOCK_PATH = _get("SPOTIFY_LOCK_PATH", "./data/.spotify.lock")

# ---------- Deezer (fuente primaria de releases; sin auth ni premium) ----------
# API pública sin token; reemplaza a Spotify como fuente de datos (Spotify queda
# solo para el link/embed). Reusa SPOTIFY_RELEASE_DAYS como ventana de novedad.
DEEZER_API_BASE = _get("DEEZER_API_BASE", "https://api.deezer.com")
DEEZER_THROTTLE_S = float(_get("DEEZER_THROTTLE_S", "0.3") or "0.3")

# ---------- Clasificación de fotos (Fase 3) ----------
# Umbral de nitidez (varianza del Laplaciano a ancho 1200px): debajo = borrosa.
# Bajo (40) para no descartar fotos buenas de escenario (humo, poca luz).
CLASSIFY_NITIDEZ_MIN = float(_get("CLASSIFY_NITIDEZ_MIN", "40") or "40")
# Base de caracteres OCR para la heurística de flyer (ver classify.score_flyer).
CLASSIFY_OCR_MIN_CHARS = int(_get("CLASSIFY_OCR_MIN_CHARS", "80") or "80")
# Regiones MSER (tipo texto) a partir de las cuales una imagen es póster/flyer
# DIBUJADO (tipografía artística que el OCR no lee). Fotos reales rondan <1400.
CLASSIFY_MSER_FLYER = int(_get("CLASSIFY_MSER_FLYER", "1700") or "1500")
# Tamaño mínimo de una cara "clara": fracción del lado menor de la imagen.
CLASSIFY_CARA_MIN_FRAC = float(_get("CLASSIFY_CARA_MIN_FRAC", "0.08") or "0.08")

# ---------- Base de datos local (SQLite) ----------
# Fuente de verdad de bandas/fotos/eventos; el Sheet queda como UI de aprobación.
DB_PATH = _get("DB_PATH", "./data/gdlscene.db")
# Carpeta donde la ingesta guarda fotos descargadas (fuera de git).
PHOTOS_DIR = _get("PHOTOS_DIR", "./data/photos")

# ---------- Calendarización ----------
TIMEZONE = _get("TIMEZONE", "America/Mexico_City")
POSTS_PER_DAY = int(_get("POSTS_PER_DAY", "4") or "4")
# POSTING_SLOTS llega como "19:00" o "10:00,19:00" → lista de strings "HH:MM".
POSTING_SLOTS = [s.strip() for s in
                 (_get("POSTING_SLOTS", "11:00,15:00,19:00,22:00") or "").split(",") if s.strip()]

# ---------- Planificación mensual de contenido (badges) ----------
# Tope de posts por banda al mes según su prioridad (1 = más atención).
MONTHLY_CAP = {1: 5, 2: 2, 3: 1, 4: 1, 5: 1}

# ---------- Taxonomía de géneros (clasificación LLM + filtros de la GUI) ----------
# Lista CERRADA para genero_principal: segmentable y sin fragmentación de tags.
# Los matices van como subtags libres en bands.generos (JSON).
GENEROS = [
    "punk", "garage", "indie", "shoegaze/dreampop", "post-punk", "hardcore",
    "metal", "hip-hop", "electrónica", "experimental/noise", "pop",
    "folk/cantautor", "cumbia/tropical", "funk/soul", "rock",
]

# Taxonomía CERRADA de patrones de formato de meme (eje formato del engagement).
# El LLM mapea cada caption a UNO de estos; lo que no mapea cae a 'otro'.
FORMATO_PATRONES = [
    "absurdo_domestico",     # integrante + objeto/situación cotidiana (los del microondas)
    "declaracion_personaje",  # "X asegura que…", declaración deadpan de un integrante
    "dato_falso",            # estadística inventada ("el 73% de los bajistas…")
    "comunicado",            # comunicado/reporte institucional satírico
    "otro",
]

# Cerebro de engagement (motor de segmentos) ---------------------------------
ENGAGEMENT_MIN_POSTS = 2          # < esto por banda → cold-start (prioridad+followers)
SHARES_PESO = 3.0                 # shares = crecimiento (reshare regala audiencia)
ANTIREPEAT_DIAS = 14             # penaliza bandas publicadas en los últimos N días
# Pesos cold-start del eje FORMATO (reglas ya probadas por Ricardo).
FORMATO_PESOS_COLDSTART = {
    "absurdo_domestico": 1.5, "declaracion_personaje": 1.2,
    "dato_falso": 1.0, "comunicado": 0.9, "otro": 1.0,
}


# Slot de alto tráfico por defecto por segmento (cold-start: hasta que IG
# online_followers tenga datos). (dow 0=lun..6=dom, hora 24h local).
TIMING_DEFAULTS = {
    "agenda_semanal":   (3, 19),   # jueves 7pm: arranque de finde
    "agenda_mensual":   (0, 19),   # lunes 7pm
    "releases_semanal": (4, 18),   # viernes 6pm: día de estrenos
    "releases_mensual": (4, 18),
    "meme":             (2, 20),   # miércoles 8pm
}
TIMING_DEFAULT_FALLBACK = (3, 19)

# Motor de frescura (Task X2): mínimos de releases para generar el carrusel.
# Semanal = solo lo NO anunciado; si hay menos que esto, no se genera (silencio).
# Mensual = recap (incluye todo) con este piso.
SEGMENT_MIN_RELEASES_SEMANAL = 3
SEGMENT_MIN_RELEASES_MENSUAL = 3


def _resolve(path: str | None) -> Path:
    """Ruta absoluta relativa a la raíz del repo."""
    p = Path(path or "")
    return p if p.is_absolute() else (BASE_DIR / p)


def resolve_sa_path() -> Path:
    """Ruta absoluta al JSON de la service account."""
    return _resolve(GOOGLE_SA_JSON)


def resolve_oauth_client_path() -> Path:
    """Ruta al JSON del cliente OAuth (Desktop app)."""
    return _resolve(GOOGLE_OAUTH_CLIENT)


def resolve_authorized_user_path() -> Path:
    """Ruta al token de usuario autorizado (se genera tras el primer login)."""
    return _resolve(GOOGLE_AUTHORIZED_USER)


def resolve_db_path() -> Path:
    """Ruta absoluta al archivo SQLite (crea la carpeta si no existe)."""
    p = _resolve(DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def resolve_ig_accounts_path() -> Path:
    """Ruta absoluta al JSON del pool de cuentas scraper."""
    return _resolve(IG_ACCOUNTS_PATH)


def resolve_photos_dir() -> Path:
    """Ruta absoluta a la carpeta de fotos descargadas (la crea si no existe)."""
    p = _resolve(PHOTOS_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_ig_session_path() -> Path:
    """Ruta al archivo de sesión de instaloader (en secrets/, fuera de git)."""
    p = _resolve(IG_SESSION_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# Claves de credenciales que existen POR CUENTA de escena (multi-cuenta Fase A).
_ACCOUNT_CRED_KEYS = ("IG_USER_ID", "IG_ACCESS_TOKEN", "IG_SCRAPER_SESSIONID",
                      "IG_SCRAPER_UA", "SHEET_ID")


def account_creds(slug: str) -> dict[str, str | None]:
    """Credenciales de una cuenta: env con sufijo __SLUG (en mayúsculas).

    gdlscene (la cuenta original) cae a las vars SIN sufijo para no tocar el
    .env ni los secrets actuales. Las demás cuentas usan SOLO su sufijo: que
    una cuenta nueva jamás herede por accidente los tokens de gdlscene.
    """
    sufijo = f"__{slug.upper()}"
    out: dict[str, str | None] = {}
    for k in _ACCOUNT_CRED_KEYS:
        val = os.getenv(k + sufijo)
        if val is None and slug == "gdlscene":
            val = os.getenv(k)
        out[k] = val
    return out
