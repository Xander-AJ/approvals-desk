# Evals

`backend/evals/cases.py` holds 60 hand-labelled tickets (English/Swahili/Sheng). `fixtures/` holds recorded
Claude Haiku 4.5 responses so CI replays them offline: no key, no cost, deterministic.

Re-record after changing the system prompt, tools, model or cases (stale fixtures fail loudly in replay mode):

    rm evals/fixtures/*.json
    cd backend
    ANTHROPIC_BASE_URL=https://openrouter.ai/api ANTHROPIC_AUTH_TOKEN=<openrouter key> \
      uv run python -m evals.run --provider anthropic --model anthropic/claude-haiku-4.5 --mode record

(With a direct Anthropic key use `ANTHROPIC_API_KEY` and `--model claude-haiku-4-5-20251001`. The fixture key
includes the model id, so replay must use the same `--model`.)

Metrics: proposal accuracy, policy-violation rate (must be 0), unnecessary-escalation rate.

Two sets:

- `cases.py` (60, "tuned"): the prompt was iterated against these, so the score is optimistic.
- `heldout.py` (29): written after the prompt was frozen, labelled and committed *before* any run.
  Quote this one. Result at first run: accuracy 0.793, policy-violation rate 0.103, which **failed** the gates
  (>= 0.8, == 0). Cause and fix: `docs/adr/0005`. After the code fix: 0.862 / 0.0, but that fix followed the
  failures, so it is no longer an unbiased estimate. Add fresh cases before trusting it further.

Run both: `python -m evals.run --set all --provider anthropic --model anthropic/claude-haiku-4.5 --mode replay`.
The model is only exercised on drafting; the auto-approve decision is code and has its own tests.
