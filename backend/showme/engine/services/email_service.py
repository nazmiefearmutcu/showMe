"""SMTP-based email dispatcher for BRIEF + ALRT.

ENV:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
"""

from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable


def _smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER")
                and os.environ.get("SMTP_PASSWORD"))


def send_email(
    *,
    to: str | list[str],
    subject: str,
    html: str | None = None,
    text: str | None = None,
    attachments: Iterable[tuple[str, bytes, str]] = (),
) -> bool:
    """Send a multipart MIME email. Returns True on success.

    ``attachments`` is an iterable of (filename, content_bytes, mimetype).
    Supports plain text + HTML alternative.
    """
    if not _smtp_configured():
        return False
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    pw = os.environ["SMTP_PASSWORD"]
    sender = os.environ.get("SMTP_FROM", user)
    recipients = [to] if isinstance(to, str) else list(to)

    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    if html:
        msg.attach(MIMEText(html, "html", "utf-8"))
    for fname, content, mt in attachments:
        from email.mime.application import MIMEApplication
        part = MIMEApplication(content, _subtype=mt.split("/")[-1])
        part.add_header("Content-Disposition", "attachment", filename=fname)
        msg.attach(part)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as s:
                s.login(user, pw)
                s.sendmail(sender, recipients, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls()
                s.login(user, pw)
                s.sendmail(sender, recipients, msg.as_string())
        return True
    except Exception:
        return False
