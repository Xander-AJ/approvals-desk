"""Slack approval adapter: outbound interactive messages and inbound button clicks.

Security model (a button click can approve a payout):
- Every inbound request is verified with Slack's signing secret (v0 HMAC) and a 5-minute freshness window.
- A verified click still grants nothing by itself: the Slack user must be mapped to a role in slack_identities.
- Text that originates from customers is escaped so it cannot inject mentions (<!channel>) or links.
- Webhook / response URLs are only ever POSTed to if they are https://hooks.slack.com/... (no SSRF).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx

TOLERANCE_SECONDS = 300
APPROVE_ACTION = "proposal_approve"
REJECT_ACTION = "proposal_reject"


def escape(text: str) -> str:
    """Slack mrkdwn control characters. Without this a customer message could ping @channel or fake a link."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def is_slack_url(url: str) -> bool:
    u = urlparse(url)
    return u.scheme == "https" and u.hostname == "hooks.slack.com" and u.port in (None, 443) and not u.username


def sign(secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def verify_signature(secret: str, timestamp: str | None, signature: str | None, body: bytes,
                     now: float | None = None) -> bool:
    if not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs((now if now is not None else time.time()) - ts) > TOLERANCE_SECONDS:
        return False  # stale: a captured request cannot be replayed later
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


@dataclass(frozen=True)
class ButtonValue:
    action: str  # approve | reject
    tenant_id: uuid.UUID
    proposal_id: uuid.UUID

    def encode(self) -> str:
        return f"{self.action}|{self.tenant_id}|{self.proposal_id}"

    @staticmethod
    def decode(value: str) -> ButtonValue:
        action, tenant, proposal = value.split("|")
        if action not in ("approve", "reject"):
            raise ValueError("bad action")
        return ButtonValue(action, uuid.UUID(tenant), uuid.UUID(proposal))


def proposal_message(tenant_id: uuid.UUID, p: dict[str, Any], console_url: str) -> dict[str, Any]:
    """Block Kit message for a proposal awaiting review. `p` is the outbox payload's proposal snapshot."""
    amount = f"{p['currency']} {Decimal(p['amount']):,.2f}"
    title = f"{p['action_type'].replace('_', ' ').title()} proposal · {amount}"
    pid = uuid.UUID(p["id"])
    evidence = [f"• `{escape(e['source'])}` {escape(e['detail'])}" for e in p.get("evidence", [])[:5]]
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Risk*\n{int(p['risk_score'])}/100"},
            {"type": "mrkdwn", "text": f"*Review by*\n{escape(str(p.get('expires_at') or '—'))}"},
        ]},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Reason*\n{escape(p['reason'])[:1500]}"}},
    ]
    if evidence:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Evidence*\n" + "\n".join(evidence)}})
    blocks.append({"type": "actions", "block_id": f"proposal:{pid}", "elements": [
        {"type": "button", "action_id": APPROVE_ACTION, "style": "primary",
         "text": {"type": "plain_text", "text": "Approve"},
         "value": ButtonValue("approve", tenant_id, pid).encode(),
         "confirm": {"title": {"type": "plain_text", "text": "Approve this payout?"},
                     "text": {"type": "mrkdwn", "text": f"This will execute *{escape(amount)}*."},
                     "confirm": {"type": "plain_text", "text": "Approve"},
                     "deny": {"type": "plain_text", "text": "Cancel"}}},
        {"type": "button", "action_id": REJECT_ACTION, "style": "danger",
         "text": {"type": "plain_text", "text": "Reject"},
         "value": ButtonValue("reject", tenant_id, pid).encode()},
        {"type": "button", "action_id": "open_console", "text": {"type": "plain_text", "text": "Open / edit"},
         "url": f"{console_url.rstrip('/')}/proposals/{pid}"},
    ]})
    return {"text": title, "blocks": blocks}


def decided_message(p_title: str, verb: str, who: str) -> dict[str, Any]:
    """Replaces the interactive message once decided, so a second click has nothing to click."""
    return {"replace_original": True, "text": f"{p_title}: {verb} by {who}",
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{escape(p_title)}*\n{verb} by {escape(who)}"}}]}


async def post(http: httpx.AsyncClient, url: str, body: dict[str, Any]) -> None:
    if not is_slack_url(url):
        raise ValueError("refusing to POST to a non-Slack URL")
    r = await http.post(url, content=json.dumps(body), headers={"Content-Type": "application/json"}, timeout=5)
    r.raise_for_status()
