# AgentHQ Supabase Row Level Security Audit

Audit date: June 10, 2026

## Executive Summary

The live Supabase `public` schema contains 13 tables. Before remediation, every table had Row Level
Security (RLS) disabled, no RLS policies, and full table privileges granted to Supabase's `anon` and
`authenticated` roles.

AgentHQ does not access Supabase tables directly from the frontend. The React application calls the
FastAPI API through Axios, and FastAPI accesses PostgreSQL through SQLAlchemy. AgentHQ identity,
roles, and organization memberships are application-managed rather than Supabase Auth identities.
For that reason, policies based on `auth.uid()` would not represent AgentHQ users or memberships.

The least-privilege remediation is:

- Enable RLS on every public table.
- Revoke all table privileges from `anon` and `authenticated`.
- Revoke the application migration role's default privileges for future public tables, sequences,
  and functions from `anon` and `authenticated`.
- Create no client policies. With RLS enabled, no policy means deny by default.
- Preserve backend, migration, and service-role access.
- Do not use `FORCE ROW LEVEL SECURITY`, because AgentHQ's backend currently connects using the
  PostgreSQL owner role with `BYPASSRLS`.

Migration: `backend/alembic/versions/202606100001_enable_rls_for_public_tables.py`

## Access Analysis

| Access path | Current behavior | RLS decision |
| --- | --- | --- |
| React frontend | Calls FastAPI only; no Supabase client or direct table access | No client policies required |
| FastAPI backend | Uses SQLAlchemy and `DATABASE_URL` | Preserved through the current owner/BYPASSRLS role |
| Alembic | Uses the backend database connection | Preserved; RLS is not forced |
| Supabase `anon` | No legitimate AgentHQ use | Revoke privileges and deny all rows |
| Supabase `authenticated` | AgentHQ does not use Supabase Auth for authorization | Revoke privileges and deny all rows |
| Supabase `service_role` | Administrative/server access | Retained; service role bypasses RLS |

The live grant audit also found that both `postgres` and Supabase's managed `supabase_admin` role
currently default-grant future public tables, sequences, and functions to Data API roles. The
migration can safely harden defaults owned by its executing role (`postgres`). It intentionally
does not alter `supabase_admin` defaults because `postgres` is not a member of that managed role.
Any future Supabase-managed public objects should therefore still receive an explicit security
review.

## Pre-Change Table Audit

| Table | Current RLS status | Risk | Sensitivity | Recommended action |
| --- | --- | --- | --- | --- |
| `users` | Disabled; no policies | Critical | Identity, password hashes, account state | Enable RLS; deny Data API clients |
| `organization_memberships` | Disabled; no policies | Critical | Tenant roles and authorization | Enable RLS; deny Data API clients |
| `organization_invites` | Disabled; no policies | Critical | Invite hashes, emails, roles | Enable RLS; deny Data API clients |
| `audit_logs` | Disabled; no policies | Critical | Governance history and snapshots | Enable RLS; deny Data API clients |
| `organizations` | Disabled; no policies | High | Tenant metadata | Enable RLS; deny Data API clients |
| `agents` | Disabled; no policies | High | Organization agent inventory | Enable RLS; deny Data API clients |
| `agent_tools` | Disabled; no policies | High | Tool permissions and risk levels | Enable RLS; deny Data API clients |
| `mcp_servers` | Disabled; no policies | High | MCP endpoints, errors, linkage | Enable RLS; deny Data API clients |
| `policy_rules` | Disabled; no policies | High | Governance and enforcement rules | Enable RLS; deny Data API clients |
| `approvals` | Disabled; no policies | High | Human decisions and reasons | Enable RLS; deny Data API clients |
| `executions` | Disabled; no policies | High | Inputs, outputs, costs, errors | Enable RLS; deny Data API clients |
| `incidents` | Disabled; no policies | High | Incident and resolution data | Enable RLS; deny Data API clients |
| `alembic_version` | Disabled; no policies | Medium | Migration metadata | Enable RLS; deny Data API clients |

## Policies and Rationale

No `SELECT`, `INSERT`, `UPDATE`, or `DELETE` policies are created for `anon` or `authenticated`.
This is deliberate.

AgentHQ's authorization model depends on its own JWT, active organization membership, membership
role, and backend tenant-scoping logic. Supabase Data API sessions do not contain that application
context. Adding policies based only on `auth.uid()` or broad role checks would either block valid
AgentHQ behavior or create a second, weaker authorization path around FastAPI.

With RLS enabled and no applicable policy:

- `anon` cannot read or mutate rows.
- `authenticated` cannot read or mutate rows.
- Direct client access is denied by default.
- FastAPI remains the single authorization and tenant-isolation boundary.

The migration also revokes table privileges from both client roles. Privilege revocation and RLS
are separate protections: privileges block table operations, while RLS protects rows if privileges
are later granted accidentally.

It also revokes the migration role's default grants to Data API roles for future public tables,
sequences, and functions, preventing later AgentHQ migrations from silently recreating this
exposure.

## Generated Migration Behavior

Upgrade:

1. Enables RLS on all 13 public tables.
2. Revokes all table privileges from `anon`, if that Supabase role exists.
3. Revokes all table privileges from `authenticated`, if that Supabase role exists.
4. Revokes the migration role's future default privileges for both client roles.
5. Leaves `service_role`, the table owner, and backend access unchanged.

Downgrade:

1. Restores the migration role's future default privileges for `anon` and `authenticated`.
2. Restores full table privileges to `anon` and `authenticated`, if those roles exist.
3. Disables RLS on all 13 tables.

The role-existence checks keep the migration compatible with local PostgreSQL installations that do
not define Supabase roles.

## Potential Breaking Changes

- Any undocumented direct use of Supabase REST, GraphQL, or a Supabase client with `anon` or
  `authenticated` credentials will stop working. Repository inspection found no such use.
- If the production backend is changed from the current owner/BYPASSRLS database role to a
  restricted role, it will need explicit grants and server-only RLS policies before that change.
- SQL run manually as `anon` or `authenticated` will no longer access these tables.
- Future frontend features must continue using FastAPI unless a separately reviewed client policy
  model is introduced.

## Rollback Plan

1. Confirm the failure is caused by RLS or privilege changes rather than application authorization.
2. Prefer granting the minimum required privilege to a dedicated backend role over removing RLS.
3. For emergency rollback, run:

   ```powershell
   cd backend
   uv run alembic downgrade 202606080004
   ```

4. Verify FastAPI health, login, tenant isolation, and core CRUD behavior.
5. Treat rollback as temporary: it restores the insecure pre-change Data API exposure.

## Follow-Up Recommendations

- Create a dedicated non-owner backend database role instead of connecting as `postgres`.
- If database-enforced tenant isolation is desired, pass trusted organization context from FastAPI
  into PostgreSQL and design policies around that context. Do not trust client-provided
  `organization_id`.
- Keep Supabase Auth/Data API access disabled unless a specific, reviewed client-access use case is
  introduced.
- Add a deployment check that verifies RLS remains enabled and client grants remain revoked.

## References

- [Supabase Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Supabase Data API Security](https://supabase.com/docs/guides/api/securing-your-api)
