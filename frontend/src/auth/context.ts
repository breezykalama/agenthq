import { createContext, useContext } from "react";

import type { BootstrapPayload, LoginPayload } from "../api/auth";
import type { AcceptOrganizationInvitePayload } from "../api/organizationInvites";
import type { OrganizationMembership, User } from "../types/api";

/**
 * anonymous: signed out. loading: identity or organization being (re)resolved.
 * none: signed in without any active membership. selection-required: several memberships and
 * no valid selection. selected: the backend confirmed the selected organization.
 */
export type OrganizationStatus =
  | "anonymous"
  | "loading"
  | "none"
  | "selection-required"
  | "selected";

export interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  organizationStatus: OrganizationStatus;
  memberships: OrganizationMembership[];
  selectedOrganizationId: string | null;
  /** Identifies the current user + organization context; tenant caches are keyed by it. */
  organizationContextKey: string;
  login: (payload: LoginPayload) => Promise<void>;
  bootstrap: (payload: BootstrapPayload) => Promise<void>;
  acceptInvite: (payload: AcceptOrganizationInvitePayload) => Promise<void>;
  selectOrganization: (organizationId: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider.");
  return context;
}
