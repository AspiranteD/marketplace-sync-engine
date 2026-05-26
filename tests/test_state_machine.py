"""Tests for ListingStateMachine – transitions, rejections, valid events."""

import pytest

from src.sync.state_machine import (
    InvalidTransitionError,
    ListingEvent,
    ListingState,
    ListingStateMachine,
)


class TestValidTransitions:
    def test_draft_to_active(self):
        sm = ListingStateMachine()
        assert sm.transition(ListingEvent.PUBLISH) == ListingState.ACTIVE

    def test_active_to_reserved(self):
        sm = ListingStateMachine(ListingState.ACTIVE)
        assert sm.transition(ListingEvent.RESERVE) == ListingState.RESERVED

    def test_active_to_sold(self):
        sm = ListingStateMachine(ListingState.ACTIVE)
        assert sm.transition(ListingEvent.SELL) == ListingState.SOLD

    def test_active_to_paused(self):
        sm = ListingStateMachine(ListingState.ACTIVE)
        assert sm.transition(ListingEvent.PAUSE) == ListingState.PAUSED

    def test_active_to_banned(self):
        sm = ListingStateMachine(ListingState.ACTIVE)
        assert sm.transition(ListingEvent.BAN) == ListingState.BANNED

    def test_active_to_expired(self):
        sm = ListingStateMachine(ListingState.ACTIVE)
        assert sm.transition(ListingEvent.EXPIRE) == ListingState.EXPIRED

    def test_reserved_to_sold(self):
        sm = ListingStateMachine(ListingState.RESERVED)
        assert sm.transition(ListingEvent.SELL) == ListingState.SOLD

    def test_reserved_to_active(self):
        sm = ListingStateMachine(ListingState.RESERVED)
        assert sm.transition(ListingEvent.RESUME) == ListingState.ACTIVE

    def test_sold_to_completed(self):
        sm = ListingStateMachine(ListingState.SOLD)
        assert sm.transition(ListingEvent.COMPLETE) == ListingState.COMPLETED

    def test_paused_to_active(self):
        sm = ListingStateMachine(ListingState.PAUSED)
        assert sm.transition(ListingEvent.RESUME) == ListingState.ACTIVE

    def test_banned_to_active(self):
        sm = ListingStateMachine(ListingState.BANNED)
        assert sm.transition(ListingEvent.UNBAN) == ListingState.ACTIVE

    def test_expired_to_active(self):
        sm = ListingStateMachine(ListingState.EXPIRED)
        assert sm.transition(ListingEvent.RELIST) == ListingState.ACTIVE


class TestInvalidTransitions:
    def test_draft_cannot_sell(self):
        sm = ListingStateMachine()
        with pytest.raises(InvalidTransitionError):
            sm.transition(ListingEvent.SELL)

    def test_completed_cannot_publish(self):
        sm = ListingStateMachine(ListingState.COMPLETED)
        with pytest.raises(InvalidTransitionError):
            sm.transition(ListingEvent.PUBLISH)

    def test_sold_cannot_pause(self):
        sm = ListingStateMachine(ListingState.SOLD)
        with pytest.raises(InvalidTransitionError):
            sm.transition(ListingEvent.PAUSE)


class TestValidEvents:
    def test_draft_valid_events(self):
        sm = ListingStateMachine()
        evts = sm.get_valid_events()
        assert ListingEvent.PUBLISH in evts
        assert len(evts) == 1

    def test_active_valid_events(self):
        evts = ListingStateMachine(ListingState.ACTIVE).get_valid_events()
        assert set(evts) == {ListingEvent.RESERVE, ListingEvent.SELL, ListingEvent.PAUSE, ListingEvent.BAN, ListingEvent.EXPIRE}

    def test_completed_has_no_events(self):
        evts = ListingStateMachine(ListingState.COMPLETED).get_valid_events()
        assert evts == []


class TestHistory:
    def test_history_recorded(self):
        sm = ListingStateMachine()
        sm.transition(ListingEvent.PUBLISH)
        sm.transition(ListingEvent.SELL)
        assert len(sm.history) == 2
        assert sm.history[0] == (ListingState.DRAFT, ListingEvent.PUBLISH, ListingState.ACTIVE)

    def test_get_all_transitions(self):
        transitions = ListingStateMachine.get_all_transitions()
        assert len(transitions) == 12
