class SecurityError(RuntimeError):
    """Base class for security-boundary failures."""


class AuthenticationError(SecurityError):
    """No valid credential was presented."""


class AuthorizationError(SecurityError):
    """A valid credential was presented but lacks the required role."""


class RateLimitExceededError(SecurityError):
    """The caller has exceeded the configured request rate for this operation."""
