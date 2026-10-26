"""Botones "Probar" de la pestaña Conexiones. Manager+."""
from __future__ import annotations

import requests
from fastapi import APIRouter, Depends

import config
from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, cred_faltante

router = APIRouter(prefix="/brands/{slug}", tags=["pruebas"])


# --- adaptadores remotos (monkeypatcheables en tests) ---

def _telegram_send(token: str, chat_id: str, texto: str) -> dict:
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": texto}, timeout=15)
    r.raise_for_status()
    return r.json()


def _ig_me(token: str) -> dict:
    r = requests.get("https://graph.instagram.com/me",
                     params={"fields": "id,username", "access_token": token}, timeout=15)
    r.raise_for_status()
    return r.json()


def _fb_page(page_id: str, token: str) -> dict:
    from src import facebook
    r = requests.get(f"{facebook.GRAPH}/{facebook.API_VERSION}/{page_id}",
                     params={"fields": "id,name", "access_token": token}, timeout=15)
    r.raise_for_status()
    return r.json()


def _fb_debug(token: str) -> dict:
    """debug_token del propio token de página (input_token = access_token)."""
    from src import facebook
    r = requests.get(f"{facebook.GRAPH}/{facebook.API_VERSION}/debug_token",
                     params={"input_token": token, "access_token": token}, timeout=15)
    r.raise_for_status()
    return r.json().get("data") or {}


def _llm_ping(provider: str, key: str, model: str) -> str:
    if provider == "claude":
        import anthropic
        msg = anthropic.Anthropic(api_key=key).messages.create(
            model=model, max_tokens=5, messages=[{"role": "user", "content": "Di 'ok'"}])
        return msg.content[0].text
    from openai import OpenAI
    out = OpenAI(api_key=key, base_url=config.DEEPSEEK_BASE_URL).chat.completions.create(
        model=model, max_tokens=5, messages=[{"role": "user", "content": "Di 'ok'"}])
    return out.choices[0].message.content or ""


def _fallo(e: Exception, secretos: list[str] | None = None) -> ApiError:
    if secretos is None:
        secretos = []

    # For HTTPError with response, only show status code
    if isinstance(e, requests.HTTPError) and hasattr(e, 'response') and e.response is not None:
        detalle = f"El servicio respondió HTTP {e.response.status_code}"
    else:
        detalle = str(e)

    # Redact secrets
    for secreto in secretos:
        if secreto:
            detalle = detalle.replace(secreto, "***")

    # Truncate to 200 chars
    detalle = detalle[:200]
    return ApiError(502, "prueba_fallida", detalle)


def _llm_de(creds: dict) -> tuple[str, str, str]:
    provider = (creds.get("LLM_PROVIDER") or config.LLM_PROVIDER or "deepseek").lower()
    if creds.get("LLM_API_KEY"):
        key = creds["LLM_API_KEY"]
    else:
        key = config.ANTHROPIC_API_KEY if provider == "claude" else config.DEEPSEEK_API_KEY
    if not key:
        raise cred_faltante("LLM_API_KEY")
    model = creds.get("LLM_MODEL") or (
        config.ANTHROPIC_MODEL if provider == "claude" else config.DEEPSEEK_MODEL)
    return provider, key, model


@router.post("/telegram/test")
def telegram_test(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    creds = config.account_creds(slug)
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if not creds.get(k):
            raise cred_faltante(k)
    try:
        _telegram_send(creds["TELEGRAM_BOT_TOKEN"], creds["TELEGRAM_CHAT_ID"],
                       f"✅ instagod conectado a {fila['nombre']} ({fila['ig_handle']})")
    except Exception as e:  # noqa: BLE001
        raise _fallo(e, [creds["TELEGRAM_BOT_TOKEN"], creds["TELEGRAM_CHAT_ID"]]) from e
    return {"ok": True, "detalle": "Mensaje enviado al chat configurado"}


@router.post("/instagram/test")
def instagram_test(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    marca_para(slug, cx, user, minimo="manager")
    creds = config.account_creds(slug)
    for k in ("IG_ACCESS_TOKEN", "IG_USER_ID"):
        if not creds.get(k):
            raise cred_faltante(k)
    try:
        me = _ig_me(creds["IG_ACCESS_TOKEN"])
    except Exception as e:  # noqa: BLE001
        raise _fallo(e, [creds["IG_ACCESS_TOKEN"]]) from e
    return {"ok": True, "username": me.get("username"), "id": me.get("id")}


@router.post("/facebook/test")
def facebook_test(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    marca_para(slug, cx, user, minimo="manager")
    creds = config.account_creds(slug)
    for k in ("FB_PAGE_ID", "FB_PAGE_ACCESS_TOKEN"):
        if not creds.get(k):
            raise cred_faltante(k)
    token = creds["FB_PAGE_ACCESS_TOKEN"]
    try:
        pagina = _fb_page(creds["FB_PAGE_ID"], token)
        info = _fb_debug(token)
    except Exception as e:  # noqa: BLE001
        raise _fallo(e, [token]) from e
    scopes = sorted(info.get("scopes") or [])
    tipo = info.get("type")
    expira = info.get("expires_at") or None  # 0 = no expira
    avisos = []
    if tipo != "PAGE":
        avisos.append(f"El token es de tipo {tipo}, no PAGE: genera uno de página.")
    if "pages_manage_posts" not in scopes:
        avisos.append("Al token le falta pages_manage_posts: no podrá publicar.")
    if info.get("is_valid") is False:
        avisos.append("Facebook marca el token como inválido.")
    if info.get("profile_id") and str(info["profile_id"]) != str(pagina.get("id")):
        avisos.append("El token es de otra página distinta a FB_PAGE_ID.")
    return {"ok": not avisos, "id": pagina.get("id"), "name": pagina.get("name"),
            "tipo": tipo, "scopes": scopes, "expira": expira, "avisos": avisos}


@router.post("/llm/test")
def llm_test(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    marca_para(slug, cx, user, minimo="manager")
    provider, key, model = _llm_de(config.account_creds(slug))
    try:
        respuesta = _llm_ping(provider, key, model)
    except Exception as e:  # noqa: BLE001
        raise _fallo(e, [key]) from e
    return {"ok": True, "provider": provider, "model": model, "respuesta": respuesta[:80]}
