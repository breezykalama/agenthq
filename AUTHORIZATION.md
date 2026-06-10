# AgentHQ Organization Authorization

## Authorization Boundary

FastAPI is AgentHQ's authorization boundary. The frontend never supplies a trusted
`organization_id`, and repositories derive the active organization from the authenticated user's
active membership.

Every organization-scoped request must:

1. Authenticate an active global user.
2. Resolve exactly one active organization membership.
3. Set the trusted organization context on the database session.
4. Pass a named organization permission check.
5. Query resources using both their resource ID and the trusted organization ID.

Cross-organization IDs return the same `404` response as unknown IDs. This avoids revealing whether
a resource exists in another organization.

## Existing Role Model

AgentHQ currently exposes four membership roles:

- `admin`
- `auditor`
- `operator`
- `agent_owner`

The conceptual roles requested for this hardening effort map to the existing product model as
follows:

| Concept | Existing AgentHQ role | Notes |
| --- | --- | --- |
| Owner | `admin` | AgentHQ has no separate owner role or organization-delete endpoint. |
| Admin | `admin` | Highest current organization role. |
| Member | `agent_owner` or `operator` | Agent owners manage assigned agents/tools; operators manage operational workflows. |
| Viewer | `auditor` | Read-only access to incidents, audit logs, compliance, and dashboard data. |

No new public roles were introduced during this hardening pass.

## Permission Matrix

| Capability | Admin | Auditor | Operator | Agent Owner |
| --- | --- | --- | --- | --- |
| View dashboard | Yes | Yes | Yes | Yes |
| Manage members | Yes | No | No | No |
| Manage invites | Yes | No | No | No |
| Manage agents and tools | Yes | No | No | Assigned agents only |
| Manage MCP servers | Yes | No | No | No |
| Manage policy rules | Yes | No | No | No |
| Evaluate policies / manage executions | Yes | No | Yes | No |
| Manage approvals | Yes | No | Yes | No |
| View incidents | Yes | Yes | Yes | No |
| Create/update/resolve/dismiss incidents | Yes | No | Yes | No |
| View audit logs | Yes | Yes | No | No |
| View compliance reports | Yes | Yes | No | No |
| Delete organization | Not available | No | No | No |

## Central Authorization Helpers

- `require_org_member`: requires an explicit active membership in production and establishes the
  trusted organization context.
- `require_org_role`: compatibility helper for narrowly role-based checks.
- `require_org_permission`: preferred route dependency using named permissions.
- `assert_resource_in_org`: defense-in-depth check before returning or mutating a loaded resource.
- `ensure_agent_access`: additionally restricts agent owners to agents assigned to their email.

Denied permission checks and scoped resource misses generate safe security logs containing the actor
user ID, attempted action, target resource where available, current organization ID, request ID,
and request path. Logs do not reveal another organization's identity.

## Scoped Resources

The following repositories filter reads by the trusted current organization:

- Agents
- Agent tools
- MCP servers
- Policy rules
- Approvals
- Executions
- Incidents
- Audit logs
- Dashboard aggregates
- Compliance reports
- Organization members
- Organization invites

Relationship validation also uses scoped repositories, preventing cross-organization tool, agent,
approval, execution, incident, policy, and MCP-server references.

## Compatibility Boundary

Production always requires an explicit active membership. For local development and tests only, a
legacy global user with no membership may be attached to the single `default-organization`. This
compatibility behavior is disabled in production, refuses inactive memberships, and emits a
security warning when used.

Users with multiple active memberships are denied until organization switching is implemented.
