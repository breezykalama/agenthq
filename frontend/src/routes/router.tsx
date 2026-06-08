import { createBrowserRouter } from "react-router-dom";

import { ProtectedRoute } from "../auth/ProtectedRoute";
import { OrganizationAdminRoute } from "../auth/OrganizationAdminRoute";
import { OrganizationAuditRoute } from "../auth/OrganizationAuditRoute";
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
import { PolicyDecisionPage } from "../pages/PolicyDecisionPage";
import { PolicyRulesPage } from "../pages/PolicyRulesPage";
import { LoginPage } from "../pages/LoginPage";
import { MCPServersPage } from "../pages/MCPServersPage";
import { OrganizationInvitesPage } from "../pages/OrganizationInvitesPage";
import { RegisterPage } from "../pages/RegisterPage";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  { path: "/bootstrap", element: <BootstrapPage /> },
  { path: "/accept-invite", element: <AcceptInvitePage /> },
  {
    element: <ProtectedRoute />,
    children: [
      {
        path: "/",
        element: <Layout />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: "mcp-servers", element: <MCPServersPage /> },
          { path: "agents", element: <AgentsPage /> },
          { path: "policy-rules", element: <PolicyRulesPage /> },
          { path: "policy-decision", element: <PolicyDecisionPage /> },
          { path: "policy-decisions", element: <PolicyDecisionPage /> },
          { path: "approvals", element: <ApprovalsPage /> },
          { path: "executions", element: <ExecutionsPage /> },
          { path: "incidents", element: <IncidentsPage /> },
          { path: "compliance", element: <CompliancePage /> },
          {
            element: <OrganizationAdminRoute />,
            children: [{ path: "organization/invites", element: <OrganizationInvitesPage /> }]
          },
          {
            element: <OrganizationAuditRoute />,
            children: [{ path: "audit-logs", element: <AuditLogsPage /> }]
          }
        ]
      }
    ]
  }
]);
