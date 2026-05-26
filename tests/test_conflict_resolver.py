"""Tests for ConflictResolver – strategies, conflict type detection."""

import pytest

from src.sync.conflict_resolver import (
    ConflictResolver,
    ConflictType,
    ListingSnapshot,
    ResolutionStrategy,
)


def _snap(platform: str = "wallapop", price: float = 10.0, status: str = "active", updated: float = 1.0) -> ListingSnapshot:
    return ListingSnapshot(listing_id="L1", price=price, status=status, updated_at=updated, platform=platform)


class TestDetection:
    def test_no_conflict(self):
        assert ConflictResolver.detect(_snap(), _snap(platform="ebay")) == ConflictType.NO_CONFLICT

    def test_price_mismatch(self):
        assert ConflictResolver.detect(_snap(price=10), _snap(price=15)) == ConflictType.PRICE_MISMATCH

    def test_status_mismatch(self):
        assert ConflictResolver.detect(_snap(status="active"), _snap(status="paused")) == ConflictType.STATUS_MISMATCH

    def test_both_modified(self):
        assert ConflictResolver.detect(_snap(price=10, status="active"), _snap(price=15, status="sold")) == ConflictType.BOTH_MODIFIED


class TestPrimaryWins:
    def test_primary_wins_price(self):
        resolver = ConflictResolver(ResolutionStrategy.PRIMARY_WINS)
        local = _snap(price=10)
        remote = _snap(price=15, platform="ebay")
        result = resolver.resolve(local, remote)
        assert result.chosen is local
        assert result.rejected is remote
        assert "Primary" in result.reason

    def test_primary_wins_is_default(self):
        resolver = ConflictResolver()
        assert resolver.default_strategy == ResolutionStrategy.PRIMARY_WINS


class TestLastWriteWins:
    def test_local_newer(self):
        resolver = ConflictResolver()
        local = _snap(price=10, updated=100)
        remote = _snap(price=15, updated=50, platform="ebay")
        result = resolver.resolve(local, remote, ResolutionStrategy.LAST_WRITE_WINS)
        assert result.chosen is local

    def test_remote_newer(self):
        resolver = ConflictResolver()
        local = _snap(price=10, updated=50)
        remote = _snap(price=15, updated=100, platform="ebay")
        result = resolver.resolve(local, remote, ResolutionStrategy.LAST_WRITE_WINS)
        assert result.chosen is remote


class TestManualReview:
    def test_manual_review_flags(self):
        resolver = ConflictResolver()
        local = _snap(price=10)
        remote = _snap(price=15, platform="ebay")
        result = resolver.resolve(local, remote, ResolutionStrategy.MANUAL_REVIEW)
        assert result.needs_review is True
        assert "manual" in result.reason.lower()


class TestNoConflictResolution:
    def test_no_conflict_returns_local(self):
        resolver = ConflictResolver()
        local = _snap()
        remote = _snap(platform="ebay")
        result = resolver.resolve(local, remote)
        assert result.conflict_type == ConflictType.NO_CONFLICT
        assert result.chosen is local
