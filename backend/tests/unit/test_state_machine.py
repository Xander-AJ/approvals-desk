import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from app.domain.idempotency import idempotency_key
from app.domain.state_machine import (
    TERMINAL,
    TRANSITIONS,
    InvalidTransition,
    ProposalState,
    transition,
)

states = st.sampled_from(list(ProposalState))


@given(states, states)
def test_transition_matches_table(a: ProposalState, b: ProposalState) -> None:
    if b in TRANSITIONS[a]:
        assert transition(a, b) == b
    else:
        with pytest.raises(InvalidTransition):
            transition(a, b)


def test_terminal_states_have_no_exits() -> None:
    for t in TERMINAL:
        assert not TRANSITIONS[t]


def test_execution_requires_approval() -> None:
    for s in ProposalState:
        if ProposalState.EXECUTED in TRANSITIONS[s]:
            assert s in {ProposalState.APPROVED, ProposalState.EDITED}


class Machine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.state = ProposalState.PROPOSED
        self.executed = 0

    @rule(t=states)
    def step(self, t: ProposalState) -> None:
        try:
            self.state = transition(self.state, t)
            if t == ProposalState.EXECUTED:
                self.executed += 1
        except InvalidTransition:
            pass

    @invariant()
    def executes_at_most_once(self) -> None:
        assert self.executed <= 1


TestMachine = Machine.TestCase


def test_idempotency_key_stable_and_versioned() -> None:
    assert idempotency_key("t", "p", 1) == idempotency_key("t", "p", 1)
    assert idempotency_key("t", "p", 1) != idempotency_key("t", "p", 2)
