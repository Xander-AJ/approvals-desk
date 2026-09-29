import hashlib


def idempotency_key(thread_id: str, proposal_id: str, version: int) -> str:
    """Deterministic key for every mutating tool call: (thread_id, proposal_id, version)."""
    return hashlib.sha256(f"{thread_id}:{proposal_id}:{version}".encode()).hexdigest()
