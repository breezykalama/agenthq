import { Navigate, Outlet } from "react-router-dom";

import { useAuth } from "./context";
import { getEffectiveRole } from "./roles";

export function OrganizationAdminRoute() {
  const { user } = useAuth();

  // Admin of the selected organization only (presentation; the backend authorizes).
  if (getEffectiveRole(user) !== "admin") {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
