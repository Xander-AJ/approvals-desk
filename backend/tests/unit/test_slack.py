import json
import time
import uuid

import httpx
import pytest

from app.integrations import slack

SECRET = "slack-signing-secret"
TENANT, PID = uuid.uuid4(), uuid.uuid4()
BODY = b"payload=%7B%7D"


def _sig(ts: str, body: bytes = BODY, secret: str = SECRET) -> str:
    return slack.sign(secret, ts, body)


def test_valid_signature_accepted() -> None:
    ts = str(int(time.time()))
    assert slack.verify_signature(SECRET, ts, _sig(ts), BODY)


def test_signature_matches_slacks_documented_example() -> None:
    # Example from Slack's "Verifying requests" docs.
    secret = "8f742231b10e8888abcd99yyyzzz85a5"
    ts = "1531420618"
    body = (b"token=xyzz0WbapA4vBCDEFasx0q6G&team_id=T1DC2JH3J&team_domain=testteamnow&channel_id=G8PSS9T3V&"
            b"channel_name=foobar&user_id=U2CERLKJA&user_name=roadrunner&command=%2Fwebhook-collect&text=&"
            b"response_url=https%3A%2F%2Fhooks.slack.com%2Fcommands%2FT1DC2JH3J%2F397700885554%2F96rGlfmibIGlgcZRskXaIFfN&"
            b"trigger_id=398738663015.47445629121.803a0bc887a14d10d2c447fce8b6703c")
    expected = "v0=a2114d57b48eac39b9ad189dd8316235a7b4a8d21a10bd27519666489c69b503"
    assert slack.sign(secret, ts, body) == expected
    assert slack.verify_signature(secret, ts, expected, body, now=1531420618 + 10)


@pytest.mark.parametrize("mutate", ["body", "secret", "sig", "missing_ts", "missing_sig", "bad_ts", "stale", "future"])
def test_invalid_or_stale_signature_rejected(mutate: str) -> None:
    now = int(time.time())
    ts, body, secret = str(now), BODY, SECRET
    sig = _sig(ts)
    if mutate == "body":
        body = b"payload=tampered"
    elif mutate == "secret":
        secret = "other"
    elif mutate == "sig":
        sig = sig[:-2] + "00"
    elif mutate == "missing_ts":
        assert not slack.verify_signature(secret, None, sig, body)
        return
    elif mutate == "missing_sig":
        assert not slack.verify_signature(secret, ts, None, body)
        return
    elif mutate == "bad_ts":
        assert not slack.verify_signature(secret, "not-a-number", sig, body)
        return
    elif mutate == "stale":
        ts = str(now - 301)
        sig = _sig(ts)
    elif mutate == "future":
        ts = str(now + 301)
        sig = _sig(ts)
    assert not slack.verify_signature(secret, ts, sig, body, now=now)


@pytest.mark.parametrize("url,ok", [
    ("https://hooks.slack.com/services/T0/B0/xyz", True),
    ("https://hooks.slack.com/actions/T0/1/abc", True),
    ("http://hooks.slack.com/services/T0/B0/xyz", False),
    ("https://hooks.slack.com.evil.com/services/x", False),
    ("https://evil.com/hooks.slack.com", False),
    ("https://user@hooks.slack.com/services/x", False),
    ("https://hooks.slack.com:8443/services/x", False),
    ("https://169.254.169.254/latest/meta-data", False),
    ("file:///etc/passwd", False),
    ("", False),
])
def test_only_real_slack_urls_are_ever_posted_to(url: str, ok: bool) -> None:
    assert slack.is_slack_url(url) is ok


async def test_post_refuses_non_slack_url_without_sending() -> None:
    sent: list[httpx.Request] = []
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (sent.append(r), httpx.Response(200))[1]))
    with pytest.raises(ValueError):
        await slack.post(http, "http://169.254.169.254/x", {})
    assert sent == []


def _proposal(**over: object) -> dict[str, object]:
    return {"id": str(PID), "action_type": "refund", "amount": "1200.00", "currency": "KES",
            "reason": "double charge at Java House", "risk_score": 10, "expires_at": "2026-09-30T10:00:00+00:00",
            "evidence": [{"source": "ledger", "detail": "charge t1 of 1200"}], **over}


def test_message_has_approve_reject_and_console_link_with_signed_free_context() -> None:
    msg = slack.proposal_message(TENANT, _proposal(), "https://console.example.com/")  # type: ignore[arg-type]
    actions = next(b for b in msg["blocks"] if b["type"] == "actions")
    by_id = {e["action_id"]: e for e in actions["elements"]}
    assert by_id["proposal_approve"]["value"] == f"approve|{TENANT}|{PID}"
    assert by_id["proposal_reject"]["value"] == f"reject|{TENANT}|{PID}"
    assert by_id["open_console"]["url"] == f"https://console.example.com/proposals/{PID}"
    assert "confirm" in by_id["proposal_approve"]  # payout needs a second click
    assert "KES 1,200.00" in msg["text"]
    assert slack.ButtonValue.decode(by_id["proposal_approve"]["value"]).proposal_id == PID


def test_customer_supplied_text_cannot_inject_mentions_links_or_markup() -> None:
    evil = "<!channel> click <https://evil.example|here> &amp; <@U123>"
    msg = slack.proposal_message(TENANT, _proposal(reason=evil, evidence=[{"source": "x<", "detail": evil}]), "https://c")  # type: ignore[arg-type]
    text = json.dumps(msg)
    assert "<!channel>" not in text and "<@U123>" not in text and "<https://evil" not in text
    assert "&lt;!channel&gt;" in text


@pytest.mark.parametrize("bad", ["approve|x|y", "delete|" + str(TENANT) + "|" + str(PID), "approve|a", ""])
def test_malformed_button_values_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        slack.ButtonValue.decode(bad)
