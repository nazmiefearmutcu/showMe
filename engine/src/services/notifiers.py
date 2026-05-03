"""Outbound notifier integrations for ALRT engine.

Slack:    incoming webhook URL — set SLACK_WEBHOOK_URL.
Discord:  webhook URL          — set DISCORD_WEBHOOK_URL.
Telegram: bot token + chat_id  — set TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
PagerDuty: integration key     — set PAGERDUTY_ROUTING_KEY (Events API v2).

Each notifier is a plain callable: ``notifier(event: dict) → None`` that
swallows its own errors and logs.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any


_log = logging.getLogger("showme.notifiers")


def _post(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None,
          timeout: float = 8.0) -> bool:
    try:
        body = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                       headers={"Content-Type": "application/json",
                                                **(headers or {})})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status < 400
    except Exception as e:
        _log.warning("notifier post failed (%s): %s", url[:60], e)
        return False


def _format_event(event: dict[str, Any]) -> str:
    cond = event.get("condition") or "alert"
    ctx = event.get("context") or {}
    sym = ctx.get("symbol", "?")
    field = ctx.get("field", "?")
    op = ctx.get("op", "?")
    val = ctx.get("value", "?")
    th = ctx.get("threshold", "?")
    actions = ", ".join(event.get("actions") or []) or "—"
    ts = event.get("ts", "")
    return f"🔔 *ShowMe Alert*\n`{cond}`\n{sym}.{field} = `{val}` {op} `{th}`\nactions: {actions}\n{ts}"


def slack_notifier(event: dict[str, Any]) -> bool:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return False
    text = _format_event(event)
    return _post(url, {"text": text})


def discord_notifier(event: dict[str, Any]) -> bool:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return False
    text = _format_event(event)
    return _post(url, {"content": text})


def telegram_notifier(event: dict[str, Any]) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    text = _format_event(event)
    return _post(f"https://api.telegram.org/bot{token}/sendMessage",
                  {"chat_id": chat, "text": text, "parse_mode": "Markdown"})


def pagerduty_notifier(event: dict[str, Any]) -> bool:
    """Emit a PagerDuty Events API v2 trigger."""
    routing_key = os.environ.get("PAGERDUTY_ROUTING_KEY")
    if not routing_key:
        return False
    cond = event.get("condition") or "ShowMe alert"
    payload = {
        "routing_key": routing_key,
        "event_action": "trigger",
        "payload": {
            "summary": cond,
            "severity": "warning",
            "source": "ShowMe",
            "custom_details": event,
        },
    }
    return _post("https://events.pagerduty.com/v2/enqueue", payload)


def all_configured_notifiers() -> list[Any]:
    """Returns the list of notifier callables whose env vars are set."""
    out: list[Any] = []
    if os.environ.get("SLACK_WEBHOOK_URL"):
        out.append(slack_notifier)
    if os.environ.get("DISCORD_WEBHOOK_URL"):
        out.append(discord_notifier)
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        out.append(telegram_notifier)
    if os.environ.get("PAGERDUTY_ROUTING_KEY"):
        out.append(pagerduty_notifier)
    return out
