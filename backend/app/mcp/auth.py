"""Vérification des jetons d'API personnels pour le serveur MCP."""

import anyio
from fastmcp.server.auth import AccessToken, TokenVerifier

from app.api.services.api_tokens import authenticate_api_token
from app.core.db import SessionLocal
from app.mcp.oauth import ALL_SCOPES


class ApiTokenVerifier(TokenVerifier):
    """Bearer `cat_…` → utilisateur CatalogAI (jeton actif, utilisateur actif).

    Les droits (modules, scoping, crédits) ne sont PAS décidés ici : chaque
    outil les revérifie à l'appel via `app.mcp.guard`.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        def lookup() -> AccessToken | None:
            with SessionLocal() as db:
                found = authenticate_api_token(db, token)
                if found is None:
                    return None
                api_token, user = found
                expires_at = api_token.expires_at
                return AccessToken(
                    token=token,
                    client_id=f"user:{user.id}",
                    scopes=list(ALL_SCOPES),
                    expires_at=int(expires_at.timestamp()) if expires_at else None,
                    claims={"user_id": user.id, "token_id": api_token.id},
                )

        return await anyio.to_thread.run_sync(lookup)
