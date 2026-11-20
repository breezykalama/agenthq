import axios, { type AxiosAdapter, type AxiosError, type InternalAxiosRequestConfig } from "axios";

import { getContextSignal, getOrganizationContext } from "../auth/organizationSession";

export const AUTH_TOKEN_KEY = "agenthq_access_token";
export const ORGANIZATION_HEADER = "X-AgentHQ-Organization";
export const UNAUTHORIZED_EVENT = "agenthq:unauthorized";
export const ORGANIZATION_UNAVAILABLE_EVENT = "agenthq:organization-unavailable";
export const IDENTITY_CHANGED_EVENT = "agenthq:identity-changed";

declare module "axios" {
  interface AxiosRequestConfig {
    /**
     * Organization header for this request. Undefined: the tab's current selection. Null:
     * never send one (membership discovery). A string: an explicit candidate, used only to
     * ask /auth/me to confirm a selection before it becomes current.
     */
    organization?: string | null;
    /** Context generation the request was issued in (set by the client, not by callers). */
    agenthqGeneration?: number;
    /** The stored access token the request was sent with (set by the client, not by callers). */
    agenthqCredential?: string | null;
  }
}

/** A response for an organization context that is no longer current; never shown or cached. */
export class StaleOrganizationContextError extends Error {
  constructor() {
    super("The organization context changed while this request was in flight.");
    this.name = "StaleOrganizationContextError";
  }
}

// Exact backend responses (backend/app/core/security.py) that mean the selection is unusable.
const ORGANIZATION_ERRORS: Record<number, string[]> = {
  400: ["Invalid organization header."],
  403: ["Organization access denied.", "Organization membership required."],
  409: ["Organization selection required."]
};

/** The `sub` claim of a JWT, read without verification, only to detect identity changes. */
export function tokenSubject(token: string | null): string | null {
  if (!token) return null;
  const payload = token.split(".")[1];
  if (!payload) return null;
  try {
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
    const claims = JSON.parse(atob(padded)) as { sub?: unknown };
    return typeof claims.sub === "string" ? claims.sub : null;
  } catch {
    return null;
  }
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "",
  headers: {
    "Content-Type": "application/json"
  }
});

export const gatewayApi = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "",
  headers: {
    "Content-Type": "application/json"
  }
});

export function getStoredToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

/** Re-resolve the identity soon, outside whatever the caller is doing (render, interceptor). */
function announceIdentityChange(): void {
  queueMicrotask(() => window.dispatchEvent(new Event(IDENTITY_CHANGED_EVENT)));
}

/** Stands in for the network: the request is refused locally and never leaves the browser. */
const refuseSuperseded: AxiosAdapter = () => Promise.reject(new StaleOrganizationContextError());

export function attachAuthAndOrganization(
  config: InternalAxiosRequestConfig
): InternalAxiosRequestConfig {
  const token = getStoredToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  config.agenthqCredential = token;
  const context = getOrganizationContext();
  config.agenthqGeneration = context.generation;
  if (!config.signal) config.signal = getContextSignal();

  // Callers can never set the organization header directly; only this client does.
  config.headers.delete?.(ORGANIZATION_HEADER);
  if (context.userId && (!token || tokenSubject(token) !== context.userId)) {
    // This tab's context belongs to one user, but the shared token now belongs to someone else
    // (or nobody): another tab signed in or out. Never send this request with another user's
    // credential, with or without an organization: it is refused locally, and this tab
    // re-resolves its identity. (Throwing here would not stop it: axios still dispatches after
    // a synchronous interceptor throws.)
    config.adapter = refuseSuperseded;
    announceIdentityChange();
    return config;
  }
  const organization =
    config.organization === undefined ? context.organizationId : config.organization;
  if (organization) config.headers.set(ORGANIZATION_HEADER, organization);
  return config;
}

function isStale(config: { agenthqGeneration?: number } | undefined): boolean {
  return config?.agenthqGeneration !== getOrganizationContext().generation;
}

/** The request was sent with a token that another tab has since replaced or removed. */
function credentialSuperseded(config: { agenthqCredential?: string | null } | undefined): boolean {
  return (config?.agenthqCredential ?? null) !== getStoredToken();
}

// Synchronous, so a request is stamped with the context (generation, signal, token and
// organization) in which it was issued, not the one current when axios gets round to sending it.
api.interceptors.request.use(attachAuthAndOrganization, undefined, { synchronous: true });

api.interceptors.response.use(
  (response) => {
    // A late response for a previous user or organization is dropped, so it can never be
    // cached or rendered under the current one (including by retries or error handlers).
    if (isStale(response.config)) return Promise.reject(new StaleOrganizationContextError());
    if (credentialSuperseded(response.config)) {
      announceIdentityChange();
      return Promise.reject(new StaleOrganizationContextError());
    }
    return response;
  },
  (error: unknown) => {
    if (axios.isCancel(error)) return Promise.reject(new StaleOrganizationContextError());
    if (!axios.isAxiosError(error)) return Promise.reject(error);
    if (isStale(error.config)) return Promise.reject(new StaleOrganizationContextError());
    if (credentialSuperseded(error.config)) {
      // E.g. a 401 for the old token arriving before this tab sees the storage event: it says
      // nothing about the new token, so it must not clear it or sign anyone out.
      announceIdentityChange();
      return Promise.reject(new StaleOrganizationContextError());
    }
    const status = error.response?.status;
    if (status === 401) {
      clearStoredToken();
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    } else if (status !== undefined && isOrganizationError(error)) {
      window.dispatchEvent(
        new CustomEvent(ORGANIZATION_UNAVAILABLE_EVENT, {
          detail: { organizationId: error.config?.headers?.get?.(ORGANIZATION_HEADER) ?? null }
        })
      );
    }
    return Promise.reject(error);
  }
);

function isOrganizationError(error: AxiosError): boolean {
  const status = error.response?.status;
  const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
  return (
    status !== undefined &&
    typeof detail === "string" &&
    (ORGANIZATION_ERRORS[status] ?? []).includes(detail)
  );
}

export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (!error.response) return "AgentHQ is unavailable. Check your connection and try again.";
    if (error.response.status === 401) return "Your session has expired. Please sign in again.";
    if (error.response.status === 403) return "You do not have permission to access this resource.";
    if (error.response.status === 422) {
      const detail = error.response.data?.detail;
      if (Array.isArray(detail)) {
        const messages = detail
          .map((item) => (typeof item?.msg === "string" ? item.msg : null))
          .filter(Boolean);
        return messages.length > 0
          ? `Please check the submitted values: ${messages.join("; ")}`
          : "Please check the submitted values and try again.";
      }
      return "Please check the submitted values and try again.";
    }
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    return "AgentHQ could not complete the request. Please try again.";
  }
  return "AgentHQ could not complete the request. Please try again.";
}

export function getGatewayErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error) && error.response?.status === 401) {
    return "The gateway token is invalid, expired, rotated, or revoked.";
  }
  return getErrorMessage(error);
}
