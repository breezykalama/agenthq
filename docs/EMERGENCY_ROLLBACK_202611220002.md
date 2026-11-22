# Emergency Backend Recovery: Idempotency Migration Compatibility

**Branch:** `rollback/v0.8.2-idempotency-migration-compat`

This branch is a temporary recovery artifact. Deploy it only to recover a failed production
backend after migration `202611220002`, and replace it with a fixed release as soon as possible.

## What it is

The single-use approval release `bc8002c` with only one addition from release `b8c0f59`: the
Alembic revision `202611220002_gateway_idempotency_reservation.py`, so the container's
`alembic upgrade head` succeeds on a database already at `202611220002` (it is a no-op there).

It keeps everything in `bc8002c`, including the `202611220001` single-use, risk-bound approval
enforcement. The database schema is the same as release `b8c0f59`.

## What it lacks

**This build does not reserve idempotency keys before dispatch.** It checks for a recorded key
before calling the upstream MCP server and records the key only afterwards, so concurrent
requests with the same key can each call the upstream tool. This is the P1 race that
`b8c0f59` fixes.

**Do not run it with side-effecting gateway execution enabled.** While it is deployed:

* Block side-effecting gateway tools with `block` policy rules, or revoke the gateway
  credentials that can call them, until the fixed release is restored.
* Approval-gated calls remain single use (each approval authorizes one call), but calls that
  do not require approval have no duplicate protection.

Records written by the fixed release stay valid: completed records replay. A record left
`in_progress` by the fixed release has no stored response; this build answers a repeat of that
key with a server error and does not call the upstream server.

## Why it is needed

Release `b8c0f59` adds migration `202611220002`. Older backends, including `bc8002c` and the
earlier recovery build `a96e211`, fail to start against that revision because
`alembic upgrade head` cannot locate it. Never run `alembic downgrade` on production.

## Use

1. Only on explicit authorization by the accountable operator, with the reason recorded.
2. First block or revoke side-effecting gateway execution (see above).
3. Deploy this branch's commit from GitHub to the Railway API service.
4. Confirm the startup log shows Alembic with no `Running upgrade` line and `/health` returns
   `200`.
5. Keep the frontend unchanged.
6. Restore a release that includes `b8c0f59` as soon as possible, then lift the temporary
   blocks.
