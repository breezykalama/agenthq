"""Client-IP resolution behind a reverse proxy, and the IP-based rate-limit buckets built on it.

On Render the TCP peer is the platform proxy, so without TRUSTED_CLIENT_IP_HEADER every user
shares one IP bucket. These tests pin the secure behaviour:

- the header is ignored unless explicitly configured;
- when configured, it is honoured only from an internal (non-public) peer, and only if it
  holds exactly one valid address;
- X-Forwarded-For is never used;
- IPv6 clients are bucketed per /64;
- per-email / per-token limits still apply however the IP is rotated.
"""

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from app.core.config import Settings, get_settings
from app.core.rate_limit import get_client_ip, parse_single_ip, rate_limit_ip_key

RENDER_PROXY_PEER = ("10.204.7.31", 40000)  # internal address, as Render's proxy appears
PUBLIC_PEER = ("8.8.4.4", 40000)  # a globally routable client reaching the app directly
HEADER = "cf-connecting-ip"
STRONG_JWT_SECRET = "A-strong-production-secret-with-32-characters!"


def make_request(peer: str | None, headers: list[tuple[str, str]] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers or []],
            "client": (peer, 1234) if peer is not None else None,
        }
    )


@pytest.fixture()
def trust_header(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TRUSTED_CLIENT_IP_HEADER", HEADER)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def proxied(client: TestClient, peer: tuple[str, int] = RENDER_PROXY_PEER) -> TestClient:
    """A client whose TCP peer is the given address (lifespan resets the limiter)."""
    return TestClient(client.app, client=peer)


def failed_login(client: TestClient, email: str, headers: dict[str, str] | None = None) -> int:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong-password-1"},
        headers=headers or {},
    )
    return int(response.status_code)


# --- Resolution (unit) --------------------------------------------------------------------------


def test_disabled_by_default_uses_socket_peer_and_ignores_all_headers() -> None:
    get_settings.cache_clear()
    request = make_request(
        "10.0.0.5", [(HEADER, "203.0.113.7"), ("x-forwarded-for", "192.0.2.1, 203.0.113.7")]
    )

    assert get_settings().trusted_client_ip_header is None
    assert get_client_ip(request) == "10.0.0.5"


def test_configured_header_from_internal_peer_is_used(trust_header: None) -> None:
    assert get_client_ip(make_request("10.0.0.5", [(HEADER, "203.0.113.7")])) == "203.0.113.7"


def test_x_forwarded_for_is_never_used(trust_header: None) -> None:
    request = make_request("10.0.0.5", [("x-forwarded-for", "192.0.2.99")])

    assert get_client_ip(request) == "10.0.0.5"
    both = make_request("10.0.0.5", [("x-forwarded-for", "192.0.2.99"), (HEADER, "203.0.113.7")])
    assert get_client_ip(both) == "203.0.113.7"


def test_header_from_public_peer_is_untrusted(trust_header: None) -> None:
    assert get_client_ip(make_request("8.8.4.4", [(HEADER, "203.0.113.7")])) == (
        "8.8.4.4"
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "not-an-ip",
        "203.0.113.7, 198.51.100.1",
        "203.0.113.7,198.51.100.1",
        "203.0.113.7 198.51.100.1",
        "203.0.113.7:443",
        "[2001:db8::1]",
        "[2001:db8::1]:443",
        "fe80::1%eth0",
        "999.1.1.1",
        "203.0.113.0/24",
        "unknown",
    ],
)
def test_malformed_header_values_fall_back_to_peer(trust_header: None, value: str) -> None:
    assert get_client_ip(make_request("10.0.0.5", [(HEADER, value)])) == "10.0.0.5"


def test_missing_or_duplicated_header_falls_back_to_peer(trust_header: None) -> None:
    assert get_client_ip(make_request("10.0.0.5")) == "10.0.0.5"
    duplicated = make_request("10.0.0.5", [(HEADER, "203.0.113.7"), (HEADER, "192.0.2.1")])
    assert get_client_ip(duplicated) == "10.0.0.5"


def test_non_ip_peer_never_enables_header_trust(trust_header: None) -> None:
    assert get_client_ip(make_request("testclient", [(HEADER, "203.0.113.7")])) == "testclient"
    assert get_client_ip(make_request(None, [(HEADER, "203.0.113.7")])) == "unknown"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("203.0.113.7", "203.0.113.7"),
        (" 203.0.113.7 ", "203.0.113.7"),
        ("::ffff:203.0.113.7", "203.0.113.7"),
        ("2001:0DB8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
        ("2001:db8::1", "2001:db8::1"),
    ],
)
def test_equivalent_representations_normalize(raw: str, expected: str) -> None:
    assert str(parse_single_ip(raw)) == expected


# --- Bucket keys (unit) -------------------------------------------------------------------------


def test_ipv4_addresses_get_independent_buckets() -> None:
    assert rate_limit_ip_key("203.0.113.7") == "203.0.113.7"
    assert rate_limit_ip_key("203.0.113.7") != rate_limit_ip_key("203.0.113.8")


def test_ipv6_addresses_share_a_bucket_per_64() -> None:
    same = {
        rate_limit_ip_key("2001:db8:1:2::a"),
        rate_limit_ip_key("2001:db8:1:2:ffff:ffff:ffff:ffff"),
        rate_limit_ip_key("2001:0db8:0001:0002:0000:0000:0000:0001"),
    }
    assert same == {"2001:db8:1:2::/64"}
    assert rate_limit_ip_key("2001:db8:1:3::a") == "2001:db8:1:3::/64"


def test_non_ip_identity_is_kept_verbatim() -> None:
    assert rate_limit_ip_key("testclient") == "testclient"
    assert rate_limit_ip_key("unknown") == "unknown"


# --- Configuration ------------------------------------------------------------------------------


def settings_with(header: str) -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL="postgresql://agenthq:agenthq@localhost:5432/agenthq",
        TRUSTED_CLIENT_IP_HEADER=header,
    )


@pytest.mark.parametrize("header", ["x-forwarded-for", "X-Forwarded-For", "forwarded"])
def test_forwarding_chain_headers_are_refused(header: str) -> None:
    with pytest.raises(ValidationError, match="never a forwarding chain"):
        settings_with(header)


@pytest.mark.parametrize("header", ["cf connecting ip", "cf-connecting-ip,x-real-ip", "a:b"])
def test_malformed_header_names_are_refused(header: str) -> None:
    with pytest.raises(ValidationError, match="single HTTP header name"):
        settings_with(header)


def test_header_name_is_normalized_and_blank_disables() -> None:
    assert settings_with("  CF-Connecting-IP ").trusted_client_ip_header == "cf-connecting-ip"
    assert settings_with("   ").trusted_client_ip_header is None


# --- Integration: real endpoints behind a Render-like proxy -------------------------------------


def test_reproduction_default_config_shares_one_bucket_across_clients(
    unauthenticated_client: TestClient,
) -> None:
    """Session 8 reproduction: with the header unset, every client behind the proxy is one IP."""
    with proxied(unauthenticated_client) as client:
        for i in range(10):
            assert failed_login(client, f"a{i}@example.com", {HEADER: "203.0.113.10"}) == 401
        assert failed_login(client, "b@example.com", {HEADER: "198.51.100.20"}) == 429


def test_trusted_header_gives_each_client_its_own_bucket(
    unauthenticated_client: TestClient,
    trust_header: None,
) -> None:
    with proxied(unauthenticated_client) as client:
        for i in range(10):
            assert failed_login(client, f"a{i}@example.com", {HEADER: "203.0.113.10"}) == 401
        assert failed_login(client, "a10@example.com", {HEADER: "203.0.113.10"}) == 429
        assert failed_login(client, "b@example.com", {HEADER: "198.51.100.20"}) == 401


def test_rotating_x_forwarded_for_does_not_escape_the_bucket(
    unauthenticated_client: TestClient,
    trust_header: None,
) -> None:
    with proxied(unauthenticated_client) as client:
        codes = [
            failed_login(
                client,
                f"spray{i}@example.com",
                {HEADER: "203.0.113.10", "X-Forwarded-For": f"192.0.2.{i}"},
            )
            for i in range(12)
        ]
    assert codes == [401] * 10 + [429, 429]


def test_rotating_cf_header_has_no_effect_when_trust_disabled(
    unauthenticated_client: TestClient,
) -> None:
    with proxied(unauthenticated_client) as client:
        codes = [
            failed_login(client, f"spray{i}@example.com", {HEADER: f"192.0.2.{i}"})
            for i in range(12)
        ]
    assert codes == [401] * 10 + [429, 429]


def test_untrusted_public_ingress_cannot_choose_its_ip(
    unauthenticated_client: TestClient,
    trust_header: None,
) -> None:
    with proxied(unauthenticated_client, PUBLIC_PEER) as client:
        codes = [
            failed_login(client, f"spray{i}@example.com", {HEADER: f"192.0.2.{i}"})
            for i in range(12)
        ]
    assert codes == [401] * 10 + [429, 429]


def test_ipv6_clients_in_one_64_share_a_bucket(
    unauthenticated_client: TestClient,
    trust_header: None,
) -> None:
    with proxied(unauthenticated_client) as client:
        for i in range(10):
            ip = f"2001:db8:1:2::{i + 1:x}"
            assert failed_login(client, f"v6-{i}@example.com", {HEADER: ip}) == 401
        same_64 = failed_login(client, "v6-x@example.com", {HEADER: "2001:db8:1:2:abcd::1"})
        other_64 = failed_login(client, "v6-y@example.com", {HEADER: "2001:db8:1:3::1"})
    assert same_64 == 429
    assert other_64 == 401


def test_per_email_limit_holds_while_rotating_ips(
    unauthenticated_client: TestClient,
    trust_header: None,
) -> None:
    with proxied(unauthenticated_client) as client:
        codes = [
            failed_login(client, "victim@example.com", {HEADER: f"192.0.2.{i}"}) for i in range(12)
        ]
    assert codes == [401] * 10 + [429, 429]


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/v1/auth/reset-password", {"token": "t" * 43, "new_password": "NewPassword123!"}),
        ("/api/v1/auth/verify-email", {"token": "t" * 43}),
        ("/api/v1/organization-invites/accept", {"token": "t" * 43, "password": "Password123!"}),
    ],
)
def test_per_token_limit_holds_while_rotating_ips(
    unauthenticated_client: TestClient,
    trust_header: None,
    path: str,
    payload: dict[str, str],
) -> None:
    with proxied(unauthenticated_client) as client:
        codes = [
            client.post(path, json=payload, headers={HEADER: f"192.0.2.{i}"}).status_code
            for i in range(12)
        ]
    assert 429 not in codes[:10]
    assert codes[10:] == [429, 429]


def test_redis_failure_still_fails_closed(
    unauthenticated_client: TestClient,
    trust_header: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    get_settings.cache_clear()
    with proxied(unauthenticated_client) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "a@example.com", "password": "wrong-password-1"},
            headers={HEADER: "203.0.113.10"},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "Abuse protection is temporarily unavailable."}


def test_production_without_redis_still_fails_closed(
    unauthenticated_client: TestClient,
    trust_header: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", STRONG_JWT_SECRET)
    monkeypatch.setenv("REDIS_URL", "")
    get_settings.cache_clear()
    with proxied(unauthenticated_client) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "a@example.com", "password": "wrong-password-1"},
            headers={HEADER: "203.0.113.10"},
        )
    assert response.status_code == 503


def test_rate_limit_log_carries_resolved_ip_but_no_credentials(
    unauthenticated_client: TestClient,
    trust_header: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with proxied(unauthenticated_client) as client, caplog.at_level(logging.WARNING):
        for i in range(11):
            failed_login(client, f"log{i}@example.com", {HEADER: "203.0.113.10"})

    assert "security_rate_limit_exceeded scope=login client_ip=203.0.113.10" in caplog.text
    assert "wrong-password-1" not in caplog.text
    assert "log10@example.com" not in caplog.text


def test_production_without_header_warns_at_startup(
    unauthenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", STRONG_JWT_SECRET)
    get_settings.cache_clear()
    with caplog.at_level(logging.WARNING, logger="agenthq.security"):
        with proxied(unauthenticated_client):
            pass

    assert "security_client_ip_header_unset" in caplog.text
