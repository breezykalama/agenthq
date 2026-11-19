/**
 * Per-tab organization context for the authenticated API client.
 *
 * The selected organization lives in this module's memory, so every browser tab has its own,
 * mirrored to sessionStorage (this tab only) so a reload keeps it. A per-user default in
 * localStorage is only a preference for new tabs: it is never authorization and is always
 * re-validated against the backend before use. Nothing here is trusted by the server, which
 * checks every request's organization header against the caller's active memberships.
 *
 * Every change of user or organization starts a new context generation: requests still in
 * flight for the previous context are aborted, and any response that arrives late is rejected
 * by the API client, so it can never populate the new organization's views.
 */

const TAB_KEY_PREFIX = "agenthq.organization.tab.";
const PREFERENCE_KEY_PREFIX = "agenthq.organization.preference.";

export interface OrganizationContextSnapshot {
  userId: string | null;
  organizationId: string | null;
  generation: number;
  key: string;
}

let userId: string | null = null;
let organizationId: string | null = null;
let generation = 0;
let controller = new AbortController();

function snapshot(): OrganizationContextSnapshot {
  return {
    userId,
    organizationId,
    generation,
    key: `${userId ?? "anonymous"}:${organizationId ?? "none"}:${generation}`
  };
}

function read(storage: () => Storage, key: string): string | null {
  try {
    return storage().getItem(key);
  } catch {
    return null;
  }
}

function write(storage: () => Storage, key: string, value: string | null): void {
  try {
    if (value === null) storage().removeItem(key);
    else storage().setItem(key, value);
  } catch {
    // Storage unavailable (private mode, blocked): the selection stays in memory only.
  }
}

const session = () => window.sessionStorage;
const local = () => window.localStorage;

export function getOrganizationContext(): OrganizationContextSnapshot {
  return snapshot();
}

/** Abort-signal for requests issued in the current context; aborted when the context ends. */
export function getContextSignal(): AbortSignal {
  return controller.signal;
}

/**
 * Start a new context. Aborts every request issued under the previous one. The selection is
 * only persisted for a known user, under that user's own keys.
 */
export function setOrganizationContext(
  nextUserId: string | null,
  nextOrganizationId: string | null
): OrganizationContextSnapshot {
  controller.abort();
  controller = new AbortController();
  generation += 1;
  userId = nextUserId;
  organizationId = nextUserId ? nextOrganizationId : null;
  if (nextUserId && nextOrganizationId) {
    write(session, TAB_KEY_PREFIX + nextUserId, nextOrganizationId);
    write(local, PREFERENCE_KEY_PREFIX + nextUserId, nextOrganizationId);
  }
  return snapshot();
}

export function readStoredSelection(forUserId: string): {
  tab: string | null;
  preference: string | null;
} {
  return {
    tab: read(session, TAB_KEY_PREFIX + forUserId),
    preference: read(local, PREFERENCE_KEY_PREFIX + forUserId)
  };
}

/** Forget a selection the backend no longer accepts (deleted, inactive or unknown). */
export function forgetStoredSelection(forUserId: string, forOrganizationId?: string): void {
  const stored = readStoredSelection(forUserId);
  if (!forOrganizationId || stored.tab === forOrganizationId) {
    write(session, TAB_KEY_PREFIX + forUserId, null);
  }
  if (!forOrganizationId || stored.preference === forOrganizationId) {
    write(local, PREFERENCE_KEY_PREFIX + forUserId, null);
  }
}

/** Clear this tab's selection (sign-out). The per-user preference is kept as a hint only. */
export function clearTabSelection(forUserId: string | null): void {
  if (forUserId) write(session, TAB_KEY_PREFIX + forUserId, null);
}

/** Test-only reset of the module state (a fresh tab). */
export function resetOrganizationSessionForTests(): void {
  controller.abort();
  controller = new AbortController();
  userId = null;
  organizationId = null;
  generation = 0;
}
