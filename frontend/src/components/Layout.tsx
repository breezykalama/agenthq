import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/context";
import { getEffectiveRole } from "../auth/roles";
import type { UserRole } from "../types/api";
import { formatRole } from "../utils/format";
import { TemporaryOnboarding } from "./Onboarding";

const baseNavItems = [
  { to: "/dashboard", label: "Dashboard", shortLabel: "DB", roles: ["admin", "auditor", "operator", "agent_owner"] },
  { to: "/mcp-servers", label: "MCP Servers", shortLabel: "MC", roles: ["admin"] },
  { to: "/tool-governance", label: "Tool Governance", shortLabel: "TG", roles: ["admin", "operator"] },
  { to: "/agents", label: "Agents", shortLabel: "AG", roles: ["admin", "agent_owner"] },
  { to: "/policy-rules", label: "Policy Rules", shortLabel: "PR", roles: ["admin"] },
  { to: "/policy-decisions", label: "Decision Tester", shortLabel: "DT", roles: ["admin", "operator"] },
  { to: "/approvals", label: "Approvals", shortLabel: "AP", roles: ["admin", "operator"] },
  { to: "/executions", label: "Executions", shortLabel: "EX", roles: ["admin", "operator"] },
  { to: "/incidents", label: "Incidents", shortLabel: "IN", roles: ["admin", "auditor", "operator"] },
  { to: "/compliance", label: "Compliance", shortLabel: "CO", roles: ["admin", "auditor"] },
  { to: "/audit-logs", label: "Audit Logs", shortLabel: "AL", roles: ["admin", "auditor"] }
] satisfies Array<{ to: string; label: string; shortLabel: string; roles: UserRole[] }>;

const inviteNavItem = {
  to: "/organization/invites",
  label: "Invites",
  shortLabel: "IV",
  roles: ["admin"] as UserRole[]
};

function canAccess(role: UserRole | undefined, allowedRoles: UserRole[]) {
  return role !== undefined && allowedRoles.includes(role);
}

function navigationForRole(role: UserRole | undefined, hasMembership: boolean) {
  return [
    ...baseNavItems.filter((item) => canAccess(role, item.roles)),
    ...(hasMembership && canAccess(role, inviteNavItem.roles) ? [inviteNavItem] : [])
  ];
}

export function Layout() {
  const { user, logout } = useAuth();
  const [isCollapsed, setIsCollapsed] = useState(
    () => localStorage.getItem("agenthq_sidebar_collapsed") === "true"
  );
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const membership = user?.organization_membership;
  const role = getEffectiveRole(user);
  const navItems = navigationForRole(role, membership !== null && membership !== undefined);
  const workspaceIdentity = membership
    ? `${membership.organization.name} \u00b7 ${formatRole(membership.role)}`
    : formatRole(role);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setIsMobileOpen(false);
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, []);

  useEffect(() => {
    document.body.style.overflow = isMobileOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [isMobileOpen]);

  function toggleCollapsed() {
    setIsCollapsed((current) => {
      const next = !current;
      localStorage.setItem("agenthq_sidebar_collapsed", String(next));
      return next;
    });
  }

  return (
    <div className="min-h-screen min-w-0 bg-slate-100">
      <TemporaryOnboarding />
      {isMobileOpen ? (
        <button
          type="button"
          aria-label="Close navigation"
          className="fixed inset-0 z-30 bg-slate-950/40 lg:hidden"
          onClick={() => setIsMobileOpen(false)}
        />
      ) : null}
      <aside
        id="primary-navigation"
        className={[
          "fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-slate-200 bg-white shadow-xl transition-transform duration-200 lg:z-20 lg:shadow-none lg:transition-[width]",
          isMobileOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
          isCollapsed ? "lg:w-20" : "lg:w-64"
        ].join(" ")}
      >
        <div className="shrink-0 border-b border-slate-200 px-4 py-4">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="text-lg font-semibold text-slate-950">
                <span className={isCollapsed ? "lg:hidden" : ""}>AgentHQ</span>
                <span className={isCollapsed ? "hidden lg:inline" : "hidden"}>AH</span>
              </div>
              <div className={`text-sm text-slate-500 ${isCollapsed ? "lg:hidden" : ""}`}>
                Organization Governance
              </div>
            </div>
            <button
              type="button"
              aria-label="Close navigation"
              className="rounded-md border border-slate-300 px-2.5 py-1.5 text-sm text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 lg:hidden"
              onClick={() => setIsMobileOpen(false)}
            >
              Close
            </button>
            <button
              type="button"
              aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-expanded={!isCollapsed}
              title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              onClick={toggleCollapsed}
              className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-md border border-slate-300 text-sm font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 lg:flex"
            >
              {isCollapsed ? ">" : "<"}
            </button>
          </div>
          <div className={`mt-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 ${isCollapsed ? "lg:hidden" : ""}`}>
            <div className="text-xs font-medium uppercase text-slate-500">Current workspace</div>
            <div className="mt-1 break-words text-sm font-semibold text-slate-900">{workspaceIdentity}</div>
          </div>
        </div>
        <nav aria-label="Primary navigation" className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 py-4">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              title={isCollapsed ? item.label : undefined}
              aria-label={item.label}
              onClick={() => setIsMobileOpen(false)}
              className={({ isActive }) =>
                [
                  "flex min-h-10 items-center rounded-md px-3 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900",
                  isCollapsed ? "lg:justify-center lg:px-2" : "",
                  isActive ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
                ].join(" ")
              }
            >
              <span className={isCollapsed ? "lg:hidden" : ""}>{item.label}</span>
              <span className={isCollapsed ? "hidden text-xs font-semibold lg:inline" : "hidden"}>
                {item.shortLabel}
              </span>
            </NavLink>
          ))}
        </nav>
        <div className="shrink-0 border-t border-slate-200 p-4">
          <div className={isCollapsed ? "lg:hidden" : ""}>
            <div className="break-words text-sm font-medium text-slate-900">{user?.full_name}</div>
            <div className="mb-3 break-words text-xs text-slate-500">{workspaceIdentity}</div>
          </div>
          <button
            type="button"
            onClick={logout}
            title={isCollapsed ? "Sign out" : undefined}
            aria-label="Sign out"
            className={`w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 ${isCollapsed ? "lg:px-2 lg:text-center" : "text-left"}`}
          >
            <span className={isCollapsed ? "lg:hidden" : ""}>Sign out</span>
            <span className={isCollapsed ? "hidden lg:inline" : "hidden"}>Out</span>
          </button>
        </div>
      </aside>
      <div className={`min-w-0 transition-[padding] duration-200 ${isCollapsed ? "lg:pl-20" : "lg:pl-64"}`}>
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              aria-label="Open navigation"
              aria-controls="primary-navigation"
              aria-expanded={isMobileOpen}
              onClick={() => setIsMobileOpen(true)}
              className="shrink-0 rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900 lg:hidden"
            >
              Menu
            </button>
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-slate-600">{workspaceIdentity}</div>
              <h1 className="text-xl font-semibold text-slate-950">AgentHQ</h1>
            </div>
          </div>
        </header>
        <main className="min-w-0 px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
