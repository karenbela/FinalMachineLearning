"""MySQL backed opaque-cookie authentication; CSRF token for state-changing routes."""
from datetime import datetime, timedelta, timezone
from threading import Lock
from collections import defaultdict
import os
import time

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_engine
from app.security import digest, equal_hash, fresh_secret, verify_password

router = APIRouter(prefix="/api/auth", tags=["Autentikasi"])
COOKIE_NAME = "edelweiss_session"
SESSION_HOURS = 8
FAILED_MAX = 6
FAILED_WINDOW_SECONDS = 300
_attempts = defaultdict(list)
_attempt_lock = Lock()


def utc_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def public_user(user):
    return {k: user[k] for k in ("user_id", "username", "display_name", "role_name")}


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


def _check_origin(request: Request):
    origin = request.headers.get("origin")
    if not origin:
        return
    # Explicit trusted dev origins; no wildcards, credentials cannot be shared across random origins.
    origins = {x.strip() for x in os.getenv("CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8000").split(",") if x.strip()}
    if origin not in origins:
        raise HTTPException(status_code=403, detail="Origin tidak diizinkan.")


def _throttle(ip):
    now = time.monotonic()
    with _attempt_lock:
        recent = [t for t in _attempts[ip] if now - t <= FAILED_WINDOW_SECONDS]
        _attempts[ip] = recent
        if len(recent) >= FAILED_MAX:
            raise HTTPException(429, "Terlalu banyak percobaan. Coba lagi nanti.")


def _failure(ip):
    with _attempt_lock:
        _attempts[ip].append(time.monotonic())


def _success(ip):
    with _attempt_lock:
        _attempts.pop(ip, None)


@router.post("/login")
def login(payload: LoginInput, request: Request, response: Response):
    _check_origin(request)
    ip = request.client.host if request.client else "unknown"
    _throttle(ip)
    try:
        with get_engine().begin() as conn:
            user = conn.execute(text("""
                SELECT u.user_id,u.username,u.display_name,u.password_hash,u.is_active,r.role_name
                FROM users u JOIN roles r ON r.role_id=u.role_id
                WHERE u.username=:username OR u.email=:username LIMIT 1
            """), {"username": payload.username}).mappings().first()
            # Identical error for unknown or invalid account to avoid username enumeration.
            if not user or not user["is_active"] or not verify_password(user["password_hash"], payload.password):
                _failure(ip)
                raise HTTPException(status_code=401, detail="Username/email atau password salah.")
            raw_token, raw_csrf = fresh_secret(), fresh_secret()
            now = utc_naive()
            conn.execute(text("""
                INSERT INTO auth_sessions(user_id,token_hash,csrf_hash,created_at,expires_at)
                VALUES(:uid,:th,:ch,:created,:expires)
            """), {"uid":user["user_id"],"th":digest(raw_token),"ch":digest(raw_csrf),
                    "created":now,"expires":now+timedelta(hours=SESSION_HOURS)})
            conn.execute(text("""
                INSERT INTO audit_logs(user_id,action_type,entity_name,entity_key)
                VALUES(:uid,'LOGIN','users',:uk)
            """), {"uid":user["user_id"],"uk":str(user["user_id"])})
        _success(ip)
        response.set_cookie(COOKIE_NAME,raw_token,httponly=True,
                            secure=os.getenv("COOKIE_SECURE","false").lower()=="true",
                            samesite="lax",path="/",max_age=SESSION_HOURS*3600)
        return {"user":public_user(user),"csrf_token":raw_csrf,"expires_in_seconds":SESSION_HOURS*3600}
    except SQLAlchemyError as exc:
        raise HTTPException(503,"Database autentikasi tidak tersedia. Pastikan migrasi SQL dijalankan.") from exc


def current_session(session_token: str | None = Cookie(default=None, alias=COOKIE_NAME)):
    if not session_token:
        raise HTTPException(status_code=401,detail="Silakan login terlebih dahulu.")
    try:
        with get_engine().connect() as conn:
            row=conn.execute(text("""
                SELECT s.session_id,s.csrf_hash,u.user_id,u.username,u.display_name,r.role_name
                FROM auth_sessions s
                JOIN users u ON u.user_id=s.user_id
                JOIN roles r ON r.role_id=u.role_id
                WHERE s.token_hash=:hash AND s.revoked_at IS NULL
                  AND s.expires_at>:now AND u.is_active=1
                LIMIT 1
            """),{"hash":digest(session_token),"now":utc_naive()}).mappings().first()
            if not row:
                raise HTTPException(401,"Sesi tidak berlaku. Silakan login kembali.")
            return dict(row)
    except SQLAlchemyError as exc:
        raise HTTPException(503,"Layanan autentikasi sedang tidak tersedia.") from exc


def require_roles(*roles: str):
    def check(session=Depends(current_session)):
        if session["role_name"] not in roles:
            raise HTTPException(403,"Anda tidak memiliki izin untuk mengakses data ini.")
        return session
    return check


def require_csrf(request: Request, csrf: str | None = Header(default=None, alias="X-CSRF-Token"), session=Depends(current_session)):
    _check_origin(request)
    if not csrf or not equal_hash(digest(csrf),session["csrf_hash"]):
        raise HTTPException(403,"Token CSRF tidak sesuai.")
    return session


@router.get("/me")
def me(session=Depends(current_session)):
    return {"user":public_user(session)}


@router.post("/logout")
def logout(response: Response, session=Depends(require_csrf)):
    try:
        with get_engine().begin() as conn:
            conn.execute(text("UPDATE auth_sessions SET revoked_at=:now WHERE session_id=:sid"),
                         {"now":utc_naive(),"sid":session["session_id"]})
            conn.execute(text("""
                INSERT INTO audit_logs(user_id,action_type,entity_name,entity_key)
                VALUES(:uid,'LOGOUT','users',:uk)
            """),{"uid":session["user_id"],"uk":str(session["user_id"])})
    except SQLAlchemyError as exc:
        raise HTTPException(503,"Gagal mengakhiri sesi pada database.") from exc
    response.delete_cookie(COOKIE_NAME,path="/",samesite="lax",secure=os.getenv("COOKIE_SECURE","false").lower()=="true")
    return {"message":"Berhasil logout."}

@router.get('/csrf')
def csrf_for_existing_session(session=Depends(current_session)):
    """Issue a fresh CSRF token only to an authenticated session; stored hashed value changes atomically."""
    token=fresh_secret()
    with get_engine().begin() as conn:
        conn.execute(text('UPDATE auth_sessions SET csrf_hash=:h WHERE session_id=:sid'),{'h':digest(token),'sid':session['session_id']})
    return {'csrf_token':token}
