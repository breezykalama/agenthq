/** User-facing outcomes of an invitation acceptance attempt (see AcceptInvitePage). */
export const INVITE_MESSAGES = {
  invalid:
    "This invitation is invalid, expired, revoked, or has already been accepted. Ask your organization administrator for a new invitation.",
  invalidAfterUnknown:
    "This invitation can no longer be used. An earlier attempt may already have accepted it before the connection was interrupted. Sign in with the invited email address and the password you entered. If you can't sign in, ask your organization administrator for a new invitation.",
  notSent:
    "Your sign-in changed in another tab, so this attempt to accept the invitation was not submitted. You can try again.",
  unknown:
    "We couldn't confirm whether your invitation was accepted. The connection was interrupted or your sign-in changed in another tab, so it may already have gone through. Sign in with the invited email address and the password you entered here. If that doesn't work, try accepting the invitation again.",
  alreadyMember:
    "This account is already a member of the organization that invited you. Sign in to continue.",
  multipleOrganizations:
    "This account already belongs to another organization, and joining a second organization isn't supported yet. Your invitation has not been used. Contact the administrator who invited you."
} as const;
