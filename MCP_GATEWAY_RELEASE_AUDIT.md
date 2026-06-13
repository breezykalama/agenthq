# AgentHQ v0.6.0 MCP Gateway Pre-Release Audit

Audit scope: gateway token management, governed tool listing, REST gateway calls, upstream MCP
execution, approval enforcement, tenant isolation, idempotency, rate limiting, audit events,
frontend token handling, and release documentation.

## Executive Summary

The AgentHQ MCP Gateway has a strong security foundation:

* Gateway tokens are high-entropy, hashed at rest, server-scoped, revocable, and returned only on
  creation or rotation.
* Cross-organization and cross-server access is rejected before governed resources are returned.
* Unreviewed, disabled, soft-deleted, and non-executable tools cannot be called.
* Policy failures fail closed.
* Blocked and approval-required calls do not reach the upstream MCP server.
* Upstream redirects are disabled, URL safety is revalidated, timeouts are bounded, and exception
  details are sanitized.
* Direct-upstream bypass limitations are clearly documented.

The gateway is **not safe to release for side-effecting production tools yet**. Two release-blocking
integrity risks remain:

1. Idempotency is checked and persisted around, rather than before, the upstream side effect.
   Concurrent requests or a database failure after an upstream success can execute the same tool
   more than once.
2. An approval is bound only to organization, agent, approved status, and tool-name action. It is
   not bound to risk level, input payload, amount, expiry/use count, or a specific execution.

## Critical Findings

### 1. Idempotency Does Not Prevent Concurrent or Post-Commit-Failure Duplicate Calls

Current behavior:

* The gateway checks for an existing idempotency record.
* If none exists, it calls the upstream MCP tool.
* Only after the upstream call returns does it create the unique idempotency record and commit.

Risks:

* Two concurrent requests with the same token, tool, and idempotency key can both pass the initial
  lookup and both call upstream before one loses the unique-index race.
* If upstream succeeds but the database commit fails, a client retry sees no idempotency record and
  calls upstream again.
* This can duplicate payments, tickets, account updates, or other irreversible side effects.
* Reusing an idempotency key with a different input payload silently returns the previous execution
  response because no request hash is stored or compared.

Required before production release:

* Reserve the idempotency key transactionally before calling upstream.
* Store a deterministic request hash containing token scope, server, tool, approval, and canonical
  input payload.
* Reject reuse of a key with a different request hash.
* Represent `in_progress`, `completed`, and `failed/unknown` states.
* Define recovery behavior for upstream-success/database-failure ambiguity.
* Prefer forwarding the idempotency key upstream when the MCP tool/server supports it.

### 2. Approval Reuse Can Authorize Materially Different Tool Inputs

Current approval validation checks:

* Approval belongs to the current organization through the tenant-scoped repository.
* Approval belongs to the same agent.
* Approval status is approved.
* `requested_action` exactly matches the tool name.

Missing binding:

* Approval risk level is not compared with the tool risk level.
* Approval is not bound to `tool_id`.
* Approval is not bound to the input payload or a payload hash.
* Approval has no use limit or gateway-specific expiry.
* An approved action can be reused indefinitely for different inputs.

Example risk:

An approval for `transfer_funds` can be reused for a different account or materially larger amount.
A low-risk approval with the same action name can authorize a high- or critical-risk tool call.

Required before production release:

* Require approval risk to be equal to or higher than the tool risk.
* Bind gateway approvals to a specific tool and canonical request hash.
* Prefer single-use approvals for side-effecting calls.
* Record consumption atomically with the gateway execution.
* If reusable approvals remain supported, add explicit scope, expiry, use-count, and maximum-risk
  fields.

## High Priority Findings

### 1. Durable Audit Trail Starts Too Late for Upstream Calls

`policy_decision.evaluated` and `mcp_gateway.call_requested` are flushed but committed only after
the upstream call returns and the final execution/audit records are written.

If the process crashes, the request times out externally, or the database commit fails after the
upstream call, AgentHQ may have no durable record of the attempted or completed upstream action.
This also compounds the idempotency ambiguity.

Recommendation:

* Persist a gateway request/execution intent before calling upstream.
* Mark it `running` or `in_progress`.
* Finalize the execution and outcome audit after the upstream response.
* Reconcile abandoned in-progress calls operationally.

### 2. Invalid Gateway Tokens Are Neither Rate Limited Nor Audited

Gateway rate limiting runs only after a gateway token has authenticated. Invalid, revoked, expired,
or cross-server token attempts return `401` before rate limiting and without a security audit event.

The token entropy makes brute-force token discovery impractical, but unrestricted invalid-token
requests can still create database load and leave no security trail.

Recommendation:

* Add an IP-based pre-authentication limit for gateway endpoints.
* Add safe security logging for invalid gateway-token attempts without logging token values.
* Use a hashed token fingerprint only if correlation is needed.

### 3. Gateway Inputs and Upstream Results Are Unbounded and Schema-Unvalidated

Current behavior:

* `input_payload` accepts arbitrary JSON objects and is not validated against the discovered MCP
  input schema.
* No application request-body size limit is configured.
* The complete upstream MCP result is materialized in memory and returned to the gateway client.
* Result size and sensitive-content handling are not bounded.

Positive control:

* Full input/output payloads are not stored in executions or audit logs; only field-name summaries
  are persisted.
* Raw upstream errors are sanitized.

Recommendation:

* Enforce request-body and upstream-result size limits.
* Validate input against the stored MCP input schema before calling upstream.
* Define content-type and sensitive-output handling rules.
* Consider returning a bounded/truncated result or rejecting oversized upstream responses.

## Medium Priority Findings

### 1. Gateway Token One-Time Display Needs Additional Cache and UI Controls

Positive controls:

* Raw tokens are generated with strong randomness.
* Only SHA-256 hashes are persisted.
* Token list responses exclude raw tokens and hashes.
* Audit metadata uses token IDs, not raw tokens.
* Gateway calls use an isolated Axios client and do not persist gateway tokens to local storage.

Remaining risks:

* Create/rotate token responses do not set `Cache-Control: no-store`.
* The frontend keeps the raw token in component state and visibly renders it until the panel closes
  or another token replaces it.
* Copying places the token in the operating-system clipboard.
* Central audit redaction does not recognize the `aghq_...` token pattern if a future code path
  accidentally logs it under a non-sensitive key.

Recommendation:

* Add `Cache-Control: no-store` to token create/rotate responses.
* Add an explicit "Hide token" action and clear raw token state after use or panel close.
* Warn users about clipboard history.
* Extend centralized redaction to recognize gateway-token values.

### 2. Audit Coverage Omits Several Denied Gateway Attempts

Current audited events include token lifecycle, successful tool listing, requested calls, policy
outcomes, upstream failures, execution creation, invalid approvals, idempotent replays, and rate
limits after authentication.

Missing or incomplete events:

* Invalid, expired, revoked, and cross-server gateway token attempts.
* Calls to unavailable, unreviewed, disabled, or non-executable tools.
* Gateway info access.
* `call_requested` is not durable before upstream execution.

Recommendation:

* Add safe pre-auth security events/logs.
* Audit authenticated denied tool-call attempts.
* Decide whether gateway info access is security-relevant and document that decision.

### 3. Gateway Rate Limits Can Be Distributed Across Tools and Tokens

Current limits are keyed by organization, token, and resource:

* Tool listing is limited per token/server.
* Tool calls are limited per token/tool.
* Token management is limited for authenticated administrators.
* Production fails closed if Redis is unavailable.
* `429` responses include `Retry-After` and create security audit events after authentication.

Remaining risks:

* A client can distribute calls across many tools.
* Multiple active tokens increase the aggregate organization call allowance.
* Invalid-token traffic is not rate limited.

Recommendation:

* Add organization-wide gateway call limits in addition to token/tool limits.
* Add IP-based pre-authentication limits.
* Monitor token creation count and active-token volume per server.

## Low Priority Findings

### 1. Gateway Token Expiry Is Optional and Has No Maximum Lifetime

Tokens may be created without expiry. Revocation and rotation exist, but long-lived credentials
increase exposure if copied or leaked.

Recommendation:

* Provide a secure default expiry.
* Set a configurable maximum token lifetime.
* Surface expiring and stale tokens in the UI.

### 2. Idempotent Replay Intentionally Omits the Previous Full Result

This is documented and reduces sensitive-data retention. Clients must be prepared to receive the
previous execution status and summary without the original tool output.

Recommendation:

* Keep this behavior, but make it explicit in the API documentation and client integration guide.

## Area Assessment

| Audit Area | Assessment |
| --- | --- |
| Gateway token leakage | Strong baseline; add no-store, UI clearing, and gateway-token redaction pattern. |
| Idempotency correctness | **Release blocker** for side-effecting tools. |
| Approval bypass | **Release blocker** for high-risk or payload-sensitive tools. |
| Cross-tenant bypass | No bypass found; server, organization, agent, and tool scope checks are strong. |
| Upstream direct bypass documentation | Clearly documented in README, deployment guidance, and UI. |
| Safe result/error handling | Errors and persisted summaries are safe; raw result size/content remains unbounded. |
| Rate-limit behavior | Valid-token and management paths are protected; invalid-token and aggregate-org gaps remain. |
| Audit completeness | Broad event coverage, but pre-auth denials and durable pre-upstream intent are missing. |

## Positive Security Controls

* Strong random gateway-token generation.
* Only token hashes stored.
* Raw token returned only on create/rotate.
* Token rotation invalidates the previous token.
* Revoked and expired tokens rejected.
* Token scoped to one MCP server and organization.
* Tenant-scoped server, tool, policy, approval, execution, and audit queries.
* Unreviewed, disabled, soft-deleted, and non-executable tools rejected.
* Policy evaluation fails closed.
* Block and approval-required decisions do not call upstream.
* Approval must be approved, tenant-scoped, same-agent, and action-name compatible.
* URL safety validation, credential-free URLs, backend-only auth references, disabled redirects, and
  bounded transport timeouts.
* Raw upstream exceptions are not returned or stored.
* Execution input/output persistence contains only field-name summaries.
* Gateway audit metadata contains token IDs rather than raw tokens.
* Production rate limiting fails closed without Redis.
* Supabase RLS lockdown included for gateway tables.
* Direct-upstream bypass limitation clearly documented and displayed in the UI.

## Recommended Fix Order

1. Make idempotency reservation concurrency-safe and bind it to a canonical request hash.
2. Bind approvals to tool, risk, payload/request hash, expiry, and consumption policy.
3. Persist gateway call intent before invoking upstream and finalize it afterward.
4. Add pre-auth IP rate limiting and safe invalid-token security events.
5. Add input-schema validation and request/result size limits.
6. Add token response no-store headers, UI clearing, and gateway-token-pattern redaction.
7. Add organization-wide aggregate gateway limits and complete denied-attempt auditing.

## Final Recommendation

**Not safe to release for production side-effecting MCP tools yet.**

The gateway is suitable for controlled development and read-only/non-destructive tool testing.
Resolve the idempotency and approval-binding release blockers before enabling payment, customer-data
mutation, ticket creation, or other irreversible production tools.
