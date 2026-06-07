import { useQueryClient } from "@tanstack/react-query";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState
} from "react";

import { authApi } from "../api/auth";
import { clearStoredToken, getStoredToken, setStoredToken } from "../api/client";
import type { User } from "../types/api";
import { AuthContext, type AuthContextValue } from "./context";

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(getStoredToken()));

  const logout = useCallback(() => {
    clearStoredToken();
    setUser(null);
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    const loadUser = async () => {
      if (!getStoredToken()) {
        setIsLoading(false);
        return;
      }
      try {
        setUser(await authApi.me());
      } catch {
        logout();
      } finally {
        setIsLoading(false);
      }
    };
    void loadUser();
  }, [logout]);

  useEffect(() => {
    window.addEventListener("agenthq:unauthorized", logout);
    return () => window.removeEventListener("agenthq:unauthorized", logout);
  }, [logout]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      login: async (payload) => {
        const token = await authApi.login(payload);
        setStoredToken(token.access_token);
        setUser(await authApi.me());
      },
      register: async (payload) => {
        await authApi.register(payload);
        const token = await authApi.login({ email: payload.email, password: payload.password });
        setStoredToken(token.access_token);
        setUser(await authApi.me());
      },
      logout
    }),
    [user, isLoading, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
