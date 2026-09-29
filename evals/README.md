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

Caveat: labels and cases were written by the same author who iterated the prompt against them, and there is no
held-out set, so the score is optimistic. Add unseen cases before trusting it.
