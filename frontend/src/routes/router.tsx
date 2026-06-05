import { createBrowserRouter } from "react-router-dom";

import { Layout } from "../components/Layout";
import { AgentsPage } from "../pages/AgentsPage";
import { ApprovalsPage } from "../pages/ApprovalsPage";
import { CompliancePage } from "../pages/CompliancePage";
import { DashboardPage } from "../pages/DashboardPage";
import { ExecutionsPage } from "../pages/ExecutionsPage";
import { IncidentsPage } from "../pages/IncidentsPage";
import { PolicyDecisionPage } from "../pages/PolicyDecisionPage";
import { PolicyRulesPage } from "../pages/PolicyRulesPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "agents", element: <AgentsPage /> },
      { path: "policy-rules", element: <PolicyRulesPage /> },
      { path: "policy-decision", element: <PolicyDecisionPage /> },
      { path: "approvals", element: <ApprovalsPage /> },
      { path: "executions", element: <ExecutionsPage /> },
      { path: "incidents", element: <IncidentsPage /> },
      { path: "compliance", element: <CompliancePage /> }
    ]
  }
]);
