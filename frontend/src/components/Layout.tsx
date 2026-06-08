import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/context";
import { TemporaryOnboarding } from "./Onboarding";

const baseNavItems = [
  { to: "/", label: "Dashboard" },
  { to: "/mcp-servers", label: "MCP Servers" },
  { to: "/agents", label: "Agents" },
  { to: "/policy-rules", label: "Policy Rules" },
  { to: "/policy-decisions", label: "Decision Tester" },
  { to: "/approvals", label: "Approvals" },
  { to: "/executions", label: "Executions" },
  { to: "/incidents", label: "Incidents" },
  { to: "/compliance", label: "Compliance" }
];

export function Layout() {
  const { user, logout } = useAuth();
  const membership = user?.organization_membership;
  const isOrganizationAdmin = membership?.role === "admin";
  const canViewAuditLogs = membership?.role === "admin" || membership?.role === "auditor";
  const navItems = [
    ...baseNavItems,
    ...(canViewAuditLogs ? [{ to: "/audit-logs", label: "Audit Logs" }] : []),
    ...(isOrganizationAdmin ? [{ to: "/organization/invites", label: "Invites" }] : [])
  ];
  const workspaceIdentity = membership
    ? `${membership.organization.name} \u00b7 ${formatRole(membership.role)}`
    : formatRole(user?.role);

  return (
    <div className="min-h-screen bg-slate-100">
      <TemporaryOnboarding />
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r border-slate-200 bg-white px-4 py-5 lg:block">
        <div className="mb-6">
          <div className="text-lg font-semibold text-slate-950">AgentHQ</div>
          <div className="text-sm text-slate-500">Organization Governance</div>
          <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
            <div className="text-xs font-medium uppercase text-slate-500">Current workspace</div>
            <div className="mt-1 truncate text-sm font-semibold text-slate-900">
              {workspaceIdentity}
            </div>
          </div>
        </div>
        <nav className="space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                [
                  "block rounded-md px-3 py-2 text-sm font-medium",
                  isActive ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
                ].join(" ")
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="absolute bottom-5 left-4 right-4 border-t border-slate-200 pt-4">
          <div className="truncate text-sm font-medium text-slate-900">{user?.full_name}</div>
          <div className="mb-3 truncate text-xs text-slate-500">{workspaceIdentity}</div>
          <button
            type="button"
            onClick={logout}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-left text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Sign out
          </button>
        </div>
      </aside>
      <div className="lg:pl-64">
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur lg:px-8">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-sm font-medium text-slate-600">{workspaceIdentity}</div>
              <h1 className="text-xl font-semibold text-slate-950">AgentHQ</h1>
            </div>
            <nav className="flex gap-2 overflow-x-auto lg:hidden">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    [
                      "whitespace-nowrap rounded-md px-3 py-2 text-sm",
                      isActive ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700"
                    ].join(" ")
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="flex items-center justify-between gap-3 lg:hidden">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-slate-900">{user?.full_name}</div>
                <div className="truncate text-xs text-slate-500">{workspaceIdentity}</div>
              </div>
              <button
                type="button"
                onClick={logout}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700"
              >
                Sign out
              </button>
            </div>
          </div>
        </header>
        <main className="px-4 py-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function formatRole(role: string | undefined): string {
  if (!role) return "";
  return role
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
