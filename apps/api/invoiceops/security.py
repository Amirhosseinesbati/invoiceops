import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Cookie, Depends, Header, HTTPException, status
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from invoiceops.config import get_settings
from invoiceops.db import get_db
from invoiceops.models import User, UserSession, as_utc, now

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored: str) -> bool:
    return password_hash.verify(password, stored)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(40)
    db.add(
        UserSession(
            token_hash=token_digest(token), user_id=user.id, expires_at=now() + timedelta(hours=12)
        )
    )
    db.commit()
    return token


def current_user(
    session_token: str | None = Cookie(default=None), db: Session = Depends(get_db)
) -> User:
    if not session_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    session = db.get(UserSession, token_digest(session_token))
    if session is None or as_utc(session.expires_at) < now():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = db.get(User, session.user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account unavailable")
    return user


def operator(user: User = Depends(current_user)) -> User:
    if user.role not in {"operator", "manager", "admin"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Operator role required")
    return user


def internal_auth(x_internal_token: str | None = Header(default=None)) -> None:
    expected = get_settings().internal_token
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Internal authentication required")


def require_same_workspace(record_workspace_id: str, user: User) -> None:
    if record_workspace_id != user.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
