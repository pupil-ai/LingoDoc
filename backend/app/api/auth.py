import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import jwt
from fastapi import Header, HTTPException, status
from jwt import PyJWKClient

from app.services.translate_service import safe_print


@dataclass(frozen=True)
class CurrentUser:
    id: str
    claims: Dict[str, Any]


_jwks_client: Optional[PyJWKClient] = None


def _get_clerk_issuer() -> str:
    issuer = os.getenv("CLERK_ISSUER_URL", "").strip().rstrip("/")
    if not issuer:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Clerk is not configured. Set CLERK_ISSUER_URL in backend/.env.",
        )
    return issuer


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client

    if _jwks_client is None:
        issuer = _get_clerk_issuer()
        jwks_url = os.getenv("CLERK_JWKS_URL", "").strip() or f"{issuer}/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url)

    return _jwks_client


def _get_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header",
        )

    return token


def _describe_token_for_log(token: str) -> str:
    try:
        header = jwt.get_unverified_header(token)
        claims = jwt.decode(token, options={"verify_signature": False})
        now = int(datetime.now(timezone.utc).timestamp())
        return (
            f"alg={header.get('alg')} kid={header.get('kid')} "
            f"iss={claims.get('iss')} aud={claims.get('aud')} "
            f"sub_present={bool(claims.get('sub'))} "
            f"exp={claims.get('exp')} nbf={claims.get('nbf')} iat={claims.get('iat')} now={now}"
        )
    except Exception as exc:
        return f"failed_to_decode_unverified_token={type(exc).__name__}: {str(exc)}"


async def get_current_user(authorization: Optional[str] = Header(default=None)) -> CurrentUser:
    token = _get_bearer_token(authorization)
    issuer = _get_clerk_issuer()
    audience = os.getenv("CLERK_JWT_AUDIENCE", "").strip()

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        decode_kwargs: Dict[str, Any] = {
            "key": signing_key.key,
            "algorithms": ["RS256"],
            "issuer": issuer,
            "options": {"verify_aud": bool(audience)},
            "leeway": 60,
        }
        if audience:
            decode_kwargs["audience"] = audience

        claims = jwt.decode(token, **decode_kwargs)
    except Exception as exc:
        safe_print(
            "[AUTH] Clerk token verification failed: "
            f"{type(exc).__name__}: {str(exc)}; "
            f"configured_issuer={issuer}; configured_audience={audience or '<none>'}; "
            f"{_describe_token_for_log(token)}"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired auth token",
        )

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Auth token is missing subject",
        )

    return CurrentUser(id=user_id, claims=claims)
