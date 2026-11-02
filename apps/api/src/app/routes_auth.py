"""HTTP boundary for Radius authentication. Sessions are HTTP-only cookies."""

import secrets
import smtplib
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import (
    consume_action_token,
    create_action_token,
    create_session,
    decode_session,
    hash_password,
    provision_domain_user_and_org,
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

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
SESSION_COOKIE = "radius_session"
OAUTH_STATE_COOKIE = "radius_oauth_state"


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
    print(
        f"\n[Radius Email Dispatch] FROM: {sender} -> TO: {to_email}\nSubject: {subject}\n"
    )
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
            print(f"[Radius SMTP Success] Email successfully delivered to {to_email}")
            return True
        except Exception as exc:
            print(f"[Radius SMTP Error] Failed to send email to {to_email}: {exc}")
            return False
    else:
        print(
            "[Radius SMTP Note] SMTP_USERNAME and SMTP_PASSWORD not set in environment. Falling back to console log."
        )
        return False


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
    user_id, session_id = decode_session(radius_session)
    session = db.get(AuthSession, session_id)
    user = db.get(User, user_id)
    now = datetime.now(UTC)
    expires_at = session.expires_at if session.expires_at.tzinfo is not None else session.expires_at.replace(tzinfo=UTC)
    if (
        not user
        or not session
        or session.user_id != user.id
        or session.revoked_at is not None
        or expires_at < now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Please sign in again.",
        )
    return user


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
    provision_domain_user_and_org(db, user)
    db.refresh(user)
    token = create_action_token(db, user.id, "verify_email", minutes=24 * 60)
    verify_url = f"{get_settings().frontend_origin}/verify-email?token={token}"
    subject = "Verify your Radius account"
    text_body = f"Hello {user.name},\n\nThank you for signing up for Radius.\n\nPlease verify your email address by visiting:\n{verify_url}\n"
    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px; padding: 24px; border: 1px solid #e7ece8; border-radius: 8px;">
      <h2 style="color: #13231E;">Welcome to Radius</h2>
      <p style="color: #555;">Hello {user.name},</p>
      <p style="color: #555;">Please verify your email address to secure your account.</p>
      <div style="margin: 24px 0;">
        <a href="{verify_url}" style="background-color: #19815C; color: #ffffff; padding: 12px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Verify Email Address</a>
      </div>
      <p style="color: #888; font-size: 12px;">Or copy and paste this link into your browser:<br/><a href="{verify_url}">{verify_url}</a></p>
    </div>
    """
    send_email_message(user.email, subject, text_body, html_body)
    set_session(response, db, user)
    return public_user(user)


@router.post("/login", response_model=UserResponse)
def login(payload: Login, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if (
        not user
        or not user.password_hash
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=401,
            detail="Unable to sign in. Please check your credentials and try again.",
        )
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
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    set_session(response, db, user)
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
        Hello {user.name}, we received a request to reset your password for your Radius account.
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
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/verify-email", response_model=UserResponse)
def verify_email(payload: VerifyToken, db: Session = Depends(get_db)):
    user = consume_action_token(db, payload.token, "verify_email")
    user.email_verified = True
    db.commit()
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
          <p style="color: #555;">Hello {user.name},</p>
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


def oauth_config(provider: str) -> tuple[str, str, str, str, str, str]:
    settings = get_settings()
    if (
        provider == "google"
        and settings.google_client_id
        and settings.google_client_secret
        and settings.google_redirect_uri
    ):
        return (
            settings.google_client_id,
            settings.google_client_secret,
            settings.google_redirect_uri,
            "https://accounts.google.com/o/oauth2/v2/auth",
            "https://oauth2.googleapis.com/token",
            "https://openidconnect.googleapis.com/v1/userinfo",
        )
    if (
        provider == "github"
        and settings.github_client_id
        and settings.github_client_secret
        and settings.github_redirect_uri
    ):
        return (
            settings.github_client_id,
            settings.github_client_secret,
            settings.github_redirect_uri,
            "https://github.com/login/oauth/authorize",
            "https://github.com/login/oauth/access_token",
            "https://api.github.com/user",
        )
    raise HTTPException(
        status_code=503, detail=f"{provider.title()} sign in is not configured."
    )


@router.get("/oauth/{provider}")
def oauth_start(provider: str, response: Response):
    if provider not in {"google", "github"}:
        raise HTTPException(
            status_code=404, detail="Authentication provider not found."
        )
    client_id, _, callback, authorization_url, _, _ = oauth_config(provider)
    nonce = secrets.token_urlsafe(24)
    state = jwt.encode(
        {
            "provider": provider,
            "nonce": nonce,
            "exp": datetime.now(UTC) + timedelta(minutes=10),
        },
        get_settings().session_secret,
        algorithm="HS256",
    )
    params = {
        "client_id": client_id,
        "redirect_uri": callback,
        "response_type": "code",
        "state": state,
    }
    if provider == "google":
        params.update({"scope": "openid email profile", "nonce": nonce})
    else:
        params.update({"scope": "read:user user:email"})
    response.status_code = status.HTTP_307_TEMPORARY_REDIRECT
    response.headers["Location"] = f"{authorization_url}?{urlencode(params)}"
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        nonce,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return response


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    response: Response,
    radius_oauth_state: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    try:
        saved = jwt.decode(state, get_settings().session_secret, algorithms=["HS256"])
        if (
            saved.get("provider") != provider
            or not radius_oauth_state
            or not secrets.compare_digest(saved["nonce"], radius_oauth_state)
        ):
            raise ValueError("Invalid OAuth state")
        client_id, client_secret, callback, _, token_url, profile_url = oauth_config(
            provider
        )
        async with httpx.AsyncClient(timeout=10) as client:
            token_response = await client.post(
                token_url,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": callback,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]
            profile = (
                await client.get(
                    profile_url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                )
            ).json()
            if provider == "github" and not profile.get("email"):
                emails = (
                    await client.get(
                        "https://api.github.com/user/emails",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Accept": "application/json",
                        },
                    )
                ).json()
                profile["email"] = next(
                    (
                        item["email"]
                        for item in emails
                        if item.get("primary") and item.get("verified")
                    ),
                    None,
                )
        provider_id = str(
            profile.get("sub") if provider == "google" else profile.get("id")
        )
        email = profile.get("email")
        if not provider_id or not email:
            raise ValueError("Provider did not supply a verified identity")
        user = user_from_provider(
            db,
            provider,
            provider_id,
            email,
            profile.get("name") or profile.get("login") or email,
        )
        set_session(response, db, user)
        response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
        response.status_code = status.HTTP_307_TEMPORARY_REDIRECT
        response.headers["Location"] = f"{get_settings().frontend_origin}/"
        return response
    except Exception:
        response.delete_cookie(OAUTH_STATE_COOKIE, path="/")
        response.status_code = status.HTTP_307_TEMPORARY_REDIRECT
        response.headers["Location"] = (
            f"{get_settings().frontend_origin}/login?error=oauth"
        )
        return response
