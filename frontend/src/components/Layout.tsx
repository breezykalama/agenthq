import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/context";
import { getEffectiveRole } from "../auth/roles";
import type { UserRole } from "../types/api";
import { formatRole } from "../utils/format";
import { TemporaryOnboarding } from "./Onboarding";

type NavItem = {
  to: string;
  label: string;
  roles: UserRole[];
};

type NavSection = {
  label: string;
  items: NavItem[];
};

const allRoles: UserRole[] = ["admin", "auditor", "operator", "agent_owner"];

const navigation: NavSection[] = [
  {
    label: "Overview",
    items: [
      { to: "/dashboard", label: "Dashboard", roles: allRoles },
      { to: "/risk-register", label: "Risk Register", roles: ["admin", "auditor"] },
      { to: "/compliance", label: "Compliance Center", roles: ["admin", "auditor"] }
    ]
  },
  {
    label: "Discovery",
    items: [
      { to: "/agents", label: "Agents", roles: ["admin", "agent_owner"] },
      { to: "/mcp-servers", label: "MCP Servers", roles: ["admin"] },
      { to: "/tool-governance", label: "Tools", roles: ["admin", "operator"] }
    ]
  },
  {
    label: "Governance",
    items: [
      { to: "/policy-rules", label: "Policies", roles: ["admin"] },
      { to: "/approvals", label: "Approvals", roles: ["admin", "operator"] },
      {
        to: "/governance-alerts",
        label: "Governance Alerts",
        roles: ["admin", "auditor", "operator"]
      },
      { to: "/policy-decisions", label: "Decision Tester", roles: ["admin", "operator"] }
    ]
  },
  {
    label: "Operations",
    items: [
      { to: "/executions", label: "Executions", roles: ["admin", "operator"] },
      { to: "/incidents", label: "Incidents", roles: ["admin", "auditor", "operator"] },
      { to: "/audit-logs", label: "Audit Logs", roles: ["admin", "auditor"] }
    ]
  },
  {
    label: "Administration",
    items: [
      { to: "/organization", label: "Organization", roles: ["admin"] },
      { to: "/organization/members", label: "Members", roles: ["admin"] },
      { to: "/gateway-credentials", label: "Gateway Credentials", roles: ["admin"] }
    ]
  }
];

function canAccess(role: UserRole | undefined, allowedRoles: UserRole[]) {
  return role !== undefined && allowedRoles.includes(role);
}

function isPathActive(pathname: string, target: string) {
  return pathname === target.split("#")[0];
}

export function Layout() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [isDesktopOpen, setIsDesktopOpen] = useState(
    () => localStorage.getItem("agenthq_sidebar_open") !== "false"
  );
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const membership = user?.organization_membership;
  const role = getEffectiveRole(user);
  const workspaceIdentity = membership
    ? `${membership.organization.name} \u00b7 ${formatRole(membership.role)}`
    : formatRole(role);
  const visibleSections = useMemo(
    () =>
      navigation
        .map((section) => ({
          ...section,
          items: section.items.filter((item) => canAccess(role, item.roles))
        }))
        .filter((section) => section.items.length > 0),
    [role]
  );
  const activeSection =
    visibleSections.find((section) =>
      section.items.some((item) => isPathActive(location.pathname, item.to))
    )?.label ?? "Overview";
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    () => new Set(["Overview", activeSection])
  );

  useEffect(() => {
    setExpandedSections((current) => new Set([...current, activeSection]));
  }, [activeSection]);

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

  function toggleDesktopSidebar() {
    setIsDesktopOpen((current) => {
      const next = !current;
      localStorage.setItem("agenthq_sidebar_open", String(next));
      return next;
    });
  }

  function toggleSection(label: string) {
    setExpandedSections((current) => {
      const next = new Set(current);
      if (next.has(label)) next.delete(label);
      else next.add(label);
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
          className="fixed inset-0 z-30 bg-slate-950/45 backdrop-blur-[1px] lg:hidden"
          onClick={() => setIsMobileOpen(false)}
        />
      ) : null}
      <aside
        id="primary-navigation"
        className={[
          "fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-slate-200 bg-white shadow-xl transition-transform duration-300 ease-out lg:z-20 lg:w-72 lg:shadow-none",
          isMobileOpen ? "translate-x-0" : "-translate-x-full",
          isDesktopOpen ? "lg:translate-x-0" : "lg:-translate-x-full"
        ].join(" ")}
      >
        <div className="shrink-0 border-b border-slate-200 px-4 py-4">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-lg font-semibold text-slate-950">AgentHQ</div>
              <div className="text-sm text-slate-500">AI governance workspace</div>
            </div>
            <button
              type="button"
              aria-label="Close navigation"
              onClick={() => {
                setIsMobileOpen(false);
                if (window.innerWidth >= 1024) toggleDesktopSidebar();
              }}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-slate-300 text-lg text-slate-600 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
            >
              x
            </button>
          </div>
          <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
            <div className="text-xs font-medium uppercase text-slate-500">Current organization</div>
            <div className="mt-1 break-words text-sm font-semibold text-slate-900">
              {workspaceIdentity}
            </div>
          </div>
        </div>
        <nav aria-label="Primary navigation" className="min-h-0 flex-1 overflow-y-auto px-3 py-4">
          <div className="space-y-4">
            {visibleSections.map((section) => {
              const expanded = expandedSections.has(section.label);
              const sectionActive = section.label === activeSection;
              return (
                <section key={section.label}>
                  <button
                    type="button"
                    aria-expanded={expanded}
                    onClick={() => toggleSection(section.label)}
                    className={[
                      "flex w-full items-center justify-between rounded-md px-3 py-1.5 text-xs font-semibold uppercase text-slate-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900",
                      sectionActive ? "text-slate-900" : "hover:text-slate-700"
                    ].join(" ")}
                  >
                    <span>{section.label}</span>
                    <span aria-hidden="true">{expanded ? "-" : "+"}</span>
                  </button>
                  {expanded ? (
                    <div className="mt-1 space-y-1">
                      {section.items.map((item) => (
                        <NavLink
                          key={`${section.label}-${item.label}`}
                          to={item.to}
                          onClick={() => setIsMobileOpen(false)}
                          className={({ isActive }) =>
                            [
                              "flex min-h-10 items-center rounded-md px-3 py-2 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900",
                              isActive
                                ? "bg-slate-900 text-white"
                                : "text-slate-600 hover:bg-slate-100 hover:text-slate-950"
                            ].join(" ")
                          }
                        >
                          {item.label}
                        </NavLink>
                      ))}
                    </div>
                  ) : null}
                </section>
              );
            })}
          </div>
        </nav>
        <div className="shrink-0 border-t border-slate-200 p-4">
          <div className="break-words text-sm font-medium text-slate-900">{user?.full_name}</div>
          <div className="mb-3 break-words text-xs text-slate-500">{user?.email}</div>
          <button
            type="button"
            onClick={logout}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
          >
            Sign out
          </button>
        </div>
      </aside>
      <div
        className={[
          "min-w-0 transition-[padding] duration-300 ease-out",
          isDesktopOpen ? "lg:pl-72" : "lg:pl-0"
        ].join(" ")}
      >
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              aria-label={isDesktopOpen ? "Hide navigation" : "Open navigation"}
              aria-controls="primary-navigation"
              aria-expanded={isMobileOpen || isDesktopOpen}
              onClick={() => {
                if (window.innerWidth >= 1024) toggleDesktopSidebar();
                else setIsMobileOpen(true);
              }}
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-slate-300 text-lg font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-slate-900"
            >
              <span aria-hidden="true">{"\u2630"}</span>
            </button>
            <div className="min-w-0">
              <div className="truncate text-xs font-medium uppercase text-slate-500">
                {workspaceIdentity}
              </div>
              <h1 className="text-lg font-semibold text-slate-950">AgentHQ</h1>
            </div>
          </div>
        </header>
        <main className="min-w-0 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-[1600px]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
