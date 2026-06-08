import { createContext, useContext } from "react";

import type { BootstrapPayload, LoginPayload, RegisterPayload } from "../api/auth";
import type { AcceptOrganizationInvitePayload } from "../api/organizationInvites";
import type { User } from "../types/api";

export interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  bootstrap: (payload: BootstrapPayload) => Promise<void>;
  acceptInvite: (payload: AcceptOrganizationInvitePayload) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider.");
  return context;
}
