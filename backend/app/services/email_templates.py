from html import escape

from app.services.email import OutboundEmail


def verification_email(recipient: str, verification_url: str) -> OutboundEmail:
    return build_email(
        recipient,
        "Verify your AgentHQ email",
        "Verify your email to complete your AgentHQ organization setup.",
        verification_url,
        "This link expires in 24 hours.",
    )


def password_reset_email(recipient: str, reset_url: str) -> OutboundEmail:
    return build_email(
        recipient,
        "Reset your AgentHQ password",
        "A password reset was requested for your AgentHQ account.",
        reset_url,
        "This link expires in 30 minutes. Ignore this email if you did not request it.",
    )


def organization_invite_email(
    recipient: str,
    organization_name: str,
    role: str,
    invite_url: str,
    expires_in_days: int,
) -> OutboundEmail:
    return build_email(
        recipient,
        f"Join {organization_name} on AgentHQ",
        f"You have been invited to join {organization_name} as {role.replace('_', ' ')}.",
        invite_url,
        f"This invitation expires in {expires_in_days} days.",
    )


def build_email(
    recipient: str,
    subject: str,
    introduction: str,
    action_url: str,
    footer: str,
) -> OutboundEmail:
    text = f"{introduction}\n\nOpen this secure link:\n{action_url}\n\n{footer}\n\nAgentHQ"
    html = (
        "<div style=\"font-family:Arial,sans-serif;line-height:1.6;color:#0f172a\">"
        "<h2>AgentHQ</h2>"
        f"<p>{escape(introduction)}</p>"
        f"<p><a href=\"{escape(action_url, quote=True)}\">Continue in AgentHQ</a></p>"
        f"<p style=\"font-size:13px;color:#475569\">{escape(footer)}</p>"
        f"<p style=\"font-size:12px;color:#64748b;word-break:break-all\">{escape(action_url)}</p>"
        "</div>"
    )
    return OutboundEmail(
        to=recipient,
        subject=subject,
        text_body=text,
        html_body=html,
    )
