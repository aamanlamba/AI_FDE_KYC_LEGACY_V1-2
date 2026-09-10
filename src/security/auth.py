"""Authentication/authorization abstraction.

Authorizer is the interface a real deployment would implement against its own
identity provider (OAuth2/OIDC, mTLS, an internal SSO gateway, ...) without changing
any caller of require_role() below. StaticWorkshopAuthorizer is the only
implementation in this repository: a deterministic, offline, config-driven static
credential set -- appropriate for a locally-runnable training service, explicitly NOT
appropriate for a real deployment (see config/security.json).
"""

from abc import ABC, abstractmethod
from pathlib import Path
import json
import os

from pydantic import BaseModel

from .errors import AuthenticationError, AuthorizationError

_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _ROOT / "config" / "security.json"

ROLE_REVIEWER = "reviewer"


class AuthPrincipal(BaseModel):
    subject: str
    roles: frozenset[str]


class Authorizer(ABC):
    @abstractmethod
    def authenticate(self, credential: str | None) -> AuthPrincipal | None:
        """Returns a principal for a valid credential, or None if the credential is
        missing/invalid. Never raises for a bad credential -- callers decide what an
        absent principal means (require_role turns it into AuthenticationError)."""
        raise NotImplementedError


def _load_workshop_credentials() -> dict[str, frozenset[str]]:
    """config/security.json provides the default (clearly labeled as workshop-only,
    not a real secret). The REVIEWER_API_KEYS environment variable, if set, is a
    comma-separated list that REPLACES the config default entirely -- the intended
    override point for any real deployment, so a credential never has to be committed
    to get a different value in a given environment (secrets/configuration hygiene)."""
    env_override = os.environ.get("REVIEWER_API_KEYS")
    if env_override:
        return {key.strip(): frozenset({ROLE_REVIEWER}) for key in env_override.split(",") if key.strip()}
    try:
        config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {key: frozenset({ROLE_REVIEWER}) for key in config.get("reviewer_api_keys", [])}


class StaticWorkshopAuthorizer(Authorizer):
    name = "static_workshop_authorizer"

    def __init__(self, credentials: dict[str, frozenset[str]] | None = None):
        self._credentials = credentials if credentials is not None else _load_workshop_credentials()

    def authenticate(self, credential: str | None) -> AuthPrincipal | None:
        if not credential:
            return None
        roles = self._credentials.get(credential)
        if roles is None:
            return None
        return AuthPrincipal(subject="workshop-reviewer", roles=roles)


_default_authorizer: Authorizer | None = None


def get_default_authorizer() -> Authorizer:
    global _default_authorizer
    if _default_authorizer is None:
        _default_authorizer = StaticWorkshopAuthorizer()
    return _default_authorizer


def authorize(credential: str | None, role: str, authorizer: Authorizer | None = None) -> AuthPrincipal:
    """Raises AuthenticationError (no/invalid credential) or AuthorizationError
    (valid credential, missing role); returns the principal on success."""
    principal = (authorizer or get_default_authorizer()).authenticate(credential)
    if principal is None:
        raise AuthenticationError("missing or invalid credential")
    if role not in principal.roles:
        raise AuthorizationError(f"credential lacks required role '{role}'")
    return principal
