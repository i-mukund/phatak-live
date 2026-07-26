"""Typed application errors mapped to HTTP responses in ``main.py``."""

from __future__ import annotations


class PhatakError(Exception):
    """Base class. Every error we raise deliberately derives from this."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, detail: object | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotFoundError(PhatakError):
    status_code = 404
    code = "not_found"


class ValidationError(PhatakError):
    status_code = 422
    code = "validation_error"


class UnauthorizedError(PhatakError):
    status_code = 401
    code = "unauthorized"


class ProviderError(PhatakError):
    """A provider failed. Never fatal — the chain handles it."""

    status_code = 502
    code = "provider_error"

    def __init__(self, provider: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.retryable = retryable


class ProviderRateLimited(ProviderError):
    code = "provider_rate_limited"

    def __init__(self, provider: str, retry_after: float | None = None) -> None:
        super().__init__(provider, "rate limited", retryable=True)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    code = "provider_unavailable"


class CircuitOpenError(ProviderError):
    code = "circuit_open"

    def __init__(self, provider: str) -> None:
        super().__init__(provider, "circuit breaker open", retryable=False)


class BudgetExhaustedError(PhatakError):
    status_code = 429
    code = "budget_exhausted"
