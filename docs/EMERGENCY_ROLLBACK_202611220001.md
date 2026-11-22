# Emergency Backend Rollback: Approval Migration Compatibility

**Branch:** `rollback/v0.8.2-approval-migration-compat`

This branch is a temporary recovery artifact. Do not deploy it except to recover a failed
production backend after migration `202611220001`, and replace it with a fixed release as soon as
possible.

## What it is

The previous production backend `d232bc7` with only two additions from release `bc8002c`:

* the Alembic revision `202611220001_single_use_approvals.py`, so the container's
  `alembic upgrade head` succeeds on a database already at `202611220001` (it is a no-op there);
* the `approval.consumed` audit action, so reading audit records written by the new release does
  not fail.

No other code changes. The database schema is the same as release `bc8002c`.

## What it lacks

**This build does not enforce single-use or risk-bound approvals.** It ignores
`approvals.consumed_at`: any `approved` approval authorizes unlimited gateway calls again,
including approvals already consumed, and an approval of lower risk than the tool is accepted.
This is the P1 governance defect that `bc8002c` fixes.

While this build is running, contain the exposure:

* Do not approve new requests for tools whose repeated execution would cause harm.
* Prefer revoking the affected gateway tokens or blocking the affected tools with a `block`
  policy rule until the fixed release is back.

## Why it is needed

Release `bc8002c` adds migration `202611220001`. Every older backend, including `d232bc7`, fails
to start against that revision, because `alembic upgrade head` cannot locate it. Never run
`alembic downgrade` on production.

## Use

1. Only on explicit authorization by the accountable operator, with the reason recorded.
2. Deploy this branch's commit from GitHub to the Railway API service (same method as a release).
3. Confirm the startup log shows Alembic with no `Running upgrade` line and `/health` returns
   `200`.
4. Keep the frontend unchanged: the API is backward compatible with it.
5. Return to a fixed release as soon as possible. Approvals consumed under the fixed release stay
   consumed; nothing needs restoring.
