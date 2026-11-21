"""Payment state machine — enforced transition graph.

Every payment progresses through a defined set of states. Transitions that are not
listed here are rejected so that a delayed webhook, a retry, or a misbehaving caller
cannot put a payment into an impossible state.

Allowed transitions (Kiro audit recommendation, 2026-11-21):

    intent_recorded → order_created
    order_created   → buyer_approved
    buyer_approved  → capture_pending | captured | failed
    capture_pending → captured | failed | verification_pending
    captured        → partially_refunded | refunded | disputed
    partially_refunded → refunded | disputed
    disputed        → captured | refunded        (dispute resolved either way)
    verification_pending → captured | failed     (async reconciliation path)
    failed          → order_created              (allow retry after failure)

Terminal states: refunded, archived.
"""
from __future__ import annotations

# Maps each state to the set of states it may legally move to.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "intent_recorded":      frozenset({"order_created"}),
    "order_created":        frozenset({"buyer_approved", "failed"}),
    "buyer_approved":       frozenset({"capture_pending", "captured", "failed", "verification_pending"}),
    "capture_pending":      frozenset({"captured", "failed", "verification_pending"}),
    "captured":             frozenset({"partially_refunded", "refunded", "disputed"}),
    "partially_refunded":   frozenset({"refunded", "disputed"}),
    "disputed":             frozenset({"captured", "refunded"}),
    "verification_pending": frozenset({"captured", "failed"}),
    "failed":               frozenset({"order_created", "verification_pending"}),
    # Terminal states have no outbound transitions.
    "refunded":             frozenset(),
    "archived":             frozenset(),
}

# States that are considered "complete" for the purpose of capture-idempotency checks.
CAPTURED_STATES = frozenset({"captured", "partially_refunded", "refunded", "disputed"})
TERMINAL_STATES = frozenset({"refunded", "archived"})


class InvalidStateTransition(ValueError):
    """Raised when a caller attempts a transition the state machine does not allow."""


def validate_transition(current: str, next_state: str) -> None:
    """Raise InvalidStateTransition if moving from *current* to *next_state* is not allowed.

    Unknown current and target states fail closed. A repeated state is idempotent.
    """
    if next_state not in _TRANSITIONS:
        raise InvalidStateTransition(
            f"Unknown target state {next_state!r}. Add it to finance_state._TRANSITIONS."
        )
    if current == next_state:
        return
    allowed = _TRANSITIONS.get(current)
    if allowed is None:
        raise InvalidStateTransition(f"Unknown current state {current!r}")
    if next_state not in allowed:
        raise InvalidStateTransition(
            f"Payment state transition {current!r} → {next_state!r} is not permitted. "
            f"Allowed from {current!r}: {sorted(allowed) or ['(terminal)']}"
        )


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def is_captured(state: str) -> bool:
    """True for any state that means money has moved to the merchant."""
    return state in CAPTURED_STATES
