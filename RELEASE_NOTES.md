# AgentHQ v0.2.0 — MCP Server Registration & Tool Discovery

AgentHQ v0.2.0 expands the governance platform with MCP server registration and adapter-based tool discovery.

## Highlights

* Added MCP Server Registration
* Added MCP Tool Discovery via adapter-based discovery
* Added linked agent creation during sync
* Added idempotent tool sync
* Added MCP sync audit logs
* Added MCP server dashboard counts
* Increased automated test coverage to 170 passing tests

## MCP Registration

Registered MCP servers track connection status, linked agents, synchronization timestamps, and the latest discovery error. Soft-deleted servers remain excluded from active registry results and dashboard counts.

## Tool Discovery

The v0.2.0 discovery flow uses a mock/local adapter behind an interface designed for future real MCP clients. Successful synchronization creates or reuses a linked agent and upserts discovered tools into the Agent Tools Registry.

Repeated synchronization does not duplicate tools. Discovery can update tool descriptions while preserving manually governed permission and risk-level settings.

## Auditability

AgentHQ records `mcp_server.synced` and `mcp_server.sync_failed` audit events with structured before/after snapshots.

## Verification

* 170 automated backend tests passing
* Ruff clean
* MyPy clean
* MCP migrations verified against PostgreSQL

# AgentHQ v0.3.0 — Authentication & RBAC

AgentHQ v0.3.0 introduces enterprise identity, authentication, and role-based access control across the governance platform.

## Highlights

* JWT Authentication
* User Management
* Role-Based Access Control
* Agent Ownership Enforcement
* Protected Governance Endpoints
* Dashboard User Metrics
* 183 Automated Tests Passing

## Authentication

Users can register, sign in, persist an access token, load their current identity, and sign out through the AgentHQ frontend. Passwords are hashed with Argon2 and are never stored as plaintext.

## Role-Based Access Control

AgentHQ supports Admin, Auditor, Operator, and Agent Owner roles. Governance endpoints enforce role permissions, while agent owners can access and manage only agents assigned to their email identity.

## Protected Governance

RBAC protects policy rules, MCP servers, audit logs, compliance reports, executions, incidents, agent management, and administrative user management.

## Dashboard

The dashboard summary now reports total users and active users.

## Verification

* 183 automated backend tests passing
* Ruff clean
* MyPy clean
* Frontend build and lint passing
* Live frontend and backend deployment

# AgentHQ v0.3.2 — Reliability & Performance Hardening

## Highlights

### Reliability

* Added service-owned atomic transactions
* Added rollback tests for critical governance flows
* Eliminated partial-state risks for key operations

### Performance

* Added pagination across all major list endpoints
* Added 16 PostgreSQL indexes
* Optimized dashboard aggregates
* Optimized compliance reporting
* Added query-count regression tests

### Quality

* 201 automated tests passing
* Ruff clean
* MyPy clean

## Metrics

Dashboard Summary:
24 → 6 queries

Compliance Summary:
10 → 5 queries

Agent Compliance Report:
10 → 2 queries
