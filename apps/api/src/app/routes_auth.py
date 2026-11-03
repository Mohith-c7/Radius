"""HTTP boundary for Radius authentication. Sessions are HTTP-only cookies."""

import html
import logging
import smtplib
import time
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import oauth
from .auth import (
    SESSION_TTL,
    burn_password_check,
    consume_action_token,
    create_action_token,
    create_session,
    decode_session,
    hash_password,
    is_production_like,
    provision_domain_user_and_org,
    revoke_user_sessions,
    should_auto_verify_email,
    user_from_provider,
    verify_password,
)
from .config import get_settings
from .database import get_db
from .models import AuthSession, User
from .schemas import (
    ForgotPassword,
    Login,
    ResetPassword,
    Signup,
    UserResponse,
    VerifyToken,
)

LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
SESSION_COOKIE = "radius_session"


def send_email_message(
    to_email: str, subject: str, text_body: str, html_body: str
) -> bool:
    settings = get_settings()
    sender = (
        settings.smtp_from_email or settings.smtp_username or "radius.yourapp@gmail.com"
    )
    if settings.email_delivery_mode == "log":
        # Local development: no mail server. The text body carries the link.
        # (Settings refuses this mode when RADIUS_ENV=production.)
        print(
            f"\n[Radius Email (EMAIL_DELIVERY_MODE=log)] TO: {to_email}\n"
            f"Subject: {subject}\n{text_body}\n",
            flush=True,
        )
        return True
    if settings.smtp_username and settings.smtp_password:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"Radius <{sender}>"
            msg["To"] = to_email
            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.starttls()
                server.login(settings.smtp_username, settings.smtp_password)
                server.sendmail(sender, [to_email], msg.as_string())
            LOGGER.info("email dispatched via SMTP")
            return True
        except Exception as exc:
            # Class name only: SMTP error text can echo the recipient or credentials.
            LOGGER.warning("email dispatch failed: %s", type(exc).__name__)
            return False
    LOGGER.warning("SMTP_USERNAME/SMTP_PASSWORD are not set; email was not sent")
    return False


_LOGIN_FAILURE_LIMIT = 10
_LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
_LOGIN_TRACKED_MAX = 10_000
_login_failures: dict[str, tuple[int, float]] = {}


def _login_locked(email: str) -> bool:
    entry = _login_failures.get(email)
    if entry is None:
        return False
    count, started = entry
    if time.monotonic() - started > _LOGIN_FAILURE_WINDOW_SECONDS:
        _login_failures.pop(email, None)
        return False
    return count >= _LOGIN_FAILURE_LIMIT


def _note_login_failure(email: str) -> None:
    now = time.monotonic()
    if len(_login_failures) >= _LOGIN_TRACKED_MAX:
        for key in [
            k
            for k, (_, started) in _login_failures.items()
            if now - started > _LOGIN_FAILURE_WINDOW_SECONDS
        ]:
            _login_failures.pop(key, None)
        if len(_login_failures) >= _LOGIN_TRACKED_MAX:
            return  # full of live entries: stay bounded, rely on the per-IP limiter
    count, started = _login_failures.get(email, (0, now))
    if now - started > _LOGIN_FAILURE_WINDOW_SECONDS:
        count, started = 0, now
    _login_failures[email] = (count + 1, started)


def _mail_name(user: User) -> str:
    """The user-chosen display name, safe for interpolation into HTML mail (A-08)."""
    return html.escape(user.name or "", quote=True)


def public_user(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        email_verified=user.email_verified,
        role=user.role,
        organization_id=getattr(user, "organization_id", None),
    )


def set_session(
    response: Response, db: Session, user: User, remember: bool = False
) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        create_session(db, user, remember),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=60 * 60 * 24 * (30 if remember else 14),
        path="/",
    )


def current_user(
    radius_session: str | None = Cookie(default=None), db: Session = Depends(get_db)
) -> User:
    if not radius_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Please sign in again.",
        )
    return _load_session(radius_session, db)[0]


def _expired() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Your session has expired. Please sign in again.",
    )


def _load_session(token: str, db: Session) -> tuple[User, AuthSession]:
    """Resolve a session cookie to (user, live session row) or raise 401.

    Every attribute of the row is read only after the existence check: a validly
    signed token whose row is gone is an expired session, not a server error.
    """
    user_id, session_id = decode_session(token)
    session = db.get(AuthSession, session_id)
    user = db.get(User, user_id)
    if not user or not session or session.user_id != user.id:
        raise _expired()
    if session.revoked_at is not None:
        raise _expired()
    expires_at = (
        session.expires_at
        if session.expires_at.tzinfo is not None
        else session.expires_at.replace(tzinfo=UTC)
    )
    if expires_at < datetime.now(UTC):
        raise _expired()
    return user, session


@router.post(
    "/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def signup(payload: Signup, response: Response, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == payload.email.lower())):
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists. Please sign in instead.",
        )
    auto_verify = should_auto_verify_email()
    user = User(
        name=payload.name.strip(),
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        email_verified=auto_verify,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if user.email_verified or not is_production_like():
        provision_domain_user_and_org(db, user)
        db.refresh(user)
    # Production/uat, unverified: do NOT join an existing organization / domain user
    # for this address yet. Whoever types an e-mail address at signup has not proven
    # they own it (A-07); provisioning happens when the address is verified.
    token = create_action_token(db, user.id, "verify_email", minutes=24 * 60)
    verify_url = f"{get_settings().frontend_origin}/verify-email?token={token}"
    subject = "Verify your Radius account"
    text_body = f"Hello {user.name},\n\nThank you for signing up for Radius.\n\nPlease verify your email address by visiting:\n{verify_url}\n"
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px; padding: 24px; border: 1px solid #e7ece8; border-radius: 8px;">
      <h2 style="color: #13231E;">Welcome to Radius</h2>
      <p style="color: #555;">Hello {_mail_name(user)},</p>
      <p style="color: #555;">Please verify your email address to secure your account.</p>
      <div style="margin: 24px 0;">
        <a href="{verify_url}" style="background-color: #19815C; color: #ffffff; padding: 12px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Verify Email Address</a>
      </div>
      <p style="color: #888; font-size: 12px;">Or copy and paste this link into your browser:<br/><a href="{verify_url}">{verify_url}</a></p>
    </div>
    """
    send_email_message(user.email, subject, text_body, html_body)
    if user.email_verified or not is_production_like():
        set_session(response, db, user)
    # Production/uat: no session until the address is verified (A-07).
    return public_user(user)


@router.post("/login", response_model=UserResponse)
def login(payload: Login, response: Response, db: Session = Depends(get_db)):
    email = payload.email.lower()
    if _login_locked(email):
        raise HTTPException(
            status_code=429,
            detail="Too many failed sign-in attempts. Try again later.",
        )
    user = db.scalar(select(User).where(User.email == email))
    if user is not None and user.password_hash:
        ok = verify_password(payload.password, user.password_hash)
    else:
        # Same argon2 work for unknown accounts: response time must not reveal them.
        burn_password_check(payload.password)
        ok = False
    if not ok or user is None:
        _note_login_failure(email)
        raise HTTPException(
            status_code=401,
            detail="Unable to sign in. Please check your credentials and try again.",
        )
    if not user.email_verified and is_production_like():
        raise HTTPException(
            status_code=403,
            detail=(
                "Verify your email address before signing in. If the link has "
                "expired, use 'Forgot password' to prove ownership of the address."
            ),
        )
    _login_failures.pop(email, None)
    if not user.organization_id:
        provision_domain_user_and_org(db, user)
        db.refresh(user)
    set_session(response, db, user, payload.remember)
    return public_user(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    radius_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if radius_session:
        try:
            _, session_id = decode_session(radius_session)
            session = db.get(AuthSession, session_id)
            if session:
                session.revoked_at = datetime.now(UTC)
                db.commit()
        except HTTPException:
            pass
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(current_user)):
    return public_user(user)


@router.post("/refresh", response_model=UserResponse)
def refresh(
    response: Response,
    radius_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    """Rotate the session: the presented one is revoked, a fresh one is issued.

    A stolen cookie therefore cannot mint sessions that outlive the original
    (each refresh kills its predecessor), and the "remember me" lifetime is kept.
    """
    if not radius_session:
        raise _expired()
    user, old = _load_session(radius_session, db)
    created = old.created_at if old.created_at.tzinfo else old.created_at.replace(tzinfo=UTC)
    expires = old.expires_at if old.expires_at.tzinfo else old.expires_at.replace(tzinfo=UTC)
    remembered = (expires - created) > SESSION_TTL + timedelta(days=1)
    old.revoked_at = datetime.now(UTC)
    db.commit()
    set_session(response, db, user, remembered)
    return public_user(user)


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(payload: ForgotPassword, db: Session = Depends(get_db)):
    email_clean = payload.email.lower().strip()
    if not email_clean:
        raise HTTPException(
            status_code=400, detail="Please enter a valid email address."
        )

    user = db.scalar(select(User).where(User.email == email_clean))
    if user:
        token = create_action_token(db, user.id, "reset_password", minutes=30)
        reset_url = f"{get_settings().frontend_origin}/reset-password?token={token}"
        subject = "Reset your Radius password"
        text_body = (
            f"Hello {user.name},\n\n"
            f"You requested a password reset for your Radius account.\n\n"
            f"Please visit the link below to choose a new password:\n"
            f"{reset_url}\n\n"
            f"This link will expire in 30 minutes.\n"
            f"If you did not request a password reset, you can safely ignore this email.\n"
        )
        html_body = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 520px; padding: 32px; border: 1px solid #E7ECE8; border-radius: 12px; background-color: #FFFFFF;">
      <div style="margin-bottom: 24px;">
        <span style="font-weight: 800; font-size: 20px; color: #17211E; letter-spacing: -0.8px;">radius</span>
      </div>
      <h2 style="font-size: 20px; font-weight: 800; color: #17211E; margin: 0 0 12px 0;">Reset your password</h2>
      <p style="font-size: 14px; line-height: 1.6; color: #70807A; margin: 0 0 24px 0;">
        Hello {_mail_name(user)}, we received a request to reset your password for your Radius account.
      </p>
      <div style="margin: 28px 0;">
        <a href="{reset_url}" style="background-color: #19815C; color: #FFFFFF; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 14px; display: inline-block;">Reset Password</a>
      </div>
      <p style="font-size: 12px; color: #70807A; line-height: 1.5; margin: 24px 0 0 0;">
        Or copy and paste this link into your browser:<br/>
        <a href="{reset_url}" style="color: #19815C; word-break: break-all;">{reset_url}</a>
      </p>
      <hr style="border: none; border-top: 1px solid #E7ECE8; margin: 24px 0;" />
      <p style="font-size: 11px; color: #70807A; margin: 0;">This reset link will expire in 30 minutes. If you did not request this, please ignore this email.</p>
    </div>
        """
        send_email_message(email_clean, subject, text_body, html_body)
    return {
        "message": "If an account exists for this address, a reset link has been sent."
    }


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: ResetPassword, db: Session = Depends(get_db)):
    if not payload.token:
        raise HTTPException(
            status_code=400, detail="This link is invalid or has expired."
        )
    user = consume_action_token(db, payload.token, "reset_password")
    user.password_hash = hash_password(payload.password)
    user.email_verified = True
    # Whoever held the old password (or a session made with it) must be signed out.
    revoke_user_sessions(db, user.id)
    db.commit()
    if not user.organization_id:
        provision_domain_user_and_org(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/verify-email", response_model=UserResponse)
def verify_email(payload: VerifyToken, db: Session = Depends(get_db)):
    user = consume_action_token(db, payload.token, "verify_email")
    was_unverified = not user.email_verified
    user.email_verified = True
    if was_unverified and is_production_like():
        # Pre-hijacking defence (A-07): the password on an account that was
        # unverified until now was chosen by whoever typed the address at signup,
        # who may not be the mailbox owner. Clear it so the mailbox owner sets
        # their own via "Forgot password" (sign-in with Google/GitHub also works).
        user.password_hash = None
    # Sessions created before the address was proven are not trusted either.
    revoke_user_sessions(db, user.id)
    db.commit()
    if not user.organization_id:
        provision_domain_user_and_org(db, user)
        db.refresh(user)
    return public_user(user)


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
def resend_verification(
    user: User = Depends(current_user), db: Session = Depends(get_db)
):
    if not user.email_verified:
        token = create_action_token(db, user.id, "verify_email", minutes=24 * 60)
        verify_url = f"{get_settings().frontend_origin}/verify-email?token={token}"
        subject = "Verify your Radius email"
        text_body = f"Hello {user.name},\n\nPlease verify your email address by visiting:\n{verify_url}\n"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 500px; padding: 24px; border: 1px solid #e7ece8; border-radius: 8px;">
          <h2 style="color: #13231E;">Verify your Radius email</h2>
          <p style="color: #555;">Hello {_mail_name(user)},</p>
          <p style="color: #555;">Please verify your email address to secure your account.</p>
          <div style="margin: 24px 0;">
            <a href="{verify_url}" style="background-color: #19815C; color: #ffffff; padding: 12px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Verify Email Address</a>
          </div>
          <p style="color: #888; font-size: 12px;">Link:<br/><a href="{verify_url}">{verify_url}</a></p>
        </div>
        """
        send_email_message(user.email, subject, text_body, html_body)
    return {
        "message": "If your address is unverified, a verification link has been sent."
    }


def _log_label(value: str) -> str:
    """A provider label for log lines taken from our own table, never from the request string."""
    known = oauth.PROVIDERS.get(value)
    return known.name if known is not None else "unknown"


def oauth_config(provider: str) -> tuple[str, str, str]:
    """Return ``(client_id, client_secret, redirect_uri)`` or raise 503 when not configured.

    The redirect URI comes only from settings and must match the strict callback shape; it is
    never read from a request.
    """
    settings = get_settings()
    values = {
        "google": (
            settings.google_client_id,
            settings.google_client_secret,
            settings.google_redirect_uri,
        ),
        "github": (
            settings.github_client_id,
            settings.github_client_secret,
            settings.github_redirect_uri,
        ),
    }.get(provider)
    if values is None or not all(values):
        raise HTTPException(
            status_code=503, detail=f"{provider.title()} sign in is not configured."
        )
    client_id, client_secret, redirect_uri = values
    try:
        oauth.validate_redirect_uri(
            provider,
            str(redirect_uri),
            production=settings.runtime_env.strip().lower() == "production",
        )
    except oauth.OAuthError as exc:
        LOGGER.error("oauth provider=%s misconfigured: %s", _log_label(provider), exc.code)
        raise HTTPException(
            status_code=503, detail=f"{provider.title()} sign in is not configured."
        ) from exc
    return str(client_id), str(client_secret), str(redirect_uri)


def _redirect(location: str, status_code: int = status.HTTP_307_TEMPORARY_REDIRECT) -> RedirectResponse:
    redirect = RedirectResponse(location, status_code=status_code)
    redirect.headers["Cache-Control"] = "no-store"
    return redirect


@router.get("/oauth/{provider}")
def oauth_start(provider: str, next: str | None = None, db: Session = Depends(get_db)):
    oauth_provider = oauth.PROVIDERS.get(provider)
    if oauth_provider is None:
        raise HTTPException(
            status_code=404, detail="Authentication provider not found."
        )
    client_id, _, redirect_uri = oauth_config(provider)
    flow_id, state, nonce, verifier = oauth.start_flow(db, oauth_provider, next or "/")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": oauth_provider.scope,
        "state": state,
    }
    if oauth_provider.pkce:
        params["code_challenge"] = oauth.pkce_challenge(verifier)
        params["code_challenge_method"] = "S256"
    if oauth_provider.oidc:
        params["nonce"] = nonce
    redirect = _redirect(f"{oauth_provider.authorize_url}?{urlencode(params)}")
    redirect.set_cookie(
        oauth.FLOW_COOKIE,
        flow_id,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="lax",
        max_age=int(oauth.FLOW_TTL.total_seconds()),
        path=oauth.FLOW_COOKIE_PATH,
    )
    return redirect


def _login_error(code: str) -> RedirectResponse:
    redirect = _redirect(f"{get_settings().frontend_origin}/login?error={code}")
    redirect.delete_cookie(oauth.FLOW_COOKIE, path=oauth.FLOW_COOKIE_PATH)
    return redirect


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    radius_oauth_flow: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    oauth_provider = oauth.PROVIDERS.get(provider)
    if oauth_provider is None:
        raise HTTPException(
            status_code=404, detail="Authentication provider not found."
        )
    try:
        # The flow row is consumed first, so any failure below also burns this attempt.
        flow = oauth.consume_flow(db, provider, radius_oauth_flow, state)
        if error:
            raise oauth.OAuthError("provider_denied", public="oauth_denied")
        if not code:
            raise oauth.OAuthError("code_missing")
        client_id, client_secret, redirect_uri = oauth_config(provider)
        async with oauth.make_http_client() as client:
            token_body = await oauth.exchange_code(
                client,
                oauth_provider,
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                code=code,
                code_verifier=flow.code_verifier,
            )
            identity = await oauth.fetch_identity(
                client, oauth_provider, token_body, client_id=client_id, nonce=flow.nonce
            )
        user = user_from_provider(
            db,
            identity.provider,
            identity.subject,
            identity.email,
            identity.name,
            email_verified=True,  # fetch_identity only returns provider-verified emails
        )
        redirect = _redirect(
            f"{get_settings().frontend_origin}{oauth.sanitize_next(flow.next_path)}"
        )
        redirect.delete_cookie(oauth.FLOW_COOKIE, path=oauth.FLOW_COOKIE_PATH)
        set_session(redirect, db, user)
        LOGGER.info("oauth provider=%s outcome=success", _log_label(provider))
        return redirect
    except oauth.OAuthError as exc:
        # Log the failure class only: never codes, tokens, secrets or provider bodies.
        LOGGER.warning("oauth provider=%s outcome=failure reason=%s", _log_label(provider), exc.code)
        return _login_error(exc.public)
    except HTTPException as exc:
        LOGGER.warning(
            "oauth provider=%s outcome=failure reason=http_%s", _log_label(provider), exc.status_code
        )
        return _login_error("oauth")
    except Exception as exc:
        LOGGER.warning(
            "oauth provider=%s outcome=failure reason=unexpected:%s",
            _log_label(provider),
            type(exc).__name__,
        )
        return _login_error("oauth")
