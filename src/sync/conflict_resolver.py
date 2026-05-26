"""Cross-platform conflict detection and resolution strategies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ConflictType(str, Enum):
    PRICE_MISMATCH = "price_mismatch"
    STATUS_MISMATCH = "status_mismatch"
    BOTH_MODIFIED = "both_modified"
    NO_CONFLICT = "no_conflict"


class ResolutionStrategy(str, Enum):
    LAST_WRITE_WINS = "last_write_wins"
    PRIMARY_WINS = "primary_wins"
    MANUAL_REVIEW = "manual_review"


@dataclass
class ListingSnapshot:
    listing_id: str
    price: float
    status: str
    updated_at: float
    platform: str
    metadata: dict[str, Any] | None = None


@dataclass
class ConflictResolution:
    conflict_type: ConflictType
    strategy: ResolutionStrategy
    chosen: ListingSnapshot
    rejected: ListingSnapshot
    reason: str
    needs_review: bool = False


class ConflictResolver:
    """Detects and resolves cross-platform listing conflicts."""

    def __init__(self, default_strategy: ResolutionStrategy = ResolutionStrategy.PRIMARY_WINS):
        self._default_strategy = default_strategy

    @property
    def default_strategy(self) -> ResolutionStrategy:
        return self._default_strategy

    # -- detection --------------------------------------------------------

    @staticmethod
    def detect(local: ListingSnapshot, remote: ListingSnapshot) -> ConflictType:
        price_diff = local.price != remote.price
        status_diff = local.status != remote.status

        if price_diff and status_diff:
            return ConflictType.BOTH_MODIFIED
        if price_diff:
            return ConflictType.PRICE_MISMATCH
        if status_diff:
            return ConflictType.STATUS_MISMATCH
        return ConflictType.NO_CONFLICT

    # -- resolution -------------------------------------------------------

    def resolve(
        self,
        local: ListingSnapshot,
        remote: ListingSnapshot,
        strategy: ResolutionStrategy | None = None,
    ) -> ConflictResolution:
        strat = strategy or self._default_strategy
        conflict_type = self.detect(local, remote)

        if conflict_type == ConflictType.NO_CONFLICT:
            return ConflictResolution(
                conflict_type=conflict_type,
                strategy=strat,
                chosen=local,
                rejected=remote,
                reason="No conflict detected",
            )

        if strat == ResolutionStrategy.LAST_WRITE_WINS:
            if local.updated_at >= remote.updated_at:
                return ConflictResolution(
                    conflict_type=conflict_type,
                    strategy=strat,
                    chosen=local,
                    rejected=remote,
                    reason=f"Local is newer ({local.updated_at} >= {remote.updated_at})",
                )
            return ConflictResolution(
                conflict_type=conflict_type,
                strategy=strat,
                chosen=remote,
                rejected=local,
                reason=f"Remote is newer ({remote.updated_at} > {local.updated_at})",
            )

        if strat == ResolutionStrategy.PRIMARY_WINS:
            return ConflictResolution(
                conflict_type=conflict_type,
                strategy=strat,
                chosen=local,
                rejected=remote,
                reason="Primary platform always wins",
            )

        # MANUAL_REVIEW
        return ConflictResolution(
            conflict_type=conflict_type,
            strategy=strat,
            chosen=local,
            rejected=remote,
            reason="Flagged for manual review",
            needs_review=True,
        )
