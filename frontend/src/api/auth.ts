import { api } from "./client";
import type { BootstrapTokenResponse, TokenResponse, User } from "../types/api";

export interface RegisterPayload {
  email: string;
  full_name: string;
  password: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface BootstrapPayload {
  organization_name: string;
  admin_full_name: string;
  admin_email: string;
  admin_password: string;
}

export const authApi = {
  register: (payload: RegisterPayload) =>
    api.post<User>("/api/v1/auth/register", payload).then((response) => response.data),
  login: (payload: LoginPayload) =>
    api.post<TokenResponse>("/api/v1/auth/login", payload).then((response) => response.data),
  bootstrap: (payload: BootstrapPayload) =>
    api
      .post<BootstrapTokenResponse>("/api/v1/organizations/bootstrap", payload)
      .then((response) => response.data),
  me: () => api.get<User>("/api/v1/auth/me").then((response) => response.data)
};
