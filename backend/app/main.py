from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from app.api.policy_decisions import router as policy_decisions_router
from app.api.policy_rules import router as policy_rules_router
from app.api.users import router as users_router
from app.core.config import get_cors_origins, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="AgentHQ", version="0.3.0", lifespan=lifespan)
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
