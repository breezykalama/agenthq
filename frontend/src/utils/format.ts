import type { UserRole } from "../types/api";

export function formatRole(role: UserRole | undefined): string {
  if (!role) return "";
  return role
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
