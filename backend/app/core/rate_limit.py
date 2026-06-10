import hashlib
import logging
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings

security_logger = logging.getLogger("agenthq.security")


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = monotonic()
        cutoff = now - window_seconds
        with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= limit:
                return False
            requests.append(now)
            return True

    def clear(self) -> None:
        with self._lock:
            self._requests.clear()


rate_limiter = InMemoryRateLimiter()


def get_client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def safe_identifier(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:16]


def enforce_auth_rate_limit(
    request: Request,
    scope: str,
    *,
    identifier: str | None = None,
    db: Session | None = None,
) -> None:
    settings = get_settings()
    client_ip = get_client_ip(request)
    keys = [f"{scope}:{client_ip}"]
    if identifier is not None:
        keys.append(f"{scope}:{client_ip}:{safe_identifier(identifier)}")
    for key in keys:
        if not rate_limiter.allow(
            key,
            limit=settings.auth_rate_limit_attempts,
            window_seconds=settings.auth_rate_limit_window_seconds,
        ):
            break
    else:
        return

    security_logger.warning(
        "security_rate_limit_exceeded scope=%s client_ip=%s",
        scope,
        client_ip,
    )
    if db is not None:
        from app.models.audit_log import AuditAction, AuditOutcome
        from app.services import audit_logs as audit_log_service

        audit_log_service.record_event(
            db,
            action=AuditAction.SECURITY_RATE_LIMITED,
            resource_type="authentication",
            outcome=AuditOutcome.DENIED,
            reason="Authentication rate limit exceeded.",
            metadata={"scope": scope},
        )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many requests. Please try again later.",
    )
