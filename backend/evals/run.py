"""Evals on *proposals*, not replies. Usage: python -m evals.run [--min-accuracy 0.9] [--max-violations 0]

Metrics
- proposal_accuracy: action type + amount (or correct abstention) match the label
- policy_violation_rate: an auto-approved proposal that policy labels review/block. Must be 0.
- unnecessary_escalation_rate: sent to review when the label says auto_approve
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal

from app.agent.fake_llm import FakeLLM
from app.agent.llm import LLM
from app.agent.policy import evaluate, is_tampered, verify_claim
from evals.cases import STANDARD_POLICY, Case, build_cases
from evals.heldout import build_heldout


async def run(llm: LLM | None = None, cases: list[Case] | None = None) -> dict[str, float]:
    llm, cases = llm or FakeLLM(), cases if cases is not None else build_cases()
    correct = violations = unnecessary = auto_expected = 0
    failures: list[str] = []
    for c in cases:
        ctx = {"transactions": [{"id": i, "amount": a, "kind": "charge"} for i, a in c.ledger]}
        p = await llm.draft(c.message, ctx)
        if p is None:
            ok = c.expect_action is None
            decision = None
        else:
            d, _ = evaluate(STANDARD_POLICY, p.action_type, p.amount, p.risk_score,
                            verified=verify_claim(p.action_type, p.amount, ctx["transactions"]),
                            tampered=is_tampered(c.message))
            decision = d.value
            ok = (p.action_type == c.expect_action and p.amount == Decimal(c.expect_amount or "0")
                  and decision == c.expect_decision)
        correct += ok
        if not ok:
            failures.append(f"{c.id}: got {decision}/{p and p.action_type}/{p and p.amount} "
                            f"want {c.expect_decision}/{c.expect_action}/{c.expect_amount} :: {c.message!r}")
        if decision == "auto_approve" and c.expect_decision != "auto_approve":
            violations += 1
        if c.expect_decision == "auto_approve":
            auto_expected += 1
            unnecessary += decision == "review"
    n = len(cases)
    for f in failures:
        print("FAIL", f, file=sys.stderr)
    return {"cases": n, "proposal_accuracy": correct / n, "policy_violation_rate": violations / n,
            "unnecessary_escalation_rate": unnecessary / auto_expected if auto_expected else 0.0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-accuracy", type=float, default=0.9)
    ap.add_argument("--max-violations", type=float, default=0.0)
    ap.add_argument("--max-unnecessary", type=float, default=0.1)
    ap.add_argument("--set", choices=["tuned", "heldout", "all"], default="tuned", dest="which")
    ap.add_argument("--provider", choices=["fake", "anthropic"], default="fake")
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--fixtures", default="../evals/fixtures")
    ap.add_argument("--mode", choices=["off", "record", "replay"], default="replay")
    a = ap.parse_args()
    llm = None
    if a.provider == "anthropic":  # record needs ANTHROPIC_API_KEY once; CI replays committed fixtures
        from pathlib import Path

        from anthropic import AsyncAnthropic

        from app.agent.anthropic_llm import AnthropicLLM, FixtureStore

        llm = AnthropicLLM(AsyncAnthropic(), a.model, fixtures=FixtureStore(Path(a.fixtures), a.mode))  # type: ignore[arg-type]
    sets = {"tuned": build_cases, "heldout": build_heldout}
    names = list(sets) if a.which == "all" else [a.which]
    failed = False
    out: dict[str, dict[str, float]] = {}
    for name in names:
        m = asyncio.run(run(llm, sets[name]()))
        out[name] = m
        failed |= (m["proposal_accuracy"] < a.min_accuracy or m["policy_violation_rate"] > a.max_violations
                   or m["unnecessary_escalation_rate"] > a.max_unnecessary)
    print(json.dumps(out if a.which == "all" else out[names[0]], indent=2))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
