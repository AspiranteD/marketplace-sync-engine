"""Tests for SyncEngine – mock adapters, sync flow, batching, stats."""

from __future__ import annotations

import pytest

from src.sync.sync_engine import ListingData, SyncEngine


class FakeAdapter:
    """In-memory platform adapter for testing."""

    def __init__(self, name: str, listings: dict[str, ListingData] | None = None):
        self._name = name
        self._listings: dict[str, ListingData] = listings or {}
        self.pushed: list[ListingData] = []
        self.price_pushes: list[tuple[str, float]] = []

    @property
    def platform_name(self) -> str:
        return self._name

    def fetch_listing(self, listing_id: str) -> ListingData | None:
        return self._listings.get(listing_id)

    def push_listing(self, listing: ListingData) -> bool:
        self.pushed.append(listing)
        self._listings[listing.listing_id] = listing
        return True

    def push_price(self, listing_id: str, price: float) -> bool:
        self.price_pushes.append((listing_id, price))
        return True

    def list_ids(self) -> list[str]:
        return list(self._listings.keys())


class FailingAdapter(FakeAdapter):
    def push_listing(self, listing: ListingData) -> bool:
        return False

    def push_price(self, listing_id: str, price: float) -> bool:
        return False


def _make_listing(lid: str = "L1", price: float = 10.0, updated: float = 1.0) -> ListingData:
    return ListingData(listing_id=lid, title="Item", price=price, status="active", platform="test", updated_at=updated)


@pytest.fixture
def primary():
    return FakeAdapter("wallapop", {"L1": _make_listing("L1"), "L2": _make_listing("L2", 20.0)})


@pytest.fixture
def secondary():
    return FakeAdapter("ebay")


class TestSyncListing:
    def test_sync_single(self, primary, secondary):
        engine = SyncEngine(primary, [secondary])
        assert engine.sync_listing("L1") is True
        assert len(secondary.pushed) == 1
        assert engine.stats.synced == 1

    def test_sync_missing_listing(self, primary, secondary):
        engine = SyncEngine(primary, [secondary])
        assert engine.sync_listing("NOPE") is False
        assert engine.stats.skipped == 1

    def test_sync_conflict_detected(self, primary):
        remote_listing = _make_listing("L1", updated=999.0)
        sec = FakeAdapter("ebay", {"L1": remote_listing})
        engine = SyncEngine(primary, [sec])
        conflicts = []
        engine.on_conflict(lambda l, r: conflicts.append((l, r)))
        engine.sync_listing("L1")
        assert engine.stats.conflicts == 1
        assert len(conflicts) == 1

    def test_sync_push_failure(self, primary):
        sec = FailingAdapter("ebay")
        engine = SyncEngine(primary, [sec])
        assert engine.sync_listing("L1") is False
        assert engine.stats.failed == 1


class TestSyncAll:
    def test_sync_all_basic(self, primary, secondary):
        engine = SyncEngine(primary, [secondary])
        stats = engine.sync_all()
        assert stats.synced == 2
        assert stats.failed == 0

    def test_sync_all_batching(self, secondary):
        listings = {f"L{i}": _make_listing(f"L{i}") for i in range(5)}
        pri = FakeAdapter("wallapop", listings)
        engine = SyncEngine(pri, [secondary], batch_size=2)
        stats = engine.sync_all()
        assert stats.synced == 5


class TestSyncPrices:
    def test_price_sync(self, primary, secondary):
        engine = SyncEngine(primary, [secondary])
        stats = engine.sync_prices()
        assert stats.synced == 2
        assert len(secondary.price_pushes) == 2

    def test_price_sync_failure(self, primary):
        sec = FailingAdapter("ebay")
        engine = SyncEngine(primary, [sec])
        stats = engine.sync_prices()
        assert stats.failed == 2


class TestEngineConfiguration:
    def test_add_secondary(self, primary, secondary):
        engine = SyncEngine(primary)
        engine.add_secondary(secondary)
        assert len(engine.secondaries) == 1
