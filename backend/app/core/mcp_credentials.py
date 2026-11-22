"""Organization binding for environment-backed MCP credentials.

An MCP server's ``auth_secret_ref`` names a process environment variable, and every
organization shares that environment. A reference is therefore valid only inside its owning
organization's namespace:

    MCP_AUTH_<ORGANIZATION_ID>_<NAME>

``<ORGANIZATION_ID>`` is the organization's UUID as 32 upper-case hexadecimal digits without
hyphens, and ``<NAME>`` is one or more of ``A-Z``, ``0-9`` and ``_``. The identifier has a fixed
length and is followed by ``_``, so one organization's namespace can never contain another's.
"""

import re
from uuid import UUID

MCP_SECRET_REF_PREFIX = "MCP_AUTH_"
MCP_SECRET_REF_MAX_LENGTH = 255
_NAME_PATTERN = re.compile(r"[A-Z0-9_]+")


def organization_secret_ref_prefix(organization_id: UUID) -> str:
    return f"{MCP_SECRET_REF_PREFIX}{organization_id.hex.upper()}_"


def secret_ref_belongs_to_organization(secret_ref: str, organization_id: UUID) -> bool:
    prefix = organization_secret_ref_prefix(organization_id)
    if len(secret_ref) > MCP_SECRET_REF_MAX_LENGTH or not secret_ref.startswith(prefix):
        return False
    return _NAME_PATTERN.fullmatch(secret_ref[len(prefix) :]) is not None
