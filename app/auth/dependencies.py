"""FastAPI authentication and database dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.oidc import TokenClaims, TokenVerifier
from app.core.errors import (
    AccountDeletionPendingError,
    AuthNotConfiguredError,
    DatabaseNotConfiguredError,
    ForbiddenError,
    UnauthorizedError,
)
from app.db.models import User, UserRole
from app.services.audit import record_audit

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="OIDCBearer",
    description="OIDC access token dari provider identitas.",
)

_BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class Principal:
    user: User
    roles: List[str]
    claims: TokenClaims


def get_db_session(request: Request) -> Iterator[Session]:
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        raise DatabaseNotConfiguredError()
    session: Session = factory()
    try:
        yield session
    finally:
        session.close()


def get_token_verifier(request: Request) -> TokenVerifier:
    verifier = getattr(request.app.state, "token_verifier", None)
    if verifier is None:
        raise AuthNotConfiguredError()
    return verifier


def _ensure_default_role(session: Session, user_id) -> None:
    existing = session.scalar(
        select(UserRole.id).where(
            UserRole.user_id == user_id,
            UserRole.role == "user",
            UserRole.org_id.is_(None),
        )
    )
    if existing is not None:
        return
    try:
        with session.begin_nested():
            session.add(UserRole(user_id=user_id, role="user"))
            session.flush()
    except IntegrityError:
        # Another concurrent first request created the role first.
        return


def _get_or_create_user(session: Session, claims: TokenClaims) -> Tuple[User, bool]:
    identity = (
        User.auth_issuer == claims.issuer,
        User.auth_subject == claims.subject,
    )
    user = session.scalar(select(User).where(*identity))
    if user is not None:
        if user.deleted_at is not None or user.deletion_requested_at is not None:
            return user, False
        changed = False
        if claims.email and user.email != claims.email:
            user.email = claims.email
            changed = True
        if user.display_name is None and claims.display_name:
            user.display_name = claims.display_name
            changed = True
        if changed:
            session.commit()
        return user, False

    user = User(
        auth_issuer=claims.issuer,
        auth_subject=claims.subject,
        email=claims.email,
        display_name=claims.display_name,
    )
    try:
        with session.begin_nested():
            session.add(user)
            session.flush()
    except IntegrityError:
        if user in session:
            session.expunge(user)
        existing = session.scalar(select(User).where(*identity))
        if existing is None:
            raise
        return existing, False

    _ensure_default_role(session, user.id)
    record_audit(
        session,
        actor_user_id=user.id,
        actor_role="user",
        action="auth.first_login",
        resource_type="user",
        resource_id=str(user.id),
        metadata={"issuer": claims.issuer},
    )
    session.commit()
    return user, True


def get_current_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    verifier: TokenVerifier = Depends(get_token_verifier),
    session: Session = Depends(get_db_session),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError("Token akses tidak dikirim.", headers=_BEARER_CHALLENGE)

    claims = verifier.verify(credentials.credentials)
    user, _ = _get_or_create_user(session, claims)

    if user.deleted_at is not None:
        raise ForbiddenError("Akun sudah dihapus.")
    if user.deletion_requested_at is not None:
        raise AccountDeletionPendingError()

    roles = list(
        session.scalars(
            select(UserRole.role).where(UserRole.user_id == user.id).distinct()
        ).all()
    )
    if not roles:
        _ensure_default_role(session, user.id)
        session.commit()
        roles = ["user"]

    return Principal(user=user, roles=sorted(roles), claims=claims)


def require_platform_admin(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    if "platform_admin" not in principal.roles:
        raise ForbiddenError("Akses platform admin diperlukan.")
    return principal


def require_trainer(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    if "trainer" not in principal.roles and "platform_admin" not in principal.roles:
        raise ForbiddenError("Akses trainer diperlukan.")
    return principal
