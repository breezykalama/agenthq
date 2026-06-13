from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.agent_tools import router as agent_tools_router
from app.api.agents import router as agents_router
from app.api.approvals import router as approvals_router
from app.api.audit_logs import router as audit_logs_router
from app.api.auth import router as auth_router
from app.api.compliance import router as compliance_router
from app.api.dashboard import router as dashboard_router
from app.api.executions import router as executions_router
from app.api.governance_alerts import health_router as governance_health_router
from app.api.governance_alerts import router as governance_alerts_router
from app.api.health import router as health_router
from app.api.incidents import router as incidents_router
from app.api.mcp_servers import router as mcp_servers_router
from app.api.organization_invites import router as organization_invites_router
from app.api.organizations import router as organizations_router
from app.api.policy_decisions import router as policy_decisions_router
from app.api.policy_rules import router as policy_rules_router
from app.api.policy_simulations import router as policy_simulations_router
from app.api.tool_governance import router as tool_governance_router
from app.api.tool_governance import summary_router as tool_governance_summary_router
from app.api.users import router as users_router
from app.core.config import get_cors_origins, get_settings
from app.core.rate_limit import reset_rate_limit_backend
from app.services.audit_logs import AuditLoggingError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    reset_rate_limit_backend()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="AgentHQ", version="0.5.3", lifespan=lifespan)

    @app.middleware("http")
    async def request_context_middleware(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

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
    app.include_router(policy_simulations_router)
    app.include_router(incidents_router)
    app.include_router(mcp_servers_router)
    app.include_router(compliance_router)
    app.include_router(tool_governance_router)
    app.include_router(tool_governance_summary_router)
    app.include_router(governance_alerts_router)
    app.include_router(governance_health_router)
    return app


app = create_app()
