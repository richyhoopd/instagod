"""Login por magic link, sesión en cookie httpOnly, /me y /auth/verify."""
from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr

import config
from api import mail
from api.deps import COOKIE, get_cx, usuario_actual
from api.errors import ApiError, no_autenticado
from src import users

router = APIRouter(tags=["auth"])


class PedirLink(BaseModel):
    email: EmailStr


def _poner_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, max_age=config.SESSION_DAYS * 86400, httponly=True,
                    secure=(config.ENV == "prod"), samesite="lax", path="/",
                    domain=config.COOKIE_DOMAIN or None)


@router.post("/auth/magic-link")
def pedir_magic_link(datos: PedirLink, request: Request, cx=Depends(get_cx)) -> dict:
    email = datos.email.lower()
    ip = request.client.host if request.client else "?"
    limite_email = request.app.state.limite_email
    limite_ip = request.app.state.limite_ip
    if not (limite_email.permitir(email) and limite_ip.permitir(ip)):
        raise ApiError(429, "demasiados_intentos", "Espera un rato antes de pedir otro link")
    u = users.por_email(cx, email)
    if u and u["activo"]:
        tok = users.crear_magic_link(cx, u["id"])
        url = f"{config.API_URL}/auth/callback?token={tok}"
        mail.enviar_magic_link(email, url)
    return {"ok": True}   # nunca revela si el email existe


_CALLBACK_HTML = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="robots" content="noindex"><title>Entrando a instagod…</title>
<style>body{font-family:system-ui,sans-serif;display:flex;min-height:100svh;align-items:center;
justify-content:center;margin:0;background:#fafafa;color:#111}form{text-align:center}
button{font:inherit;padding:.7rem 1.4rem;border-radius:.5rem;border:0;background:#111;color:#fff;cursor:pointer}
</style></head><body><form method="post" action="">
<input type="hidden" name="token" value="__TOKEN__">
<p>Entrando a instagod…</p><button type="submit">Entrar</button></form>
<script>document.forms[0].submit()</script></body></html>"""


@router.get("/auth/callback", name="auth_callback")
def auth_callback_get(token: str) -> HTMLResponse:
    # No consume el token con GET: las vistas previas de chats/correo hacen GET y
    # quemarían el link de un solo uso. El navegador real manda el POST (auto-submit).
    html = _CALLBACK_HTML.replace("__TOKEN__", escape(token, quote=True))
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@router.post("/auth/callback")
def auth_callback(request: Request, token: str | None = Form(None),
                  cx=Depends(get_cx)) -> RedirectResponse:
    token = token or request.query_params.get("token") or ""
    try:
        uid = users.consumir_magic_link(cx, token)
    except users.LinkInvalido:
        return RedirectResponse(f"{config.APP_URL}/login?error=link_invalido", status_code=303)
    ses = users.crear_sesion(cx, uid, dias=config.SESSION_DAYS,
                             ua=request.headers.get("user-agent"))
    resp = RedirectResponse(f"{config.APP_URL}/brands", status_code=303)
    _poner_cookie(resp, ses)
    return resp


@router.post("/auth/logout")
def logout(request: Request, cx=Depends(get_cx)) -> Response:
    tok = request.cookies.get(COOKIE)
    if tok:
        users.cerrar_sesion(cx, tok)
    resp = Response(content='{"ok": true}', media_type="application/json")
    resp.delete_cookie(COOKIE, path="/", domain=config.COOKIE_DOMAIN or None)
    return resp


@router.get("/auth/verify")
def verify(user: dict = Depends(usuario_actual)) -> dict:
    """Para forward_auth de Caddy (GUI legacy): 200 solo si la sesión es admin."""
    if not user.get("is_admin"):
        raise no_autenticado()
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    return {"id": user["id"], "email": user["email"], "nombre": user["nombre"],
            "is_admin": bool(user["is_admin"]), "marcas": users.marcas_de(cx, user["id"])}
