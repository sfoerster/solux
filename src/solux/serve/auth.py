from __future__ import annotations

import logging
import threading
import time
from importlib import import_module
from typing import Any

_JWKS_TTL_SECONDS = 3600  # Refresh JWKS at most once per hour
_DEFAULT_ALLOWED_JWT_ALGORITHMS = (
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
)

logger = logging.getLogger(__name__)


class OIDCValidator:
    """Validates OIDC JWT tokens using JWKS from the issuer."""

    def __init__(
        self,
        issuer: str,
        audience: str,
        allowed_algorithms: tuple[str, ...] | None = None,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.allowed_algorithms = tuple(allowed_algorithms or _DEFAULT_ALLOWED_JWT_ALGORITHMS)
        self._jwks_client: Any | None = None
        self._jwks_client_built_at: float = 0.0
        self._lock = threading.Lock()
        self._jwks_url = f"{self.issuer}/.well-known/jwks.json"

    def _build_jwks_client(self) -> Any:
        jwt_mod = import_module("jwt")
        jwks_client_type = getattr(jwt_mod, "PyJWKClient", None)
        if jwks_client_type is None:
            raise RuntimeError("OIDCValidator: jwt.PyJWKClient is unavailable")
        return jwks_client_type(self._jwks_url, cache_keys=True)

    def _get_jwks_client(self) -> Any:
        with self._lock:
            now = time.monotonic()
            if self._jwks_client is None or (now - self._jwks_client_built_at) >= _JWKS_TTL_SECONDS:
                self._jwks_client = self._build_jwks_client()
                self._jwks_client_built_at = now
            return self._jwks_client

    def _refresh_jwks_client(self) -> Any:
        with self._lock:
            self._jwks_client = self._build_jwks_client()
            self._jwks_client_built_at = time.monotonic()
            return self._jwks_client

    def validate(self, token: str) -> dict[str, Any] | None:
        """Validate a Bearer JWT token. Returns claims dict or None on failure."""
        try:
            jwt_mod = import_module("jwt")
        except ImportError:
            logger.warning("OIDCValidator: PyJWT not installed; skipping token validation — install 'solux[oidc]'")
            return None

        for attempt in range(2):
            try:
                jwks_client = self._get_jwks_client() if attempt == 0 else self._refresh_jwks_client()
                signing_key = jwks_client.get_signing_key_from_jwt(token)
                decode_fn = getattr(jwt_mod, "decode", None)
                if not callable(decode_fn):
                    logger.debug("OIDCValidator: jwt.decode is unavailable")
                    return None
                claims_raw = decode_fn(
                    token,
                    signing_key.key,
                    algorithms=list(self.allowed_algorithms),
                    audience=self.audience or None,
                    issuer=self.issuer or None,
                    options={"verify_exp": True},
                )
                if isinstance(claims_raw, dict):
                    return {str(key): value for key, value in claims_raw.items()}
                return None
            except Exception as exc:
                if attempt == 0:
                    logger.debug("OIDCValidator: token validation failed once; retrying with refreshed JWKS: %s", exc)
                    continue
                logger.debug("OIDCValidator: token validation failed: %s", exc)
                return None
        return None


# Module-level singleton cache
_validators: dict[str, OIDCValidator] = {}
_validator_lock = threading.Lock()


def get_validator(
    issuer: str,
    audience: str,
    allowed_algorithms: tuple[str, ...] | None = None,
) -> OIDCValidator:
    effective_algorithms = tuple(allowed_algorithms or _DEFAULT_ALLOWED_JWT_ALGORITHMS)
    key = f"{issuer}:{audience}:{','.join(effective_algorithms)}"
    with _validator_lock:
        if key not in _validators:
            _validators[key] = OIDCValidator(
                issuer,
                audience,
                allowed_algorithms=effective_algorithms,
            )
    return _validators[key]
