from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.user import UserRole

AUDIT_ACTOR_USER_ID = "audit_actor_user_id"
AUDIT_ACTOR_ROLE = "audit_actor_role"
AUDIT_IP_ADDRESS = "audit_ip_address"
AUDIT_REQUEST_ID = "audit_request_id"
AUDIT_USER_AGENT = "audit_user_agent"


def set_request_audit_context(db: Session, request: Request) -> None:
    request_id = getattr(request.state, "request_id", None)
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")
    db.info[AUDIT_REQUEST_ID] = request_id[:255] if request_id else None
    db.info[AUDIT_IP_ADDRESS] = ip_address[:64] if ip_address else None
    db.info[AUDIT_USER_AGENT] = user_agent[:512] if user_agent else None


def set_actor_audit_context(
    db: Session,
    *,
    user_id: UUID,
    role: UserRole,
) -> None:
    db.info[AUDIT_ACTOR_USER_ID] = user_id
    db.info[AUDIT_ACTOR_ROLE] = role.value
