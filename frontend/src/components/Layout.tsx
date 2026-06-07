import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/context";

const navItems = [
  { to: "/", label: "Dashboard" },
  { to: "/agents", label: "Agents" },
  { to: "/policy-rules", label: "Policy Rules" },
  { to: "/policy-decision", label: "Decision Tester" },
  { to: "/approvals", label: "Approvals" },
  { to: "/executions", label: "Executions" },
  { to: "/incidents", label: "Incidents" },
  { to: "/compliance", label: "Compliance" }
];

export function Layout() {
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen bg-slate-100">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r border-slate-200 bg-white px-4 py-5 lg:block">
        <div className="mb-8">
          <div className="text-lg font-semibold text-slate-950">AgentHQ</div>
          <div className="text-sm text-slate-500">Governance Console</div>
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
          <div className="mb-3 text-xs capitalize text-slate-500">
            {user?.role.replace(/_/g, " ")}
          </div>
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
              <div className="text-sm text-slate-500">Enterprise Agent Governance</div>
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
                <div className="text-xs capitalize text-slate-500">
                  {user?.role.replace(/_/g, " ")}
                </div>
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
