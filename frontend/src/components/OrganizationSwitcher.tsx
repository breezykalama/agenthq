import { useId, useState } from "react";
import { useNavigate } from "react-router-dom";

import { getErrorMessage } from "../api/client";
import { useAuth } from "../auth/context";
import { getSelectedMembership } from "../auth/roles";
import { formatRole } from "../utils/format";

/**
 * Current organization and role; a selector when the account has several memberships.
 * Switching goes through the auth context, which re-confirms the choice with the backend,
 * discards the previous organization's cache and remounts the workspace.
 */
export function OrganizationSwitcher() {
  const { user, memberships, selectedOrganizationId, selectOrganization } = useAuth();
  const navigate = useNavigate();
  const selectId = useId();
  const [error, setError] = useState<string | null>(null);
  const [isSwitching, setIsSwitching] = useState(false);
  const selected = getSelectedMembership(user);

  if (!selected) return null;
  const identity = `${selected.organization.name} · ${formatRole(selected.role)}`;

  if (memberships.length < 2) {
    return (
      <div className="mt-0.5 inline-flex max-w-full truncate rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
        {identity}
      </div>
    );
  }

  async function switchTo(organizationId: string) {
    if (organizationId === selectedOrganizationId) return;
    setIsSwitching(true);
    setError(null);
    try {
      await selectOrganization(organizationId);
      navigate("/dashboard", { replace: true });
    } catch (caught) {
      setError(getErrorMessage(caught));
      setIsSwitching(false);
    }
  }

  return (
    <div className="mt-0.5 flex min-w-0 items-center gap-2">
      <label htmlFor={selectId} className="sr-only">
        Organization
      </label>
      <select
        id={selectId}
        value={selected.organization_id}
        disabled={isSwitching}
        onChange={(event) => void switchTo(event.target.value)}
        className="max-w-full truncate rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-xs text-slate-700 focus:border-slate-900 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:opacity-60"
      >
        {memberships.map((membership) => (
          <option key={membership.organization_id} value={membership.organization_id}>
            {membership.organization.name} {"·"} {formatRole(membership.role)}
          </option>
        ))}
      </select>
      {error ? (
        <span role="alert" className="truncate text-xs text-rose-700">
          {error}
        </span>
      ) : null}
    </div>
  );
}
