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

# ---------- Calendarización ----------
TIMEZONE = _get("TIMEZONE", "America/Mexico_City")
POSTS_PER_DAY = int(_get("POSTS_PER_DAY", "1") or "1")
# POSTING_SLOTS llega como "19:00" o "10:00,19:00" → lista de strings "HH:MM".
POSTING_SLOTS = [s.strip() for s in (_get("POSTING_SLOTS", "19:00") or "").split(",") if s.strip()]


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
