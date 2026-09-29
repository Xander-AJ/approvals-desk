"""Single owner of approval state transitions. Invalid transitions raise InvalidTransition (HTTP 409)."""
from __future__ import annotations

from enum import StrEnum


class ProposalState(StrEnum):
    PROPOSED = "proposed"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"
    COMPENSATED = "compensated"


S = ProposalState

TRANSITIONS: dict[ProposalState, frozenset[ProposalState]] = {
    S.PROPOSED: frozenset({S.PENDING_REVIEW, S.APPROVED, S.REJECTED}),  # APPROVED=auto, REJECTED=policy block
    S.PENDING_REVIEW: frozenset({S.APPROVED, S.EDITED, S.REJECTED, S.EXPIRED}),
    S.APPROVED: frozenset({S.EXECUTED, S.FAILED}),
    S.EDITED: frozenset({S.EXECUTED, S.FAILED}),
    S.REJECTED: frozenset(),
    S.EXPIRED: frozenset(),
    S.EXECUTED: frozenset({S.COMPENSATED}),
    S.FAILED: frozenset(),
    S.COMPENSATED: frozenset(),
}

TERMINAL: frozenset[ProposalState] = frozenset(s for s, n in TRANSITIONS.items() if not n)


class InvalidTransition(Exception):
    def __init__(self, current: ProposalState, target: ProposalState) -> None:
        super().__init__(f"invalid transition {current.value} -> {target.value}")
        self.current = current
        self.target = target


def can_transition(current: ProposalState, target: ProposalState) -> bool:
    return target in TRANSITIONS[current]


def transition(current: ProposalState, target: ProposalState) -> ProposalState:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)
    return target
