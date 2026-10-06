"""Serveur d'autorisation OAuth 2.1 du MCP (connecteur claude.ai, Codex).

Parcours : le client s'enregistre (DCR, RFC 7591) → `/authorize` crée une
demande et renvoie vers la page de consentement de l'app
(`/oauth/consent?request=…`, session de l'utilisateur) → « Autoriser » émet un
code à usage unique (5 min) → `/token` l'échange (PKCE S256 vérifié par le SDK)
contre un jeton d'accès (1 h) et un jeton de rafraîchissement (30 j, rotation).
Tout est en base (plusieurs workers) et seuls les hachages sont stockés.

Scopes : `catalogai:read` (lecture) et `catalogai:write` (lancer, valider,
appliquer, transférer) — revérifiés par chaque outil via la garde commune.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
from fastmcp.server.auth import AccessToken, OAuthProvider
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import OAuthAuthorization, OAuthClient, User
from app.models import OAuthToken as OAuthTokenRow

SCOPE_READ = "catalogai:read"
SCOPE_WRITE = "catalogai:write"
ALL_SCOPES = [SCOPE_READ, SCOPE_WRITE]

REQUEST_TTL = timedelta(minutes=10)
CODE_TTL = timedelta(minutes=5)
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    # SQLite (tests) relit les dates sans fuseau : on les suppose en UTC.
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _ts(value: datetime | None) -> int | None:
    aware = _aware(value)
    return int(aware.timestamp()) if aware else None


def _alive(expires_at: datetime | None, now: datetime) -> bool:
    aware = _aware(expires_at)
    return aware is None or aware > now


def consent_url(request_key: str) -> str:
    return f"{settings.PUBLIC_APP_URL}/oauth/consent?request={request_key}"


# --- Consentement (appelé par les routes /oauth/requests, session utilisateur) --


def pending_authorization(db: Session, request_key: str) -> OAuthAuthorization | None:
    row = db.scalar(
        select(OAuthAuthorization).where(OAuthAuthorization.request_key == request_key)
    )
    if (
        row is None
        or row.used_at is not None
        or row.user_id is not None
        or not _alive(row.expires_at, _now())
    ):
        return None
    return row


def client_name(db: Session, client_id: str) -> str:
    client = db.get(OAuthClient, client_id)
    name = (client.metadata_json or {}).get("client_name") if client else None
    return str(name or "Application MCP")


def approve_authorization(db: Session, row: OAuthAuthorization, user: User) -> str:
    """Émet le code pour `user` ; renvoie l'URL de retour du client."""
    code = secrets.token_urlsafe(32)
    row.user_id = user.id
    row.code_hash = _hash(code)
    row.expires_at = _now() + CODE_TTL
    db.commit()
    return construct_redirect_uri(row.redirect_uri, code=code, state=row.state)


def deny_authorization(db: Session, row: OAuthAuthorization) -> str:
    row.used_at = _now()
    db.commit()
    return construct_redirect_uri(
        row.redirect_uri, error="access_denied", state=row.state
    )


# --- Fournisseur OAuth (endpoints /register, /authorize, /token, /revoke) ------


class CatalogOAuthProvider(OAuthProvider):
    def __init__(self) -> None:
        super().__init__(
            base_url=settings.PUBLIC_API_URL,
            service_documentation_url="https://catalog.tillin.fr",
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=ALL_SCOPES, default_scopes=ALL_SCOPES
            ),
            revocation_options=RevocationOptions(enabled=True),
        )

    # Les accès base sont synchrones : chaque méthode passe par un thread.
    @staticmethod
    async def _run(fn: Any, *args: Any) -> Any:
        def call() -> Any:
            with SessionLocal() as db:
                return fn(db, *args)

        return await anyio.to_thread.run_sync(call)

    # Clients ---------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        def load(db: Session) -> OAuthClientInformationFull | None:
            row = db.get(OAuthClient, client_id)
            if row is None:
                return None
            return OAuthClientInformationFull.model_validate(row.metadata_json)

        result: OAuthClientInformationFull | None = await self._run(load)
        return result

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.client_id is None:
            raise ValueError("client_id is required for client registration")
        requested = set((client_info.scope or "").split())
        if requested - set(ALL_SCOPES):
            raise ValueError("Requested scopes are not valid")

        def save(db: Session) -> None:
            row = db.get(OAuthClient, client_info.client_id)
            payload = client_info.model_dump(mode="json")
            if row is None:
                db.add(
                    OAuthClient(client_id=client_info.client_id, metadata_json=payload)
                )
            else:
                row.metadata_json = payload
            db.commit()

        await self._run(save)

    # Autorisation ------------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if client.client_id is None:
            raise AuthorizeError(
                error="invalid_request", error_description="Client ID is required"
            )
        scopes = [s for s in (params.scopes or ALL_SCOPES) if s in ALL_SCOPES]
        if not scopes:
            raise AuthorizeError(
                error="invalid_scope", error_description="No valid scope requested"
            )
        request_key = secrets.token_urlsafe(32)

        def create(db: Session) -> None:
            db.add(
                OAuthAuthorization(
                    request_key=request_key,
                    client_id=client.client_id,
                    redirect_uri=str(params.redirect_uri),
                    redirect_uri_explicit=params.redirect_uri_provided_explicitly,
                    scopes_json=scopes,
                    state=params.state,
                    code_challenge=params.code_challenge,
                    resource=params.resource,
                    expires_at=_now() + REQUEST_TTL,
                )
            )
            db.commit()

        await self._run(create)
        return consent_url(request_key)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        def load(db: Session) -> AuthorizationCode | None:
            row = db.scalar(
                select(OAuthAuthorization).where(
                    OAuthAuthorization.code_hash == _hash(authorization_code)
                )
            )
            if (
                row is None
                or row.client_id != client.client_id
                or row.used_at is not None
                or row.user_id is None
                or not _alive(row.expires_at, _now())
            ):
                return None
            return AuthorizationCode(
                code=authorization_code,
                scopes=list(row.scopes_json or []),
                expires_at=float(_ts(row.expires_at) or 0),
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=AnyUrl(row.redirect_uri),
                redirect_uri_provided_explicitly=row.redirect_uri_explicit,
                resource=row.resource,
                subject=str(row.user_id),
            )

        result: AuthorizationCode | None = await self._run(load)
        return result

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        def exchange(db: Session) -> OAuthToken:
            # Consommation atomique : un code ne s'échange qu'une fois, même si
            # deux workers reçoivent la requête en même temps.
            consumed = db.execute(
                update(OAuthAuthorization)
                .where(
                    OAuthAuthorization.code_hash == _hash(authorization_code.code),
                    OAuthAuthorization.used_at.is_(None),
                )
                .values(used_at=_now())
            )
            if consumed.rowcount != 1:  # type: ignore[attr-defined]
                db.rollback()
                raise TokenError("invalid_grant", "Authorization code already used")
            return self._issue(
                db,
                client_id=str(client.client_id),
                user_id=int(authorization_code.subject or 0),
                scopes=authorization_code.scopes,
                resource=authorization_code.resource,
            )

        result: OAuthToken = await self._run(exchange)
        return result

    # Jetons ------------------------------------------------------------------

    @staticmethod
    def _issue(
        db: Session,
        *,
        client_id: str,
        user_id: int,
        scopes: list[str],
        resource: str | None,
    ) -> OAuthToken:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            db.rollback()
            raise TokenError("invalid_grant", "User is not active")
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        family = secrets.token_hex(16)
        now = _now()
        for value, kind, ttl in (
            (access, "access", ACCESS_TTL),
            (refresh, "refresh", REFRESH_TTL),
        ):
            db.add(
                OAuthTokenRow(
                    token_hash=_hash(value),
                    kind=kind,
                    family=family,
                    client_id=client_id,
                    user_id=user_id,
                    scopes_json=scopes,
                    resource=resource,
                    expires_at=now + ttl,
                )
            )
        db.commit()
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=int(ACCESS_TTL.total_seconds()),
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    @staticmethod
    def _active_row(db: Session, token: str, kind: str) -> OAuthTokenRow | None:
        row = db.scalar(
            select(OAuthTokenRow).where(OAuthTokenRow.token_hash == _hash(token))
        )
        if (
            row is None
            or row.kind != kind
            or row.revoked_at is not None
            or not _alive(row.expires_at, _now())
        ):
            return None
        return row

    @staticmethod
    def _revoke_family(db: Session, family: str) -> None:
        db.execute(
            update(OAuthTokenRow)
            .where(OAuthTokenRow.family == family, OAuthTokenRow.revoked_at.is_(None))
            .values(revoked_at=_now())
        )
        db.commit()

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        def load(db: Session) -> RefreshToken | None:
            row = self._active_row(db, refresh_token, "refresh")
            if row is None or row.client_id != client.client_id:
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=row.client_id,
                scopes=list(row.scopes_json or []),
                expires_at=_ts(row.expires_at),
                resource=row.resource,
                subject=str(row.user_id),
            )

        result: RefreshToken | None = await self._run(load)
        return result

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        granted = scopes or refresh_token.scopes
        if not set(granted) <= set(refresh_token.scopes):
            raise TokenError("invalid_scope", "Requested scopes exceed the grant")

        def exchange(db: Session) -> OAuthToken:
            row = self._active_row(db, refresh_token.token, "refresh")
            if row is None:
                raise TokenError("invalid_grant", "Refresh token is not active")
            # Rotation : l'ancienne famille (accès + rafraîchissement) tombe.
            self._revoke_family(db, row.family)
            return self._issue(
                db,
                client_id=str(client.client_id),
                user_id=row.user_id,
                scopes=list(granted),
                resource=row.resource,
            )

        result: OAuthToken = await self._run(exchange)
        return result

    async def load_access_token(self, token: str) -> AccessToken | None:
        def load(db: Session) -> AccessToken | None:
            row = self._active_row(db, token, "access")
            if row is None:
                return None
            user = db.get(User, row.user_id)
            if user is None or not user.is_active:
                return None
            return AccessToken(
                token=token,
                client_id=row.client_id,
                scopes=list(row.scopes_json or []),
                expires_at=_ts(row.expires_at),
                resource=row.resource,
                claims={"user_id": row.user_id, "oauth_client": row.client_id},
            )

        result: AccessToken | None = await self._run(load)
        return result

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        def revoke(db: Session) -> None:
            row = db.scalar(
                select(OAuthTokenRow).where(
                    OAuthTokenRow.token_hash == _hash(token.token)
                )
            )
            if row is not None:
                self._revoke_family(db, row.family)

        await self._run(revoke)
