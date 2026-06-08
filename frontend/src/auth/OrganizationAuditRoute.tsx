import { Navigate, Outlet } from "react-router-dom";

import { useAuth } from "./context";

export function OrganizationAuditRoute() {
  const { user } = useAuth();
  const role = user?.organization_membership?.role;

  if (role !== "admin" && role !== "auditor") {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
