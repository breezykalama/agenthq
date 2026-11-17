import hashlib
import ipaddress
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from functools import lru_cache
from math import ceil
from threading import Lock
from time import monotonic
from typing import Protocol, cast
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.tenancy import get_optional_organization_id

security_logger = logging.getLogger("agenthq.security")
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

SENSITIVE_LIMIT_SETTINGS = {
    "invite_create": "invite_create_rate_limit_attempts",
    "invite_revoke": "invite_create_rate_limit_attempts",
    "approval_action": "approval_rate_limit_attempts",
    "execution_create": "execution_rate_limit_attempts",
    "execution_update": "execution_rate_limit_attempts",
    "mcp_sync": "mcp_sync_rate_limit_attempts",
    "gateway_token": "gateway_token_rate_limit_attempts",
    "policy_decision": "policy_decision_rate_limit_attempts",
    "compliance_access": "compliance_rate_limit_attempts",
}

GATEWAY_LIMIT_SETTINGS = {
    "gateway_tools": "gateway_list_rate_limit_attempts",
    "gateway_call": "gateway_call_rate_limit_attempts",
}


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int


class RateLimitBackend(Protocol):
    def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision: ...


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        now = monotonic()
        cutoff = now - window_seconds
        with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= limit:
                retry_after = max(1, ceil(requests[0] + window_seconds - now))
                return RateLimitDecision(allowed=False, retry_after=retry_after)
            requests.append(now)
            return RateLimitDecision(allowed=True, retry_after=0)

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        return self.check(key, limit=limit, window_seconds=window_seconds).allowed

    def clear(self) -> None:
        with self._lock:
            self._requests.clear()


class RedisRateLimiter:
    _CHECK_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""

    def __init__(self, redis_url: str) -> None:
        from redis import Redis

        self._client = Redis.from_url(redis_url, decode_responses=True)

    def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        result = cast(
            list[int],
            self._client.eval(
                self._CHECK_SCRIPT,
                1,
                f"agenthq:rate-limit:{key}",
                window_seconds,
            ),
        )
        count, ttl = result
        return RateLimitDecision(
            allowed=count <= limit,
            retry_after=max(1, ttl) if count > limit else 0,
        )


class RateLimitBackendUnavailableError(Exception):
    pass


rate_limiter = InMemoryRateLimiter()


@lru_cache
def get_rate_limit_backend() -> RateLimitBackend:
    settings = get_settings()
    if settings.redis_url:
        return RedisRateLimiter(settings.redis_url)
    if settings.is_production:
        raise RateLimitBackendUnavailableError(
            "Production rate limiting requires REDIS_URL."
        )
    return rate_limiter


def reset_rate_limit_backend() -> None:
    get_rate_limit_backend.cache_clear()
    rate_limiter.clear()


IPV6_RATE_LIMIT_PREFIX = 64
UNKNOWN_CLIENT_IP = "unknown"


def parse_single_ip(value: str) -> IPAddress | None:
    """Parse exactly one bare IPv4/IPv6 address; anything else is rejected.

    Rejects empty values, comma-separated chains, embedded whitespace, ports, brackets and
    IPv6 zone identifiers. IPv4-mapped IPv6 addresses are reduced to their IPv4 form so the
    same client always produces the same identity.
    """
    candidate = value.strip()
    if not candidate or any(char in candidate for char in ", \t%[]/"):
        return None
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _peer_may_relay_client_ip(peer: IPAddress | None) -> bool:
    """Only an internal hop (private, loopback, shared or link-local address) can be the edge
    proxy. A peer with a public address reached the app directly, so any client-IP header it
    sends is client-controlled and is ignored. This does NOT distinguish the platform proxy
    from other internal callers; that remains a documented deployment assumption."""
    return peer is not None and not peer.is_global


def get_client_ip(request: Request) -> str:
    """Resolve the client address used for rate-limit keys and security logs.

    Default: the TCP peer. When TRUSTED_CLIENT_IP_HEADER is configured, exactly one valid
    address in that header replaces the peer, but only when the peer is an internal hop.
    X-Forwarded-For is never consulted. Every failure falls back to the peer.
    """
    peer = parse_single_ip(request.client.host) if request.client is not None else None
    header = get_settings().trusted_client_ip_header
    if header is not None and _peer_may_relay_client_ip(peer):
        values = request.headers.getlist(header)
        if len(values) == 1:
            relayed = parse_single_ip(values[0])
            if relayed is not None:
                return str(relayed)
    if peer is not None:
        return str(peer)
    if request.client is not None and request.client.host:
        return request.client.host  # non-IP peer, e.g. a unix socket or test transport
    return UNKNOWN_CLIENT_IP


def rate_limit_ip_key(client_ip: str) -> str:
    """Bucket identity for IP-based limits: one IPv4 address, or one IPv6 /64 network
    (a single subscriber usually controls a whole /64)."""
    address = parse_single_ip(client_ip)
    if isinstance(address, ipaddress.IPv6Address):
        network = ipaddress.IPv6Network((address, IPV6_RATE_LIMIT_PREFIX), strict=False)
        return str(network)
    return str(address) if address is not None else client_ip


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
    if not settings.rate_limits_enabled:
        return
    client_ip = get_client_ip(request)
    keys = [f"auth:{scope}:ip:{rate_limit_ip_key(client_ip)}"]
    if identifier is not None:
        keys.append(f"auth:{scope}:identifier:{safe_identifier(identifier)}")
    _enforce_rate_limit(
        request,
        db=db,
        scope=scope,
        resource_type="authentication",
        keys=keys,
        limit=settings.auth_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )


def enforce_authenticated_rate_limit(
    request: Request,
    db: Session,
    scope: str,
    *,
    resource_type: str,
    resource_id: UUID | None = None,
    key_by_resource: bool = False,
    organization_shared: bool = False,
) -> None:
    settings = get_settings()
    if not settings.rate_limits_enabled:
        return
    actor_user_id = db.info.get("audit_actor_user_id")
    organization_id = get_optional_organization_id(db)
    actor_key = str(actor_user_id) if actor_user_id is not None else "unknown"
    organization_key = str(organization_id) if organization_id is not None else "none"
    key = f"authenticated:{scope}:organization:{organization_key}"
    if not organization_shared:
        key = f"{key}:actor:{actor_key}"
    if key_by_resource and resource_id is not None:
        key = f"{key}:resource:{resource_id}"
    _enforce_rate_limit(
        request,
        db=db,
        scope=scope,
        resource_type=resource_type,
        resource_id=resource_id,
        keys=[key],
        limit=getattr(settings, SENSITIVE_LIMIT_SETTINGS[scope]),
        window_seconds=settings.sensitive_rate_limit_window_seconds,
    )


def enforce_gateway_rate_limit(
    request: Request,
    db: Session,
    scope: str,
    *,
    gateway_token_id: UUID,
    organization_id: UUID,
    resource_id: UUID,
) -> None:
    settings = get_settings()
    if not settings.rate_limits_enabled:
        return
    _enforce_rate_limit(
        request,
        db=db,
        scope=scope,
        resource_type="mcp_gateway",
        resource_id=resource_id,
        keys=[
            f"gateway:{scope}:organization:{organization_id}:token:{gateway_token_id}:"
            f"resource:{resource_id}"
        ],
        limit=getattr(settings, GATEWAY_LIMIT_SETTINGS[scope]),
        window_seconds=settings.sensitive_rate_limit_window_seconds,
    )


def _enforce_rate_limit(
    request: Request,
    *,
    db: Session | None,
    scope: str,
    resource_type: str,
    keys: list[str],
    limit: int,
    window_seconds: int,
    resource_id: UUID | None = None,
) -> None:
    try:
        backend = get_rate_limit_backend()
        denied: RateLimitDecision | None = None
        for key in keys:
            decision = backend.check(key, limit=limit, window_seconds=window_seconds)
            if not decision.allowed:
                denied = decision
                break
    except Exception as exc:
        security_logger.exception("security_rate_limit_backend_unavailable scope=%s", scope)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Abuse protection is temporarily unavailable.",
        ) from exc
    if denied is None:
        return

    client_ip = get_client_ip(request)
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
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=AuditOutcome.DENIED,
            reason="rate_limit_exceeded",
            metadata={
                "endpoint": request.url.path,
                "scope": scope,
            },
        )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many requests. Please try again later.",
        headers={"Retry-After": str(denied.retry_after)},
    )
