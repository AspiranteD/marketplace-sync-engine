"""
Store assignment with price-based ranking and category routing.

Three stores:
  - STORE_MOTOR (16): items whose category contains "motor"
  - STORE_EXPENSIVE (17): top N most expensive non-motor items
  - STORE_CHEAP (14): remaining non-motor items

Features:
  - Lazy calculation: only compute when needed (during sync or new stock)
  - Batch recalculation: recompute all stores sorted by price DESC
  - Category-first routing: motor items bypass price ranking
  - Configurable TOP_N threshold (default 5100)
"""
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

STORE_MOTOR = 16
STORE_EXPENSIVE = 17
STORE_CHEAP = 14
DEFAULT_TOP_N = 5100


def assign_store(
    category: str,
    price: float,
    count_more_expensive: int,
    top_n: int = DEFAULT_TOP_N,
) -> int:
    """
    Calculate store assignment for a single item.

    Priority: motor category > price ranking > default cheap.
    """
    if category and "motor" in category.lower():
        return STORE_MOTOR

    if price is None or price <= 0:
        return STORE_CHEAP

    if count_more_expensive < top_n:
        return STORE_EXPENSIVE

    return STORE_CHEAP


def batch_assign_stores(
    items: List[Dict[str, Any]],
    category_key: str = "category",
    price_key: str = "price",
    top_n: int = DEFAULT_TOP_N,
) -> Dict[str, Dict[str, Any]]:
    """
    Recalculate stores for a batch of items.

    Items are sorted by price DESC. Motor items are always routed to
    STORE_MOTOR regardless of price. Non-motor items are ranked by price;
    the top N go to STORE_EXPENSIVE, the rest to STORE_CHEAP.

    Returns stats dict with total, motor, expensive, cheap, updated, unchanged.
    """
    stats = {
        "total": 0,
        "motor": 0,
        "expensive": 0,
        "cheap": 0,
        "updated": 0,
        "unchanged": 0,
    }

    motor_items = []
    non_motor_items = []

    for item in items:
        cat = item.get(category_key) or ""
        if "motor" in cat.lower():
            motor_items.append(item)
        else:
            non_motor_items.append(item)

    non_motor_items.sort(
        key=lambda x: x.get(price_key) or 0,
        reverse=True,
    )

    for item in motor_items:
        old = item.get("store")
        item["store"] = STORE_MOTOR
        stats["motor"] += 1
        stats["total"] += 1
        if old != STORE_MOTOR:
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1

    for idx, item in enumerate(non_motor_items, 1):
        price = item.get(price_key) or 0
        old = item.get("store")

        if price <= 0:
            item["store"] = STORE_CHEAP
            new = STORE_CHEAP
        elif idx <= top_n:
            item["store"] = STORE_EXPENSIVE
            new = STORE_EXPENSIVE
        else:
            item["store"] = STORE_CHEAP
            new = STORE_CHEAP

        if new == STORE_EXPENSIVE:
            stats["expensive"] += 1
        else:
            stats["cheap"] += 1

        stats["total"] += 1
        if old != new:
            stats["updated"] += 1
        else:
            stats["unchanged"] += 1

    logger.info(
        "Store assignment: %d total, %d motor, %d expensive, %d cheap, %d updated",
        stats["total"], stats["motor"], stats["expensive"],
        stats["cheap"], stats["updated"],
    )
    return stats
