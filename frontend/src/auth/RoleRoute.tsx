import { Navigate, Outlet } from "react-router-dom";

import type { UserRole } from "../types/api";
import { useAuth } from "./context";
import { getEffectiveRole } from "./roles";

export function RoleRoute({ allowedRoles }: { allowedRoles: UserRole[] }) {
  const { user } = useAuth();
  const role = getEffectiveRole(user);

  if (!role || !allowedRoles.includes(role)) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
