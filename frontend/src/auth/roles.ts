import type { OrganizationMembership, User, UserRole } from "../types/api";

/**
 * The membership the backend resolved for the current organization selection, or null.
 *
 * Presentation only: the backend authorizes every request. The singular field is trusted only
 * when it is the organization the backend says it selected, so a stale or rejected selection
 * can never lend its role to the UI. Older backends (the v0.8.1 rollback build) do not send
 * `selected_organization_id`; for them the single membership they return is used as before.
 */
export function getSelectedMembership(
  user: User | null | undefined
): OrganizationMembership | null {
  const membership = user?.organization_membership ?? null;
  if (!user || !membership) return null;
  if (user.selected_organization_id === undefined) return membership;
  return user.selected_organization_id === membership.organization_id ? membership : null;
}

/** The selected organization's role. Never the global users.role. */
export function getEffectiveRole(user: User | null | undefined): UserRole | undefined {
  return getSelectedMembership(user)?.role;
}

/** The caller's active memberships, also for older backends that only send one. */
export function getMemberships(user: User | null | undefined): OrganizationMembership[] {
  if (!user) return [];
  if (user.organization_memberships) return user.organization_memberships;
  return user.organization_membership ? [user.organization_membership] : [];
}

/**
 * Which organization to ask the backend to confirm: an explicit request, then this tab's
 * selection, then the user's preference, then the only membership. Every candidate must be
 * one of the memberships the backend just returned; stored values are never trusted alone.
 */
export function chooseOrganizationCandidate(
  memberships: OrganizationMembership[],
  stored: { tab: string | null; preference: string | null },
  requested: string | null = null
): string | null {
  const available = new Set(memberships.map((membership) => membership.organization_id));
  for (const candidate of [requested, stored.tab, stored.preference]) {
    if (candidate && available.has(candidate)) return candidate;
  }
  return memberships.length === 1 ? memberships[0].organization_id : null;
}
