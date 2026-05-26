"""Multi-platform listing sync orchestrator with platform adapter protocol."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class ListingData:
    listing_id: str
    title: str
    price: float
    status: str
    platform: str
    updated_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class PlatformAdapter(Protocol):
    """Each marketplace implements this interface."""

    @property
    def platform_name(self) -> str: ...

    def fetch_listing(self, listing_id: str) -> ListingData | None: ...

    def push_listing(self, listing: ListingData) -> bool: ...

    def push_price(self, listing_id: str, price: float) -> bool: ...

    def list_ids(self) -> list[str]: ...


@dataclass
class SyncStats:
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    conflicts: int = 0

    def reset(self) -> None:
        self.synced = self.skipped = self.failed = self.conflicts = 0


class SyncEngine:
    """Coordinates sync between a primary platform and N secondary platforms."""

    def __init__(
        self,
        primary: PlatformAdapter,
        secondaries: list[PlatformAdapter] | None = None,
        batch_size: int = 50,
    ):
        self.primary = primary
        self.secondaries: list[PlatformAdapter] = secondaries or []
        self.batch_size = batch_size
        self.stats = SyncStats()
        self._conflict_cb: Any = None

    def on_conflict(self, callback: Any) -> None:
        self._conflict_cb = callback

    # -- public API -------------------------------------------------------

    def sync_listing(self, listing_id: str) -> bool:
        """Sync a single listing from primary → all secondaries."""
        primary_data = self.primary.fetch_listing(listing_id)
        if primary_data is None:
            logger.warning("Listing %s not found on primary", listing_id)
            self.stats.skipped += 1
            return False

        all_ok = True
        for sec in self.secondaries:
            remote = sec.fetch_listing(listing_id)
            if remote and remote.updated_at > primary_data.updated_at:
                self.stats.conflicts += 1
                if self._conflict_cb:
                    self._conflict_cb(primary_data, remote)
                continue

            if not sec.push_listing(primary_data):
                self.stats.failed += 1
                all_ok = False
            else:
                self.stats.synced += 1

        return all_ok

    def sync_all(self) -> SyncStats:
        """Full sync of every listing from primary to secondaries (batched)."""
        self.stats.reset()
        ids = self.primary.list_ids()

        for i in range(0, len(ids), self.batch_size):
            batch = ids[i : i + self.batch_size]
            for lid in batch:
                self.sync_listing(lid)

        return self.stats

    def sync_prices(self) -> SyncStats:
        """Price-only sync – lighter and meant for high-frequency runs."""
        self.stats.reset()
        ids = self.primary.list_ids()

        for lid in ids:
            primary_data = self.primary.fetch_listing(lid)
            if primary_data is None:
                self.stats.skipped += 1
                continue

            for sec in self.secondaries:
                if sec.push_price(lid, primary_data.price):
                    self.stats.synced += 1
                else:
                    self.stats.failed += 1

        return self.stats

    def add_secondary(self, adapter: PlatformAdapter) -> None:
        self.secondaries.append(adapter)
