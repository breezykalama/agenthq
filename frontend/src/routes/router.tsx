import { type RouteObject, createBrowserRouter } from "react-router-dom";

import { ProtectedRoute } from "../auth/ProtectedRoute";
import { OrganizationAdminRoute } from "../auth/OrganizationAdminRoute";
import { RoleRoute } from "../auth/RoleRoute";
import { Layout } from "../components/Layout";
import { AcceptInvitePage } from "../pages/AcceptInvitePage";
import { AgentsPage } from "../pages/AgentsPage";
import { ApprovalsPage } from "../pages/ApprovalsPage";
import { AuditLogsPage } from "../pages/AuditLogsPage";
import { BootstrapPage } from "../pages/BootstrapPage";
import { CompliancePage } from "../pages/CompliancePage";
import { DashboardPage } from "../pages/DashboardPage";
import { ExecutionsPage } from "../pages/ExecutionsPage";
import { IncidentsPage } from "../pages/IncidentsPage";
import { IdentityRedirectPage } from "../pages/IdentityRedirectPage";
import { PolicyDecisionPage } from "../pages/PolicyDecisionPage";
import { PolicyRulesPage } from "../pages/PolicyRulesPage";
import { LoginPage } from "../pages/LoginPage";
import { LandingPage } from "../pages/LandingPage";
import { MCPServersPage } from "../pages/MCPServersPage";
import { OrganizationInvitesPage } from "../pages/OrganizationInvitesPage";
import { RegisterPage } from "../pages/RegisterPage";
import { RiskRegisterPage } from "../pages/RiskRegisterPage";
import { ToolGovernancePage } from "../pages/ToolGovernancePage";
import { GovernanceAlertsPage } from "../pages/GovernanceAlertsPage";

// Exported so tests can mount the production route tree with a memory router.
export const routes: RouteObject[] = [
  { path: "/", element: <LandingPage /> },
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  { path: "/bootstrap", element: <BootstrapPage /> },
  { path: "/accept-invite", element: <AcceptInvitePage /> },
  { path: "/verify-email", element: <IdentityRedirectPage mode="verify-email" /> },
  { path: "/forgot-password", element: <IdentityRedirectPage mode="forgot-password" /> },
  { path: "/reset-password", element: <IdentityRedirectPage mode="reset-password" /> },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <Layout />,
        children: [
          { path: "dashboard", element: <DashboardPage /> },
          {
            element: <RoleRoute allowedRoles={["admin"]} />,
            children: [
              { path: "mcp-servers", element: <MCPServersPage /> },
              { path: "gateway-credentials", element: <MCPServersPage /> },
              { path: "policy-rules", element: <PolicyRulesPage /> }
            ]
          },
          {
            element: <RoleRoute allowedRoles={["admin", "agent_owner"]} />,
            children: [{ path: "agents", element: <AgentsPage /> }]
          },
          {
            element: <RoleRoute allowedRoles={["admin", "operator"]} />,
            children: [
              { path: "policy-decision", element: <PolicyDecisionPage /> },
              { path: "policy-decisions", element: <PolicyDecisionPage /> },
              { path: "approvals", element: <ApprovalsPage /> },
              { path: "executions", element: <ExecutionsPage /> },
              { path: "tool-governance", element: <ToolGovernancePage /> }
            ]
          },
          {
            element: <RoleRoute allowedRoles={["admin", "auditor", "operator"]} />,
            children: [
              { path: "incidents", element: <IncidentsPage /> },
              { path: "governance-alerts", element: <GovernanceAlertsPage /> }
            ]
          },
          {
            element: <RoleRoute allowedRoles={["admin", "auditor"]} />,
            children: [
              { path: "compliance", element: <CompliancePage /> },
              { path: "risk-register", element: <RiskRegisterPage /> },
              { path: "audit-logs", element: <AuditLogsPage /> }
            ]
          },
          {
            element: <OrganizationAdminRoute />,
            children: [
              { path: "organization", element: <OrganizationInvitesPage /> },
              { path: "organization/members", element: <OrganizationInvitesPage /> },
              { path: "organization/invites", element: <OrganizationInvitesPage /> }
            ]
          }
        ]
      }
    ]
  }
];

export const router = createBrowserRouter(routes);
