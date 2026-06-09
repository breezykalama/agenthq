import ipaddress
from urllib.parse import urlsplit

from app.core.config import get_settings


def validate_mcp_server_url(value: str) -> str:
    if not value or any(character.isspace() for character in value):
        raise ValueError("MCP server URL must be a valid HTTP or HTTPS URL.")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _port = parsed.port
    except ValueError as exc:
        raise ValueError("MCP server URL must be a valid HTTP or HTTPS URL.") from exc

    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        raise ValueError("MCP server URL must be a valid HTTP or HTTPS URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("MCP server URL must not contain credentials.")
    if not get_settings().private_mcp_urls_allowed and is_private_hostname(hostname):
        raise ValueError("Private network MCP server URLs are not allowed.")
    return value


def is_private_hostname(hostname: str) -> bool:
    normalized = hostname.lower().rstrip(".")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_reserved
    )
