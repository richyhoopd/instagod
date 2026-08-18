"""Login por magic link, sesión en cookie httpOnly, /me y /auth/verify."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr

import config
from api import mail
from api.deps import COOKIE, get_cx, usuario_actual
from api.errors import ApiError, no_autenticado
from api.ratelimit import Limitador
from src import users

router = APIRouter(tags=["auth"])
_limite_email = Limitador(5, 3600)
_limite_ip = Limitador(5, 3600)


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
    if not (_limite_email.permitir(email) and _limite_ip.permitir(ip)):
        raise ApiError(429, "demasiados_intentos", "Espera un rato antes de pedir otro link")
    u = users.por_email(cx, email)
    if u and u["activo"]:
        tok = users.crear_magic_link(cx, u["id"])
        url = str(request.url_for("auth_callback")) + f"?token={tok}"
        mail.enviar_magic_link(email, url)
    return {"ok": True}   # nunca revela si el email existe


@router.get("/auth/callback", name="auth_callback")
def auth_callback(token: str, request: Request, cx=Depends(get_cx)) -> RedirectResponse:
    try:
        uid = users.consumir_magic_link(cx, token)
    except users.LinkInvalido:
        return RedirectResponse(f"{config.APP_URL}/login?error=link_invalido", status_code=302)
    ses = users.crear_sesion(cx, uid, dias=config.SESSION_DAYS,
                             ua=request.headers.get("user-agent"))
    resp = RedirectResponse(f"{config.APP_URL}/brands", status_code=302)
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
