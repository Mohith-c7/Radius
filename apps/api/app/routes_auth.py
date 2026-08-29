"""HTTP boundary for Radius authentication. Sessions are HTTP-only cookies."""
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import secrets
from urllib.parse import urlencode
import httpx
import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import consume_action_token, create_action_token, create_session, decode_session, hash_password, user_from_provider, verify_password
from .config import get_settings
from .database import get_db
from .models import AuthSession, User
from .schemas import ForgotPassword, Login, ResetPassword, Signup, UserResponse, VerifyToken

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
SESSION_COOKIE = "radius_session"
OAUTH_STATE_COOKIE = "radius_oauth_state"


def public_user(user: User) -> UserResponse:
    return UserResponse(id=user.id, name=user.name, email=user.email, email_verified=user.email_verified, role=user.role)


def set_session(response: Response, db: Session, user: User, remember: bool = False) -> None:
    settings = get_settings()
    response.set_cookie(SESSION_COOKIE, create_session(db, user, remember), httponly=True, secure=settings.session_cookie_secure, samesite="lax", max_age=60 * 60 * 24 * (30 if remember else 14), path="/")


def current_user(radius_session: str | None = Cookie(default=None), db: Session = Depends(get_db)) -> User:
    if not radius_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Please sign in again.")
    user_id, session_id = decode_session(radius_session)
    session = db.get(AuthSession, session_id)
    user = db.get(User, user_id)
    if not user or not session or session.user_id != user.id or session.revoked_at is not None or session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session has expired. Please sign in again.")
    return user


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: Signup, response: Response, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email.lower())):
        raise HTTPException(status_code=409, detail="An account with this email already exists. Please sign in instead.")
    user = User(name=payload.name.strip(), email=payload.email.lower(), password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_action_token(db, user.id, "verify_email", minutes=24 * 60)
    # Email delivery is deliberately not simulated. Console mode exposes a development-only link in server logs.
    if get_settings().email_delivery_mode == "console":
        print(f"[Radius development] Verify email: {get_settings().frontend_origin}/verify-email?token={token}")
    set_session(response, db, user)
    return public_user(user)


@router.post("/login", response_model=UserResponse)
def login(payload: Login, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Unable to sign in. Please check your credentials and try again.")
    set_session(response, db, user, payload.remember)
    return public_user(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, radius_session: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    if radius_session:
        try:
            _, session_id = decode_session(radius_session)
            session = db.get(AuthSession, session_id)
            if session:
                session.revoked_at = datetime.utcnow()
                db.commit()
        except HTTPException:
            pass
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(current_user)):
    return public_user(user)


@router.post("/refresh", response_model=UserResponse)
def refresh(response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    set_session(response, db, user)
    return public_user(user)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(payload: ForgotPassword, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user:
        token = create_action_token(db, user.id, "reset_password")
        if get_settings().email_delivery_mode == "console":
            print(f"[Radius development] Reset password: {get_settings().frontend_origin}/reset-password?token={token}")
    return {"message": "If an account exists for this address, a reset link has been sent."}


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: ResetPassword, db: Session = Depends(get_db)):
    user = consume_action_token(db, payload.token, "reset_password")
    user.password_hash = hash_password(payload.password)
    db.commit()


@router.post("/verify-email", response_model=UserResponse)
def verify_email(payload: VerifyToken, db: Session = Depends(get_db)):
    user = consume_action_token(db, payload.token, "verify_email")
    user.email_verified = True
    db.commit()
    return public_user(user)


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
def resend_verification(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not user.email_verified:
        token = create_action_token(db, user.id, "verify_email", minutes=24 * 60)
        if get_settings().email_delivery_mode == "console":
            print(f"[Radius development] Verify email: {get_settings().frontend_origin}/verify-email?token={token}")
    return {"message": "If your address is unverified, a verification link has been sent."}


def oauth_config(provider: str) -> tuple[str, str, str, str, str, str]:
    settings = get_settings()
    if provider == "google" and settings.google_client_id and settings.google_client_secret and settings.google_redirect_uri:
        return settings.google_client_id, settings.google_client_secret, settings.google_redirect_uri, "https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token", "https://openidconnect.googleapis.com/v1/userinfo"
    if provider == "github" and settings.github_client_id and settings.github_client_secret and settings.github_redirect_uri:
        return settings.github_client_id, settings.github_client_secret, settings.github_redirect_uri, "https://github.com/login/oauth/authorize", "https://github.com/login/oauth/access_token", "https://api.github.com/user"
    raise HTTPException(status_code=503, detail=f"{provider.title()} sign in is not configured.")


@router.get("/oauth/{provider}")
def oauth_start(provider: str, response: Response):
    if provider not in {"google", "github"}:
        raise HTTPException(status_code=404, detail="Authentication provider not found.")
    client_id, _, callback, authorization_url, _, _ = oauth_config(provider)
    nonce = secrets.token_urlsafe(24)
    state = jwt.encode({"provider": provider, "nonce": nonce, "exp": datetime.now(timezone.utc) + timedelta(minutes=10)}, get_settings().session_secret, algorithm="HS256")
    params = {"client_id": client_id, "redirect_uri": callback, "response_type": "code", "state": state}
    if provider == "google":
        params.update({"scope": "openid email profile", "nonce": nonce})
    else:
        params.update({"scope": "read:user user:email"})
    response.status_code = status.HTTP_307_TEMPORARY_REDIRECT
    response.headers["Location"] = f"{authorization_url}?{urlencode(params)}"
    response.set_cookie(OAUTH_STATE_COOKIE, nonce, httponly=True, secure=get_settings().session_cookie_secure, samesite="lax", max_age=600, path="/")
    return response


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str, state: str, response: Response, radius_oauth_state: str | None = Cookie(default=None), db: Session = Depends(get_db)):
    try:
        saved = jwt.decode(state, get_settings().session_secret, algorithms=["HS256"])
        if saved.get("provider") != provider or not radius_oauth_state or not secrets.compare_digest(saved["nonce"], radius_oauth_state):
            raise ValueError("Invalid OAuth state")
        client_id, client_secret, callback, _, token_url, profile_url = oauth_config(provider)
        async with httpx.AsyncClient(timeout=10) as client:
            token_response = await client.post(token_url, data={"client_id": client_id, "client_secret": client_secret, "code": code, "redirect_uri": callback, "grant_type": "authorization_code"}, headers={"Accept": "application/json"})
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]
            profile = (await client.get(profile_url, headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})).json()
            if provider == "github" and not profile.get("email"):
                emails = (await client.get("https://api.github.com/user/emails", headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})).json()
                profile["email"] = next((item["email"] for item in emails if item.get("primary") and item.get("verified")), None)
        provider_id = str(profile.get("sub") if provider == "google" else profile.get("id"))
        email = profile.get("email")
        if not provider_id or not email:
            raise ValueError("Provider did not supply a verified identity")
        user = user_from_provider(db, provider, provider_id, email, profile.get("name") or profile.get("login") or email)
        set_session(response, db, user)
        response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
        response.status_code = status.HTTP_307_TEMPORARY_REDIRECT
        response.headers["Location"] = f"{get_settings().frontend_origin}/"
        return response
    except Exception:
        response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
        response.status_code = status.HTTP_307_TEMPORARY_REDIRECT
        response.headers["Location"] = f"{get_settings().frontend_origin}/login?error=oauth"
        return response
