import {
  AxiosError,
  AxiosHeaders,
  CanceledError,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig
} from "axios";

import type { OrganizationMembership, User, UserRole } from "../types/api";

/**
 * In-memory stand-in for the AgentHQ API, plugged in as the axios adapter so the real client
 * interceptors run. Organization resolution mirrors backend/app/core/security.py (dd8dd99):
 * strict on organization-scoped routes, lenient on /auth/me, identical reply texts.
 */

interface FakeUser {
  id: string;
  email: string;
  password: string;
  role: UserRole;
}
interface FakeOrganization {
  id: string;
  name: string;
  deleted: boolean;
}
interface FakeMembership {
  userId: string;
  organizationId: string;
  role: UserRole;
  active: boolean;
}
export interface RecordedRequest {
  method: string;
  url: string;
  organization: string | null;
  authorization: string | null;
}
interface Hold {
  match: (request: RecordedRequest) => boolean;
  release: () => void;
  promise: Promise<void>;
  ignoreAbort: boolean;
}

const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function base64Url(value: string): string {
  return btoa(value).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function uuid(n: number): string {
  return `00000000-0000-4000-8000-${n.toString().padStart(12, "0")}`;
}

export class FakeBackend {
  users = new Map<string, FakeUser>();
  organizations = new Map<string, FakeOrganization>();
  memberships: FakeMembership[] = [];
  /** fullName null: the invite carries no name, so a new account must supply one (422). */
  invites = new Map<
    string,
    { organizationId: string; email: string; role: UserRole; fullName?: string | null }
  >();
  /**
   * One-shot failure for the next matching request: "before-commit" fails in transit before the
   * server does anything; "after-commit" applies the request, then loses the reply in transit;
   * "server-error-after-commit" applies it, then answers 500 (the reply failed to build).
   */
  networkFailure: {
    match: (request: RecordedRequest) => boolean;
    when: "before-commit" | "after-commit" | "server-error-after-commit";
  } | null = null;
  requests: RecordedRequest[] = [];
  forcedError: { status: number; detail: string } | null = null;
  multiOrganizationEnabled = false;
  /** Simulated network latency: responses arrive in a later task, as they do in a browser. */
  latencyMs = 0;
  /** Tokens the server now rejects with 401 (expired, or revoked by a password reset). */
  revokedTokens = new Set<string>();
  private holds: Hold[] = [];
  private tokenCounter = 0;

  addOrganization(id: string, name: string, deleted = false): void {
    this.organizations.set(id, { id, name, deleted });
  }

  addUser(id: string, email: string, role: UserRole = "agent_owner"): void {
    this.users.set(id, { id, email, password: "Password123!", role });
  }

  addMembership(userId: string, organizationId: string, role: UserRole, active = true): void {
    this.memberships.push({ userId, organizationId, role, active });
  }

  setMembershipActive(userId: string, organizationId: string, active: boolean): void {
    for (const membership of this.memberships) {
      if (membership.userId === userId && membership.organizationId === organizationId) {
        membership.active = active;
      }
    }
  }

  tokenFor(userId: string): string {
    this.tokenCounter += 1;
    const payload = base64Url(JSON.stringify({ sub: userId, n: this.tokenCounter }));
    return `${base64Url('{"alg":"HS256"}')}.${payload}.signature`;
  }

  /** Delay the next matching response until release() is called. */
  hold(match: (request: RecordedRequest) => boolean, options: { ignoreAbort?: boolean } = {}) {
    let release = () => {};
    const promise = new Promise<void>((resolve) => {
      release = resolve;
    });
    const hold: Hold = { match, release, promise, ignoreAbort: options.ignoreAbort ?? false };
    this.holds.push(hold);
    return { release: () => hold.release() };
  }

  requestsTo(path: string): RecordedRequest[] {
    return this.requests.filter((request) => request.url === path);
  }

  private activeMemberships(userId: string) {
    return this.memberships.filter((membership) => {
      const organization = this.organizations.get(membership.organizationId);
      return membership.userId === userId && membership.active && organization && !organization.deleted;
    });
  }

  private membershipRead(membership: FakeMembership): OrganizationMembership {
    const organization = this.organizations.get(membership.organizationId)!;
    return {
      id: `${membership.userId}-${membership.organizationId}`,
      organization_id: organization.id,
      user_id: membership.userId,
      role: membership.role,
      is_active: membership.active,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      organization: {
        id: organization.id,
        name: organization.name,
        slug: organization.name.toLowerCase().replace(/\s+/g, "-"),
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z"
      }
    };
  }

  /** backend user_read_with_membership: explicit selection, or the only membership. */
  userRead(userId: string, explicit: boolean, selected: string | null): User {
    const user = this.users.get(userId)!;
    const memberships = this.activeMemberships(userId);
    const chosen = explicit
      ? memberships.find((membership) => membership.organizationId === selected) ?? null
      : memberships.length === 1
        ? memberships[0]
        : null;
    return {
      id: user.id,
      email: user.email,
      full_name: user.email,
      role: user.role,
      is_active: true,
      email_verified: true,
      email_verified_at: null,
      email_verification_required: false,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      organization_membership: chosen ? this.membershipRead(chosen) : null,
      organization_memberships: memberships.map((membership) => this.membershipRead(membership)),
      selected_organization_id: chosen ? chosen.organizationId : null
    };
  }

  private parseHeader(value: string | null): { present: boolean; valid: boolean; id: string | null } {
    if (value === null || value === undefined) return { present: false, valid: true, id: null };
    const raw = value.trim().toLowerCase();
    return CANONICAL_UUID.test(raw)
      ? { present: true, valid: true, id: raw }
      : { present: true, valid: false, id: null };
  }

  private userFromAuthorization(authorization: string | null): FakeUser | null {
    const token = authorization?.replace(/^Bearer /, "") ?? "";
    if (this.revokedTokens.has(token)) return null;
    try {
      const claims = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      return this.users.get(claims.sub) ?? null;
    } catch {
      return null;
    }
  }

  private route(config: InternalAxiosRequestConfig, request: RecordedRequest): [number, unknown] {
    const user = this.userFromAuthorization(request.authorization);
    const body = typeof config.data === "string" ? JSON.parse(config.data) : (config.data ?? {});
    if (request.url === "/api/v1/auth/login") {
      const match = [...this.users.values()].find(
        (candidate) => candidate.email === body.email && candidate.password === body.password
      );
      return match
        ? [200, { access_token: this.tokenFor(match.id), token_type: "bearer" }]
        : [401, { detail: "Invalid email or password." }];
    }
    if (request.url === "/api/v1/organization-invites/accept") {
      const invite = this.invites.get(body.token);
      if (!invite) return [400, { detail: "Invite is invalid or expired." }];
      // Same order as backend accept_invite: token, password, duplicate, phase 0 guard.
      let invitee = [...this.users.values()].find((candidate) => candidate.email === invite.email);
      if (invitee) {
        if (invitee.password !== body.password) return [400, { detail: "Invite is invalid or expired." }];
        if (this.activeMemberships(invitee.id).some((m) => m.organizationId === invite.organizationId)) {
          return [409, { detail: "User is already a member of this organization." }];
        }
        if (
          !this.multiOrganizationEnabled &&
          this.activeMemberships(invitee.id).some((m) => m.organizationId !== invite.organizationId)
        ) {
          return [409, { detail: "Multiple organizations are not yet supported." }];
        }
      } else {
        if (invite.fullName === null && !body.full_name) {
          return [422, { detail: "Full name is required to accept this invite." }];
        }
        this.addUser(`user-${invite.email}`, invite.email);
        invitee = this.users.get(`user-${invite.email}`)!;
        invitee.password = body.password;
      }
      this.addMembership(invitee.id, invite.organizationId, invite.role);
      this.invites.delete(body.token);
      return [
        200,
        {
          access_token: this.tokenFor(invitee.id),
          token_type: "bearer",
          user: this.userRead(invitee.id, true, invite.organizationId)
        }
      ];
    }
    if (request.url.startsWith("/api/v1/mcp-gateway/")) return [200, { items: [] }];
    if (!user) return [401, { detail: "Invalid or expired access token." }];

    const header = this.parseHeader(request.organization);
    if (request.url === "/api/v1/auth/me") {
      return [200, this.userRead(user.id, header.present, header.valid ? header.id : null)];
    }
    // Organization-scoped route: the resolver.
    if (this.forcedError) return [this.forcedError.status, { detail: this.forcedError.detail }];
    if (!header.valid) return [400, { detail: "Invalid organization header." }];
    const memberships = this.activeMemberships(user.id);
    let selected: FakeMembership | undefined;
    if (header.present) {
      selected = memberships.find((membership) => membership.organizationId === header.id);
      if (!selected) return [403, { detail: "Organization access denied." }];
    } else if (memberships.length > 1) {
      return [409, { detail: "Organization selection required." }];
    } else if (memberships.length === 0) {
      return [403, { detail: "Organization membership required." }];
    } else {
      selected = memberships[0];
    }
    const organization = this.organizations.get(selected.organizationId)!;
    if (request.url === "/api/v1/agents") {
      return [200, { items: [{ id: `agent-${organization.id}`, name: `Agent of ${organization.name}` }], total: 1 }];
    }
    return [404, { detail: "Not found." }];
  }

  adapter: AxiosAdapter = async (config) => {
    const headers = AxiosHeaders.from(config.headers);
    const request: RecordedRequest = {
      method: (config.method ?? "get").toUpperCase(),
      url: config.url ?? "",
      organization: (headers.get("X-AgentHQ-Organization") as string | null) ?? null,
      authorization: (headers.get("Authorization") as string | null) ?? null
    };
    this.requests.push(request);
    const holdIndex = this.holds.findIndex((hold) => hold.match(request));
    if (holdIndex >= 0) {
      const [hold] = this.holds.splice(holdIndex, 1);
      const aborted = new Promise<never>((_, reject) => {
        if (hold.ignoreAbort || !config.signal) return;
        const signal = config.signal as AbortSignal;
        if (signal.aborted) reject(new CanceledError(undefined, undefined, config));
        signal.addEventListener?.("abort", () =>
          reject(new CanceledError(undefined, undefined, config))
        );
      });
      await Promise.race([hold.promise, aborted]);
    }
    if (this.latencyMs > 0) await new Promise((resolve) => setTimeout(resolve, this.latencyMs));
    const failure = this.networkFailure?.match(request) ? this.networkFailure : null;
    if (failure) this.networkFailure = null;
    const transportError = () => new AxiosError("Network Error", "ERR_NETWORK", config, {});
    if (failure?.when === "before-commit") throw transportError();
    const [status, data] = this.route(config, request);
    if (failure?.when === "after-commit") throw transportError();
    if (failure?.when === "server-error-after-commit") {
      const error = { data: { detail: "Internal Server Error" }, status: 500, statusText: "500", headers: {}, config, request: {} };
      throw new AxiosError("Request failed with status code 500", "ERR_BAD_RESPONSE", config, {}, error);
    }
    const response: AxiosResponse = { data, status, statusText: String(status), headers: {}, config, request: {} };
    if (status >= 400) {
      throw new AxiosError(`Request failed with status code ${status}`, "ERR_BAD_REQUEST", config, {}, response);
    }
    return response;
  };
}
