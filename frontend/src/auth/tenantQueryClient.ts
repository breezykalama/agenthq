import { QueryClient, hashKey } from "@tanstack/react-query";

/**
 * A QueryClient for one user + organization context. Query hashes are prefixed with the
 * context key, so even a cache shared by mistake could never answer one organization's query
 * with another's data. TenantQueryBoundary creates one per context and discards the previous.
 */
export function createTenantQueryClient(contextKey: string): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        refetchOnWindowFocus: false,
        queryKeyHashFn: (queryKey) => hashKey([contextKey, ...queryKey])
      }
    }
  });
}
