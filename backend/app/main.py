from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.agent_tools import router as agent_tools_router
from app.api.agents import router as agents_router
from app.api.approvals import router as approvals_router
from app.api.audit_logs import router as audit_logs_router
from app.api.auth import router as auth_router
from app.api.compliance import router as compliance_router
from app.api.dashboard import router as dashboard_router
from app.api.executions import router as executions_router
from app.api.health import router as health_router
from app.api.incidents import router as incidents_router
from app.api.mcp_servers import router as mcp_servers_router
from app.api.organization_invites import router as organization_invites_router
from app.api.organizations import router as organizations_router
from app.api.policy_decisions import router as policy_decisions_router
from app.api.policy_rules import router as policy_rules_router
from app.api.users import router as users_router
from app.core.config import get_cors_origins, get_settings
from app.core.rate_limit import rate_limiter
from app.services.audit_logs import AuditLoggingError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    rate_limiter.clear()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="AgentHQ", version="0.4.0", lifespan=lifespan)

    @app.exception_handler(AuditLoggingError)
    async def audit_logging_error_handler(
        request: Request,
        exc: AuditLoggingError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
        )

    cors_origins = get_cors_origins()
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(organizations_router)
    app.include_router(organization_invites_router)
    app.include_router(users_router)
    app.include_router(agents_router)
    app.include_router(agent_tools_router)
    app.include_router(audit_logs_router)
    app.include_router(approvals_router)
    app.include_router(executions_router)
    app.include_router(dashboard_router)
    app.include_router(policy_rules_router)
    app.include_router(policy_decisions_router)
    app.include_router(incidents_router)
    app.include_router(mcp_servers_router)
    app.include_router(compliance_router)
    return app


app = create_app()
