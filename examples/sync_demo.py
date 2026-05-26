"""
Quick demo: wire up the sync engine with in-memory adapters and run a full sync.

Usage:
    python -m examples.sync_demo
"""

from __future__ import annotations

from src.sync.sync_engine import ListingData, SyncEngine
from src.sync.state_machine import ListingStateMachine, ListingEvent
from src.sync.conflict_resolver import ConflictResolver, ListingSnapshot, ResolutionStrategy


# ---------------------------------------------------------------------------
# 1. In-memory platform adapter
# ---------------------------------------------------------------------------

class MemoryAdapter:
    def __init__(self, name: str, listings: dict[str, ListingData] | None = None):
        self._name = name
        self._store: dict[str, ListingData] = listings or {}

    @property
    def platform_name(self) -> str:
        return self._name

    def fetch_listing(self, listing_id: str) -> ListingData | None:
        return self._store.get(listing_id)

    def push_listing(self, listing: ListingData) -> bool:
        self._store[listing.listing_id] = listing
        print(f"  [{self._name}] pushed {listing.listing_id} @ €{listing.price}")
        return True

    def push_price(self, listing_id: str, price: float) -> bool:
        if listing_id in self._store:
            self._store[listing_id].price = price
        return True

    def list_ids(self) -> list[str]:
        return list(self._store.keys())


# ---------------------------------------------------------------------------
# 2. Build adapters with sample data
# ---------------------------------------------------------------------------

wallapop = MemoryAdapter("wallapop", {
    "WLP-001": ListingData("WLP-001", "iPhone 13 128 GB", 420.0, "active", "wallapop", updated_at=1000),
    "WLP-002": ListingData("WLP-002", "MacBook Air M2", 890.0, "active", "wallapop", updated_at=1000),
    "WLP-003": ListingData("WLP-003", "AirPods Pro", 120.0, "active", "wallapop", updated_at=1000),
})

ebay = MemoryAdapter("ebay")
portalhero = MemoryAdapter("portalhero")

# ---------------------------------------------------------------------------
# 3. State machine demo
# ---------------------------------------------------------------------------

print("=== State Machine ===")
sm = ListingStateMachine()
print(f"  State: {sm.state.value}")
sm.transition(ListingEvent.PUBLISH)
print(f"  -> PUBLISH -> {sm.state.value}")
sm.transition(ListingEvent.RESERVE)
print(f"  -> RESERVE -> {sm.state.value}")
sm.transition(ListingEvent.SELL)
print(f"  -> SELL    -> {sm.state.value}")
sm.transition(ListingEvent.COMPLETE)
print(f"  -> COMPLETE-> {sm.state.value}")
print()

# ---------------------------------------------------------------------------
# 4. Sync engine demo
# ---------------------------------------------------------------------------

print("=== Full Sync ===")
engine = SyncEngine(wallapop, [ebay, portalhero])
stats = engine.sync_all()
print(f"\n  Stats: synced={stats.synced}  skipped={stats.skipped}  failed={stats.failed}  conflicts={stats.conflicts}")
print()

# ---------------------------------------------------------------------------
# 5. Conflict resolution demo
# ---------------------------------------------------------------------------

print("=== Conflict Resolution ===")
local = ListingSnapshot("WLP-001", price=420.0, status="active", updated_at=1000, platform="wallapop")
remote = ListingSnapshot("WLP-001", price=399.0, status="active", updated_at=1050, platform="ebay")

resolver = ConflictResolver()
result = resolver.resolve(local, remote, ResolutionStrategy.LAST_WRITE_WINS)
print(f"  Strategy: {result.strategy.value}")
print(f"  Winner:   {result.chosen.platform} @ €{result.chosen.price}")
print(f"  Reason:   {result.reason}")
