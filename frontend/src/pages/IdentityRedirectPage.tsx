import { Navigate } from "react-router-dom";

import { captureIdentityToken } from "../utils/identityTokens";

/**
 * Compatibility routes (/verify-email, /reset-password, /forgot-password). Any token in the
 * link is captured and stripped before redirecting, so it never reaches the landing-page URL.
 */
export function IdentityRedirectPage({
  mode
}: {
  mode: "verify-email" | "reset-password" | "forgot-password";
}) {
  if (mode !== "forgot-password") {
    captureIdentityToken(mode);
  }
  return <Navigate replace to={`/?auth=${mode}`} />;
}
