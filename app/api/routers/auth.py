from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.infrastructure.config.settings import get_settings
from app.infrastructure.db.models import User

router = APIRouter(tags=["auth"])

_TEMPLATE_DIR = str(Path(__file__).resolve().parents[2] / "dashboard" / "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

SESSION_COOKIE = "hf_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sign_session(uid: str, hid: str) -> str:
    secret = get_settings().session_secret
    if not secret:
        raise RuntimeError("SESSION_SECRET is not configured")
    payload = json.dumps({"uid": uid, "hid": hid, "exp": int(time.time()) + SESSION_TTL_SECONDS}, separators=(",", ":")).encode()
    body = _b64url_encode(payload)
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(sig)}"


def verify_session(token: str) -> dict | None:
    secret = get_settings().session_secret
    if not secret or not token or "." not in token:
        return None
    body, sig = token.split(".", 1)
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    try:
        got = _b64url_decode(sig)
    except Exception:
        return None
    if not hmac.compare_digest(expected, got):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except Exception:
        return None
    if payload.get("exp", 0) < int(time.time()):
        return None
    return payload


def _verify_telegram_auth(params: dict[str, str]) -> bool:
    token = get_settings().telegram_bot_token
    if not token:
        return False
    received_hash = params.get("hash", "")
    pairs = [f"{k}={v}" for k, v in sorted(params.items()) if k != "hash"]
    data_check_string = "\n".join(pairs)
    secret_key = hashlib.sha256(token.encode()).digest()
    expected = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received_hash)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    bot_username = get_settings().telegram_bot_username or ""
    return templates.TemplateResponse(
        request,
        "login.html",
        {"bot_username": bot_username},
    )


@router.get("/auth/telegram/callback")
def telegram_callback(request: Request, db: Session = Depends(get_db)) -> Response:
    params = {k: v for k, v in request.query_params.items()}
    if "hash" not in params or "id" not in params or "auth_date" not in params:
        raise HTTPException(status_code=400, detail="missing telegram auth params")

    if not _verify_telegram_auth(params):
        raise HTTPException(status_code=401, detail="invalid telegram signature")

    try:
        auth_date = int(params["auth_date"])
    except ValueError:
        raise HTTPException(status_code=400, detail="bad auth_date")
    if abs(int(time.time()) - auth_date) > 86400:
        raise HTTPException(status_code=401, detail="auth_date expired")

    tg_id = str(params["id"])
    user = db.query(User).filter(User.telegram_id == tg_id, User.is_active.is_(True)).one_or_none()
    if user is None:
        raise HTTPException(status_code=403, detail="user not allowed")

    token = sign_session(str(user.id), str(user.household_id))
    secure = request.url.scheme == "https"
    resp = RedirectResponse(url=f"/finance/report?household_id={user.household_id}", status_code=302)
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return resp


@router.post("/auth/logout")
def logout() -> Response:
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp
