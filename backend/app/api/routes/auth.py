from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import record_audit, request_ip
from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import check_rate_limit, login_rate_limit_key
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models import TokenTransaction, User, UserRole, UserSession
from app.schemas import TokenOut, UserCreate, UserLogin


router = APIRouter()
settings = get_settings()


def validate_registration_policy(email: str, db: Session) -> UserRole:
    existing_users = db.scalar(select(User.id).limit(1))
    if not settings.allow_registration and existing_users:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Registration is disabled")

    domains = [domain.lower().lstrip("@") for domain in settings.registration_email_domains]
    if domains and email.split("@")[-1].lower() not in domains:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email domain is not allowed")

    if settings.first_superuser_email and email.lower() == settings.first_superuser_email.lower():
        return UserRole.admin
    if not existing_users and settings.environment != "production":
        return UserRole.admin
    return UserRole.member


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.refresh_cookie_name,
        token,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.environment == "production",
        samesite="lax",
        path=f"{settings.api_prefix}/auth",
    )


def issue_session(db: Session, user: User, request: Request, response: Response) -> TokenOut:
    refresh_token = create_refresh_token()
    db.add(
        UserSession(
            id=str(uuid4()),
            user_id=user.id,
            refresh_token_hash=hash_refresh_token(refresh_token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
            ip_address=request_ip(request),
            user_agent=request.headers.get("user-agent", "")[:300],
        )
    )
    set_refresh_cookie(response, refresh_token)
    return TokenOut(
        access_token=create_access_token(str(user.id)),
        expires_in=settings.access_token_expire_minutes * 60,
        user=user,
    )


def normalize_datetime(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.post("/register", response_model=TokenOut)
def register(payload: UserCreate, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    role = validate_registration_policy(payload.email, db)
    user = User(
        email=payload.email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=role,
        permissions="agents:read,projects:write,knowledge:write",
        ai_token_balance=settings.welcome_ai_tokens,
    )
    db.add(user)
    db.flush()
    if settings.welcome_ai_tokens:
        db.add(
            TokenTransaction(
                user_id=user.id,
                amount=settings.welcome_ai_tokens,
                balance_after=settings.welcome_ai_tokens,
                transaction_type="WELCOME",
                idempotency_key=f"welcome:{user.id}",
                description="新用户赠送",
            )
        )
    token = issue_session(db, user, request, response)
    record_audit(db, "auth.register", user_id=user.id, resource_type="user", resource_id=user.id, request=request)
    db.commit()
    db.refresh(user)
    return token


@router.post("/login", response_model=TokenOut)
def login(payload: UserLogin, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    check_rate_limit(login_rate_limit_key(request, payload.email))
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        record_audit(
            db,
            "auth.login_failed",
            user_id=user.id if user else None,
            resource_type="user",
            resource_id=user.id if user else "",
            details={"email": payload.email, "reason": "invalid_credentials"},
            request=request,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        record_audit(db, "auth.login_failed", user_id=user.id, resource_type="user", resource_id=user.id, details={"reason": "disabled"}, request=request)
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is disabled")
    token = issue_session(db, user, request, response)
    record_audit(db, "auth.login", user_id=user.id, resource_type="user", resource_id=user.id, request=request)
    db.commit()
    return token


@router.post("/refresh", response_model=TokenOut)
def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=settings.refresh_cookie_name),
    db: Session = Depends(get_db),
) -> TokenOut:
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh session is missing")
    session = db.scalar(select(UserSession).where(UserSession.refresh_token_hash == hash_refresh_token(refresh_token)))
    now = datetime.now(timezone.utc)
    if not session or session.revoked_at or normalize_datetime(session.expires_at) <= now:
        response.delete_cookie(settings.refresh_cookie_name, path=f"{settings.api_prefix}/auth")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh session is invalid")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User session is unavailable")
    session.revoked_at = now
    token = issue_session(db, user, request, response)
    record_audit(db, "auth.refresh", user.id, resource_type="session", resource_id=session.id, request=request)
    db.commit()
    return token


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=settings.refresh_cookie_name),
    db: Session = Depends(get_db),
) -> Response:
    if refresh_token:
        session = db.scalar(select(UserSession).where(UserSession.refresh_token_hash == hash_refresh_token(refresh_token)))
        if session and not session.revoked_at:
            session.revoked_at = datetime.now(timezone.utc)
            record_audit(db, "auth.logout", session.user_id, resource_type="session", resource_id=session.id, request=request)
            db.commit()
    response.delete_cookie(settings.refresh_cookie_name, path=f"{settings.api_prefix}/auth")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
