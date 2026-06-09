import type { User, UserRole } from "../types/api";

export function getEffectiveRole(user: User | null | undefined): UserRole | undefined {
  return user?.organization_membership?.role ?? user?.role;
}
