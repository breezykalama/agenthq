import { Navigate, Outlet } from "react-router-dom";

import { useAuth } from "./context";

export function OrganizationAdminRoute() {
  const { user } = useAuth();

  if (user?.organization_membership?.role !== "admin") {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
