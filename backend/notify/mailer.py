"""
Email notifications (SMTP).

Used by the scheduler to send alarms when a scheduled Beat-Price / Find-Product
search returns results matching a user-defined rule (e.g. price < $27 and match
>= 80%). Reads SMTP settings from config/settings.yaml `email.*`.

Configuration is intentionally fail-soft: if SMTP isn't configured the functions
log a warning and return a (False, reason) result rather than raising, so a
misconfigured mail server never breaks a scheduled job.
"""
import logging
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import List, Optional, Tuple

from backend.config import config

logger = logging.getLogger(__name__)


def email_settings() -> dict:
    """Current SMTP settings (password redaction is the caller's job)."""
    return {
        "enabled": bool(config.get("email", "enabled", default=False)),
        "smtp_host": config.get("email", "smtp_host", default="") or "",
        "smtp_port": int(config.get("email", "smtp_port", default=587) or 587),
        "smtp_use_tls": bool(config.get("email", "smtp_use_tls", default=True)),
        "smtp_user": config.get("email", "smtp_user", default="") or "",
        "smtp_password": config.get("email", "smtp_password", default="") or "",
        "from_address": config.get("email", "from_address", default="") or "",
        "to_addresses": config.get("email", "to_addresses", default=[]) or [],
    }


def is_configured() -> bool:
    s = email_settings()
    return bool(s["enabled"] and s["smtp_host"] and s["from_address"])


def send_email(
    subject: str,
    body: str,
    recipients: List[str],
    html: Optional[str] = None,
) -> Tuple[bool, str]:
    """Send a plain-text (optionally multipart HTML) email.

    Returns (ok, detail). Never raises on misconfiguration or SMTP failure —
    the failure reason is returned so the caller can record it.
    """
    s = email_settings()
    recipients = [r.strip() for r in (recipients or []) if r and r.strip()]
    if not recipients:
        return False, "no recipients"
    if not s["enabled"]:
        return False, "email disabled in settings"
    if not s["smtp_host"] or not s["from_address"]:
        return False, "SMTP host / from_address not configured"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("domainComp", s["from_address"]))
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        if s["smtp_use_tls"]:
            server = smtplib.SMTP(s["smtp_host"], s["smtp_port"], timeout=30)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(s["smtp_host"], s["smtp_port"], timeout=30)
        try:
            if s["smtp_user"]:
                server.login(s["smtp_user"], s["smtp_password"])
            server.send_message(msg)
        finally:
            server.quit()
        logger.info("Sent notification email to %s: %s", recipients, subject)
        return True, f"sent to {len(recipients)} recipient(s)"
    except Exception as exc:  # noqa: BLE001 - report any SMTP error back to caller
        logger.warning("Email send failed: %s", exc)
        return False, f"smtp error: {exc}"
