"""Listing lifecycle state machine with validated transitions."""

from __future__ import annotations

from enum import Enum


class ListingState(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    RESERVED = "reserved"
    SOLD = "sold"
    COMPLETED = "completed"
    PAUSED = "paused"
    BANNED = "banned"
    EXPIRED = "expired"


class ListingEvent(str, Enum):
    PUBLISH = "publish"
    RESERVE = "reserve"
    SELL = "sell"
    COMPLETE = "complete"
    PAUSE = "pause"
    RESUME = "resume"
    BAN = "ban"
    UNBAN = "unban"
    EXPIRE = "expire"
    RELIST = "relist"


_TRANSITIONS: dict[tuple[ListingState, ListingEvent], ListingState] = {
    (ListingState.DRAFT, ListingEvent.PUBLISH): ListingState.ACTIVE,
    (ListingState.ACTIVE, ListingEvent.RESERVE): ListingState.RESERVED,
    (ListingState.ACTIVE, ListingEvent.SELL): ListingState.SOLD,
    (ListingState.ACTIVE, ListingEvent.PAUSE): ListingState.PAUSED,
    (ListingState.ACTIVE, ListingEvent.BAN): ListingState.BANNED,
    (ListingState.ACTIVE, ListingEvent.EXPIRE): ListingState.EXPIRED,
    (ListingState.RESERVED, ListingEvent.SELL): ListingState.SOLD,
    (ListingState.RESERVED, ListingEvent.RESUME): ListingState.ACTIVE,
    (ListingState.SOLD, ListingEvent.COMPLETE): ListingState.COMPLETED,
    (ListingState.PAUSED, ListingEvent.RESUME): ListingState.ACTIVE,
    (ListingState.BANNED, ListingEvent.UNBAN): ListingState.ACTIVE,
    (ListingState.EXPIRED, ListingEvent.RELIST): ListingState.ACTIVE,
}


class InvalidTransitionError(Exception):
    pass


class ListingStateMachine:
    """Validates and executes listing lifecycle transitions."""

    def __init__(self, initial_state: ListingState = ListingState.DRAFT):
        self._state = initial_state
        self._history: list[tuple[ListingState, ListingEvent, ListingState]] = []

    @property
    def state(self) -> ListingState:
        return self._state

    @property
    def history(self) -> list[tuple[ListingState, ListingEvent, ListingState]]:
        return list(self._history)

    def transition(self, event: ListingEvent) -> ListingState:
        """Apply *event* to the current state. Raises on invalid transition."""
        key = (self._state, event)
        new_state = _TRANSITIONS.get(key)
        if new_state is None:
            raise InvalidTransitionError(
                f"Cannot apply {event.value!r} in state {self._state.value!r}"
            )
        old = self._state
        self._state = new_state
        self._history.append((old, event, new_state))
        return new_state

    def get_valid_events(self, state: ListingState | None = None) -> list[ListingEvent]:
        """Return events that are valid from *state* (defaults to current)."""
        st = state or self._state
        return [evt for (s, evt), _ in _TRANSITIONS.items() if s == st]

    @staticmethod
    def get_all_transitions() -> dict[tuple[ListingState, ListingEvent], ListingState]:
        return dict(_TRANSITIONS)
