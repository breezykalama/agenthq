import { api } from "./client";
import type { BootstrapTokenResponse, TokenResponse, User } from "../types/api";

export interface LoginPayload {
  email: string;
  password: string;
}

export interface BootstrapPayload {
  organization_name: string;
  admin_full_name: string;
  admin_email: string;
  admin_password: string;
  bootstrap_secret?: string;
}

export interface IdentityActionResponse {
  message: string;
}

export const authApi = {
  login: (payload: LoginPayload) =>
    api.post<TokenResponse>("/api/v1/auth/login", payload).then((response) => response.data),
  verifyEmail: (token: string) =>
    api
      .post<IdentityActionResponse>("/api/v1/auth/verify-email", { token })
      .then((response) => response.data),
  forgotPassword: (email: string) =>
    api
      .post<IdentityActionResponse>("/api/v1/auth/forgot-password", { email })
      .then((response) => response.data),
  resendVerification: (email: string) =>
    api
      .post<IdentityActionResponse>("/api/v1/auth/resend-verification", { email })
      .then((response) => response.data),
  resetPassword: (token: string, newPassword: string) =>
    api
      .post<IdentityActionResponse>("/api/v1/auth/reset-password", {
        token,
        new_password: newPassword
      })
      .then((response) => response.data),
  bootstrap: ({ bootstrap_secret, ...payload }: BootstrapPayload) =>
    api
      .post<BootstrapTokenResponse>("/api/v1/organizations/bootstrap", payload, {
        headers: bootstrap_secret ? { "X-Bootstrap-Secret": bootstrap_secret } : undefined
      })
      .then((response) => response.data),
  /**
   * The caller's identity. `organization: null` asks without any selection (membership
   * discovery); a string asks the backend to resolve that candidate against the caller's own
   * memberships. Omitted: the tab's current selection.
   */
  me: (options: { organization?: string | null } = {}) =>
    api
      .get<User>("/api/v1/auth/me", { organization: options.organization })
      .then((response) => response.data)
};
