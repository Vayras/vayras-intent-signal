from __future__ import annotations

import re
import smtplib

try:
    import dns.resolver
except ImportError:  # pragma: no cover
    dns = None  # type: ignore


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailCheckProvider:
    """DNS/MX, then a basic SMTP RCPT check. Never guesses a mailbox."""

    name = "DNS/MX+SMTP"

    def check(self, email: str | None) -> str:
        if not email or not EMAIL_RE.match(email):
            return "missing"
        domain = email.rsplit("@", 1)[-1]
        if dns is None:
            return "unverified"
        try:
            answers = list(dns.resolver.resolve(domain, "MX"))
        except Exception:
            return "unverified"
        if not answers:
            return "no_mx"
        mx = str(sorted(answers, key=lambda row: row.preference)[0].exchange).rstrip(".")
        return _smtp_rcpt(email, mx) or "mx_ok"


def _smtp_rcpt(email: str, mx_host: str) -> str:
    # ponytail: port 25 is often blocked; mx_ok is the fallback
    try:
        with smtplib.SMTP(timeout=8) as smtp:
            smtp.connect(mx_host, 25)
            smtp.helo("intent-radar.local")
            smtp.mail("verify@intent-radar.local")
            code, _ = smtp.rcpt(email)
            smtp.quit()
        if code == 250:
            return "smtp_ok"
        if code in {550, 551, 553}:
            return "smtp_reject"
    except Exception:
        return ""
    return ""
