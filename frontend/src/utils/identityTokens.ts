/**
 * Single-use identity tokens (email verification, password reset, invitations) arrive in
 * emailed links. Links put the token in the URL fragment (`#token=`), which browsers never
 * send to the server, in Referer headers, or to third parties. Legacy `?token=` links are
 * still accepted.
 *
 * As soon as a token is read it is removed from the address bar with `history.replaceState`,
 * so it does not stay in browser history, bookmarks, screenshots, or later navigations. It is
 * kept in sessionStorage (this tab only, cleared when the tab closes) so a page refresh still
 * works. It is cleared once the action succeeds.
 */

export type IdentityTokenPurpose = "invite" | "verify-email" | "reset-password";

const storageKey = (purpose: IdentityTokenPurpose) => `agenthq.identity-token.${purpose}`;

function readStored(purpose: IdentityTokenPurpose): string {
  try {
    return window.sessionStorage.getItem(storageKey(purpose)) ?? "";
  } catch {
    return "";
  }
}

function store(purpose: IdentityTokenPurpose, token: string): void {
  try {
    window.sessionStorage.setItem(storageKey(purpose), token);
  } catch {
    // Storage unavailable (private mode or blocked). The token stays in memory only.
  }
}

/** Read a token from the current URL (fragment first, then query), strip it, and remember it. */
export function captureIdentityToken(purpose: IdentityTokenPurpose): string {
  const url = new URL(window.location.href);
  const fragment = new URLSearchParams(url.hash.startsWith("#") ? url.hash.slice(1) : url.hash);
  const token = fragment.get("token") ?? url.searchParams.get("token");

  if (fragment.has("token") || url.searchParams.has("token")) {
    fragment.delete("token");
    url.searchParams.delete("token");
    const remainingFragment = fragment.toString();
    url.hash = remainingFragment ? `#${remainingFragment}` : "";
    window.history.replaceState(window.history.state, "", url.toString());
  }

  if (token) {
    store(purpose, token);
    return token;
  }
  return readStored(purpose);
}

export function clearIdentityToken(purpose: IdentityTokenPurpose): void {
  try {
    window.sessionStorage.removeItem(storageKey(purpose));
  } catch {
    // Nothing stored.
  }
}
