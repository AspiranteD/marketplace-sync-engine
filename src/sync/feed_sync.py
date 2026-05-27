"""
Feed synchronization: DB -> CSV -> cloud storage.

Full pipeline:
  1. Load raw feed from data source (materialized view, query, etc.)
  2. Process DataFrame:
     a. Price filtering (min 2 EUR, motor exempt)
     b. Image normalization (split separators, limit to 10)
     c. Condition code mapping (PERFECTO -> as_good_as_new, etc.)
     d. Shipping weight rules (<=30kg -> shippable)
     e. Free shipping rules (<5kg AND >70 EUR)
     f. ASIN+condition deduplication with stock accumulation:
        - PERFECTO: group by ASIN+condition only
        - CON_TARA/others: group by ASIN+condition+description
          (each defect has unique images)
        - Within each group: count=stock, min(price)=price
     g. ID randomization (2-letter suffix rotating every 54h)
     h. Store assignment post-dedup (motor=16, top5100=17, rest=14)
     i. Title/description formatting with truncation
  3. Upload to cloud storage (update existing or create new)
  4. Keep local audit copy with timestamp
"""
import logging
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.sync.store_assignment import (
    STORE_MOTOR, STORE_EXPENSIVE, STORE_CHEAP,
    DEFAULT_TOP_N, batch_assign_stores,
)

logger = logging.getLogger(__name__)

CONDITION_CODE_MAP = {
    "PERFECTO": "as_good_as_new",
    "CON_TARA": "fair",
    "PARA_PIEZAS": "has_given_it_all",
}

CONDITION_TEXT_MAP = {
    "Para piezas": "has_given_it_all",
    "Con tara": "fair",
    "Perfecto": "as_good_as_new",
}

_BASE_DATETIME = datetime(2026, 1, 21, 7, 0, 0)
_PERIOD_HOURS = 54
_START_OFFSET = 102


def get_time_based_suffix(now: Optional[datetime] = None) -> str:
    """
    Generate a 2-letter suffix that rotates every 54 hours.

    Algorithm replicates the original V2_5 implementation:
      - Base date: 2026-01-21 07:00:00
      - Offset: 102 (first suffix = "DY")
      - Period: 54 hours
      - 676 combinations (AA-ZZ)
    """
    if now is None:
        now = datetime.now()
    period_seconds = _PERIOD_HOURS * 3600
    time_diff = now.timestamp() - _BASE_DATETIME.timestamp()
    period_number = max(0, int(time_diff // period_seconds))
    period_number = (period_number + _START_OFFSET) % 676
    first = chr(65 + period_number // 26)
    second = chr(65 + period_number % 26)
    return first + second


def randomize_id(item_id: str, now: Optional[datetime] = None) -> str:
    """Append time-based 2-letter suffix to an ID."""
    if not item_id or str(item_id).strip() == "":
        return item_id
    return str(item_id).strip() + get_time_based_suffix(now)


def normalize_images(img_str: str, max_images: int = 10) -> str:
    """Normalize image separators (comma, space, pipe) and limit count."""
    if not img_str:
        return ""
    tokens = [t.strip() for t in re.split(r"[,\s|]+", str(img_str)) if t.strip()]
    return "|".join(tokens[:max_images])


def map_condition(
    condition_code: Optional[str] = None,
    condition_text: Optional[str] = None,
) -> str:
    """Map condition codes/text to standardized status values."""
    if condition_code and condition_code in CONDITION_CODE_MAP:
        return CONDITION_CODE_MAP[condition_code]
    if condition_text and condition_text in CONDITION_TEXT_MAP:
        return CONDITION_TEXT_MAP[condition_text]
    return "good"


def calc_shipping(weight_kg: Optional[float]) -> str:
    """Determine if item is shippable (weight <= 30kg or unknown)."""
    if weight_kg is None or weight_kg <= 30:
        return "true"
    return ""


def calc_free_shipping(weight_kg: Optional[float], price: Optional[float]) -> str:
    """Free shipping: weight < 5kg AND price > 70 EUR."""
    if (
        weight_kg is not None
        and weight_kg < 5
        and price is not None
        and price > 70
    ):
        return "true"
    return ""


def deduplicate_by_asin(
    items: List[Dict[str, Any]],
    asin_key: str = "asin",
    id_key: str = "id_base",
    condition_key: str = "condition_code",
    description_key: str = "condition_description",
    price_key: str = "price",
) -> List[Dict[str, Any]]:
    """
    Deduplicate items by ASIN + condition with stock accumulation.

    Grouping rules:
      - PERFECTO/as_good_as_new: group by ASIN + condition only
        (condition_description contains operator notes, not defects)
      - CON_TARA / PARA_PIEZAS / others: group by ASIN + condition + description
        (each defect has unique description and images)

    Within each group:
      - stock = count of items
      - price = min price across group
      - Keep first item's data (images, title, etc.)
    """
    groups: Dict[str, Dict[str, Any]] = {}

    for item in items:
        asin = item.get(asin_key) or item.get(id_key, "")
        ccode = item.get(condition_key) or ""
        cdesc = (item.get(description_key) or "").strip()

        is_perfecto = ccode in ("PERFECTO", "as_good_as_new")
        desc_for_group = "" if is_perfecto else cdesc

        group_key = f"{asin}|{ccode}|{desc_for_group}"

        if group_key not in groups:
            groups[group_key] = {**item, "stock": 1}
        else:
            groups[group_key]["stock"] += 1
            existing_price = groups[group_key].get(price_key)
            new_price = item.get(price_key)
            if new_price is not None:
                if existing_price is None or new_price < existing_price:
                    groups[group_key][price_key] = new_price

    result = list(groups.values())
    n_deduped = len(items) - len(result)
    if n_deduped > 0:
        logger.info(
            "Deduplication: %d -> %d items (%d duplicates merged into stock)",
            len(items), len(result), n_deduped,
        )
    return result


class FeedSyncService:
    """
    Full feed sync pipeline: load -> process -> upload.

    Database-agnostic: uses callbacks for data loading, title building,
    and file uploading.
    """

    def __init__(
        self,
        load_feed: Callable[[], List[Dict[str, Any]]],
        upload_file: Callable[[str, List[Dict[str, Any]]], None],
        build_title: Optional[Callable[[Dict[str, Any]], str]] = None,
        build_description: Optional[Callable[[Dict[str, Any]], str]] = None,
        top_n_expensive: int = DEFAULT_TOP_N,
        min_price: float = 2.0,
        max_images: int = 10,
        max_title_len: int = 60,
        max_desc_len: int = 640,
        max_id_len: int = 150,
    ):
        self._load_feed = load_feed
        self._upload_file = upload_file
        self._build_title = build_title
        self._build_description = build_description
        self.top_n = top_n_expensive
        self.min_price = min_price
        self.max_images = max_images
        self.max_title_len = max_title_len
        self.max_desc_len = max_desc_len
        self.max_id_len = max_id_len

    def sync(self) -> Dict[str, Any]:
        """Execute full sync pipeline."""
        logger.info("Starting feed sync...")

        raw_items = self._load_feed()
        if not raw_items:
            logger.warning("No data to sync")
            return {"status": "empty", "items": 0}

        processed = self.process(raw_items)
        logger.info("Feed processed: %d items", len(processed))

        self._upload_file("item_feed.csv", processed)
        logger.info("Feed sync completed")

        return {"status": "success", "items": len(processed)}

    def process(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Full processing pipeline."""
        items = self._filter_price(items)
        items = self._normalize_images(items)
        items = self._map_conditions(items)
        items = self._calc_shipping(items)
        items = deduplicate_by_asin(items)
        items = self._randomize_ids(items)
        items = self._assign_stores(items)
        items = self._format_text(items)
        return items

    def _filter_price(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter out items below min_price (motor category exempt)."""
        result = []
        for item in items:
            cat = item.get("external_category") or ""
            price = item.get("price")
            is_motor = "motor" in cat.lower()

            if is_motor or (price is not None and price >= self.min_price):
                result.append(item)

        filtered = len(items) - len(result)
        if filtered > 0:
            logger.info("Price filter: removed %d items below %.2f EUR", filtered, self.min_price)
        return result

    def _normalize_images(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for item in items:
            raw = item.get("images_raw") or item.get("images", "")
            item["images"] = normalize_images(raw, self.max_images)
        return items

    def _map_conditions(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for item in items:
            if not item.get("status"):
                item["status"] = map_condition(
                    item.get("condition_code"),
                    item.get("condition"),
                )
        return items

    def _calc_shipping(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for item in items:
            w = item.get("shipping_weight_kg")
            p = item.get("price")

            if not item.get("shipping"):
                item["shipping"] = calc_shipping(w)

            item["free_shipping"] = calc_free_shipping(w, p)
        return items

    def _randomize_ids(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for item in items:
            base_id = item.get("id_base") or item.get("id", "")
            item["id"] = randomize_id(base_id)[:self.max_id_len]
        return items

    def _assign_stores(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        batch_assign_stores(
            items,
            category_key="external_category",
            price_key="price",
            top_n=self.top_n,
        )
        return items

    def _format_text(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        for item in items:
            if self._build_title:
                item["title"] = self._build_title(item)[:self.max_title_len]
            elif "title" in item:
                item["title"] = str(item["title"])[:self.max_title_len]

            if self._build_description:
                item["description"] = self._build_description(item)[:self.max_desc_len]
            elif "description" in item:
                item["description"] = str(item["description"])[:self.max_desc_len]
        return items
