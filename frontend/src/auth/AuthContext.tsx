import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { authApi } from "../api/auth";
import {
  AUTH_TOKEN_KEY,
  IDENTITY_CHANGED_EVENT,
  ORGANIZATION_UNAVAILABLE_EVENT,
  StaleOrganizationContextError,
  UNAUTHORIZED_EVENT,
  clearStoredToken,
  getStoredToken,
  setStoredToken
} from "../api/client";
import { organizationInvitesApi } from "../api/organizationInvites";
import type { BootstrapTokenResponse, OrganizationMembership, User } from "../types/api";
import { AuthContext, type AuthContextValue, type OrganizationStatus } from "./context";
import {
  clearTabSelection,
  forgetStoredSelection,
  getOrganizationContext,
  readStoredSelection,
  setOrganizationContext
} from "./organizationSession";
import { chooseOrganizationCandidate, getMemberships, getSelectedMembership } from "./roles";

function joinedOrganization(result: BootstrapTokenResponse): string | null {
  // The organization the backend selected in its response (just created or just joined).
  return getSelectedMembership(result.user)?.organization_id ?? null;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [memberships, setMemberships] = useState<OrganizationMembership[]>([]);
  const [status, setStatus] = useState<OrganizationStatus>(() =>
    getStoredToken() ? "loading" : "anonymous"
  );
  const [selectedOrganizationId, setSelectedOrganizationId] = useState<string | null>(null);
  const [contextKey, setContextKey] = useState(() => getOrganizationContext().key);
  // Only the latest identity load may apply its result (rapid switching, concurrent events).
  const sequence = useRef(0);

  const enterContext = useCallback((userId: string | null, organizationId: string | null) => {
    setContextKey(setOrganizationContext(userId, organizationId).key);
  }, []);

  const signOutLocally = useCallback(() => {
    sequence.current += 1;
    clearTabSelection(getOrganizationContext().userId);
    enterContext(null, null);
    setUser(null);
    setMemberships([]);
    setSelectedOrganizationId(null);
    setStatus("anonymous");
  }, [enterContext]);

  const logout = useCallback(() => {
    clearStoredToken();
    signOutLocally();
  }, [signOutLocally]);

  const loadIdentity = useCallback(
    async (requested: string | null, attempt = 0): Promise<void> => {
      const run = ++sequence.current;
      const isCurrent = () => run === sequence.current;
      if (!getStoredToken()) {
        signOutLocally();
        return;
      }
      // Neutral context first: aborts the previous context's requests, stops sending its
      // organization header and discards its tenant cache before anything new is shown.
      enterContext(null, null);
      setStatus("loading");
      setSelectedOrganizationId(null);
      try {
        const base = await authApi.me({ organization: null });
        if (!isCurrent()) return;
        const available = getMemberships(base);
        const candidate = chooseOrganizationCandidate(
          available,
          readStoredSelection(base.id),
          requested
        );
        const settle = (identity: User, nextStatus: OrganizationStatus, organization: string | null) => {
          enterContext(identity.id, organization);
          setUser(identity);
          setMemberships(getMemberships(identity));
          setSelectedOrganizationId(organization);
          setStatus(nextStatus);
        };
        if (!candidate) {
          settle(base, available.length === 0 ? "none" : "selection-required", null);
          return;
        }
        // Ask the backend to resolve the candidate against the caller's memberships; only its
        // answer selects anything. A 200 from /auth/me never by itself proves a selection.
        const confirmed =
          getSelectedMembership(base)?.organization_id === candidate
            ? base
            : await authApi.me({ organization: candidate });
        if (!isCurrent()) return;
        if (confirmed.id !== base.id || getSelectedMembership(confirmed)?.organization_id !== candidate) {
          // Refused (e.g. the membership was just deactivated): forget it and rediscover once
          // with fresh memberships; a second refusal falls back to the picker.
          forgetStoredSelection(base.id, candidate);
          if (attempt === 0) return loadIdentity(null, 1);
          settle(base, available.length === 0 ? "none" : "selection-required", null);
          return;
        }
        settle(confirmed, "selected", candidate);
      } catch (error) {
        if (!isCurrent() || error instanceof StaleOrganizationContextError) return;
        logout();
      }
    },
    [enterContext, logout, signOutLocally]
  );

  useEffect(() => {
    if (getStoredToken()) void loadIdentity(null);
  }, [loadIdentity]);

  useEffect(() => {
    const onUnauthorized = () => signOutLocally();
    const onOrganizationUnavailable = (event: Event) => {
      const context = getOrganizationContext();
      if (!context.userId) return;
      const rejected = (event as CustomEvent<{ organizationId: string | null }>).detail
        ?.organizationId;
      if (rejected) forgetStoredSelection(context.userId, rejected);
      void loadIdentity(null);
    };
    const onIdentityChanged = () => void loadIdentity(null);
    const onStorage = (event: StorageEvent) => {
      // Another tab signed in or out: the shared token changed, so re-resolve everything.
      if (event.key !== AUTH_TOKEN_KEY && event.key !== null) return;
      if (getStoredToken()) void loadIdentity(null);
      else signOutLocally();
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    window.addEventListener(ORGANIZATION_UNAVAILABLE_EVENT, onOrganizationUnavailable);
    window.addEventListener(IDENTITY_CHANGED_EVENT, onIdentityChanged);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
      window.removeEventListener(ORGANIZATION_UNAVAILABLE_EVENT, onOrganizationUnavailable);
      window.removeEventListener(IDENTITY_CHANGED_EVENT, onIdentityChanged);
      window.removeEventListener("storage", onStorage);
    };
  }, [loadIdentity, signOutLocally]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading: status === "loading",
      organizationStatus: status,
      memberships,
      selectedOrganizationId,
      organizationContextKey: contextKey,
      login: async (payload) => {
        const token = await authApi.login(payload);
        setStoredToken(token.access_token);
        await loadIdentity(null);
      },
      bootstrap: async (payload) => {
        const result = await authApi.bootstrap(payload);
        setStoredToken(result.access_token);
        await loadIdentity(joinedOrganization(result));
      },
      acceptInvite: async (payload) => {
        const result = await organizationInvitesApi.accept(payload);
        setStoredToken(result.access_token);
        await loadIdentity(joinedOrganization(result));
      },
      selectOrganization: async (organizationId) => {
        if (!memberships.some((membership) => membership.organization_id === organizationId)) {
          throw new Error("That organization is not available to this account.");
        }
        await loadIdentity(organizationId);
      },
      logout,
      refreshUser: async () => {
        await loadIdentity(getOrganizationContext().organizationId ?? selectedOrganizationId);
      }
    }),
    [user, status, memberships, selectedOrganizationId, contextKey, loadIdentity, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
