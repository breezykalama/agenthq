import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useRef } from "react";

import { useAuth } from "./context";
import { createTenantQueryClient } from "./tenantQueryClient";

/**
 * One TanStack Query cache per user + organization context.
 *
 * Pages keep their plain query keys (["agents"], ...), but each context gets its own
 * QueryClient whose hashes are also prefixed with the context key. When the user,
 * organization or sign-in state changes, the previous client's queries are cancelled and its
 * cache cleared, and everything below this boundary remounts, so no cached data, retry, error
 * state or component state from the previous organization can reach the new one. Late
 * responses are additionally rejected by the API client before they reach any cache.
 */
export function TenantQueryBoundary({ children }: { children: ReactNode }) {
  const { organizationContextKey } = useAuth();
  const client = useMemo(
    () => createTenantQueryClient(organizationContextKey),
    [organizationContextKey]
  );
  const previous = useRef<QueryClient | null>(null);

  useEffect(() => {
    const prior = previous.current;
    previous.current = client;
    if (prior && prior !== client) {
      void prior.cancelQueries();
      prior.clear();
    }
  }, [client]);

  return (
    <QueryClientProvider client={client} key={organizationContextKey}>
      {children}
    </QueryClientProvider>
  );
}
