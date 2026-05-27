"""Tests for feed sync pipeline."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from src.sync.feed_sync import (
    get_time_based_suffix, randomize_id,
    normalize_images, map_condition,
    calc_shipping, calc_free_shipping,
    deduplicate_by_asin, FeedSyncService,
    CONDITION_CODE_MAP, CONDITION_TEXT_MAP,
    _BASE_DATETIME, _PERIOD_HOURS, _START_OFFSET,
)


# ─── get_time_based_suffix ──────────────────────────────────────────────────

def test_suffix_is_two_uppercase_letters():
    suffix = get_time_based_suffix()
    assert len(suffix) == 2
    assert suffix.isalpha()
    assert suffix.isupper()


def test_suffix_at_base_datetime():
    suffix = get_time_based_suffix(now=_BASE_DATETIME)
    expected_num = (_START_OFFSET) % 676
    first = chr(65 + expected_num // 26)
    second = chr(65 + expected_num % 26)
    assert suffix == first + second


def test_suffix_deterministic():
    now = datetime(2026, 3, 15, 12, 0, 0)
    s1 = get_time_based_suffix(now)
    s2 = get_time_based_suffix(now)
    assert s1 == s2


def test_suffix_changes_after_period():
    from datetime import timedelta
    t1 = datetime(2026, 2, 1, 7, 0, 0)
    t2 = t1 + timedelta(hours=_PERIOD_HOURS)
    s1 = get_time_based_suffix(t1)
    s2 = get_time_based_suffix(t2)
    assert s1 != s2


def test_suffix_same_within_period():
    from datetime import timedelta
    t1 = _BASE_DATETIME
    t2 = t1 + timedelta(hours=_PERIOD_HOURS - 1)
    s1 = get_time_based_suffix(t1)
    s2 = get_time_based_suffix(t2)
    assert s1 == s2


def test_suffix_before_base():
    t = datetime(2026, 1, 1, 0, 0, 0)
    suffix = get_time_based_suffix(t)
    assert len(suffix) == 2


# ─── randomize_id ───────────────────────────────────────────────────────────

def test_randomize_id():
    result = randomize_id("LPNWE246958296")
    assert result.startswith("LPNWE246958296")
    assert len(result) == len("LPNWE246958296") + 2


def test_randomize_id_empty():
    assert randomize_id("") == ""
    assert randomize_id(None) is None


def test_randomize_id_strips_whitespace():
    result = randomize_id("  LPNWE001  ")
    assert result.startswith("LPNWE001")
    assert not result.startswith("  ")


# ─── normalize_images ───────────────────────────────────────────────────────

def test_normalize_pipe_separated():
    assert normalize_images("a.jpg|b.jpg|c.jpg") == "a.jpg|b.jpg|c.jpg"


def test_normalize_comma_separated():
    assert normalize_images("a.jpg, b.jpg, c.jpg") == "a.jpg|b.jpg|c.jpg"


def test_normalize_space_separated():
    assert normalize_images("a.jpg b.jpg c.jpg") == "a.jpg|b.jpg|c.jpg"


def test_normalize_mixed_separators():
    assert normalize_images("a.jpg, b.jpg|c.jpg d.jpg") == "a.jpg|b.jpg|c.jpg|d.jpg"


def test_normalize_limit():
    imgs = "|".join(f"img{i}.jpg" for i in range(20))
    result = normalize_images(imgs, max_images=10)
    assert len(result.split("|")) == 10


def test_normalize_empty():
    assert normalize_images("") == ""
    assert normalize_images(None) == ""


def test_normalize_strips_whitespace():
    assert normalize_images("  a.jpg  |  b.jpg  ") == "a.jpg|b.jpg"


# ─── map_condition ──────────────────────────────────────────────────────────

def test_condition_perfecto():
    assert map_condition("PERFECTO") == "as_good_as_new"


def test_condition_con_tara():
    assert map_condition("CON_TARA") == "fair"


def test_condition_para_piezas():
    assert map_condition("PARA_PIEZAS") == "has_given_it_all"


def test_condition_text_perfecto():
    assert map_condition(condition_text="Perfecto") == "as_good_as_new"


def test_condition_text_con_tara():
    assert map_condition(condition_text="Con tara") == "fair"


def test_condition_unknown():
    assert map_condition("UNKNOWN") == "good"


def test_condition_none():
    assert map_condition(None, None) == "good"


def test_condition_code_takes_priority():
    assert map_condition("PERFECTO", "Con tara") == "as_good_as_new"


# ─── calc_shipping ──────────────────────────────────────────────────────────

def test_shipping_light():
    assert calc_shipping(5.0) == "true"


def test_shipping_at_30():
    assert calc_shipping(30.0) == "true"


def test_shipping_heavy():
    assert calc_shipping(31.0) == ""


def test_shipping_unknown_weight():
    assert calc_shipping(None) == "true"


# ─── calc_free_shipping ────────────────────────────────────────────────────

def test_free_shipping_eligible():
    assert calc_free_shipping(3.0, 100.0) == "true"


def test_free_shipping_too_heavy():
    assert calc_free_shipping(5.0, 100.0) == ""


def test_free_shipping_too_cheap():
    assert calc_free_shipping(3.0, 50.0) == ""


def test_free_shipping_at_boundary():
    assert calc_free_shipping(4.99, 70.01) == "true"


def test_free_shipping_exact_boundary():
    assert calc_free_shipping(5.0, 70.0) == ""


def test_free_shipping_none_weight():
    assert calc_free_shipping(None, 100.0) == ""


def test_free_shipping_none_price():
    assert calc_free_shipping(3.0, None) == ""


# ─── deduplicate_by_asin ───────────────────────────────────────────────────

def test_dedup_no_duplicates():
    items = [
        {"asin": "A1", "condition_code": "PERFECTO", "price": 10},
        {"asin": "A2", "condition_code": "PERFECTO", "price": 20},
    ]
    result = deduplicate_by_asin(items)
    assert len(result) == 2


def test_dedup_same_asin_perfecto():
    items = [
        {"asin": "A1", "condition_code": "PERFECTO", "condition_description": "PAOLA", "price": 10},
        {"asin": "A1", "condition_code": "PERFECTO", "condition_description": "BN", "price": 8},
        {"asin": "A1", "condition_code": "PERFECTO", "condition_description": "", "price": 12},
    ]
    result = deduplicate_by_asin(items)
    assert len(result) == 1
    assert result[0]["stock"] == 3
    assert result[0]["price"] == 8


def test_dedup_con_tara_different_descriptions():
    items = [
        {"asin": "A1", "condition_code": "CON_TARA", "condition_description": "Arañazo lateral", "price": 10},
        {"asin": "A1", "condition_code": "CON_TARA", "condition_description": "Pantalla rota", "price": 15},
    ]
    result = deduplicate_by_asin(items)
    assert len(result) == 2
    assert all(r["stock"] == 1 for r in result)


def test_dedup_con_tara_same_description():
    items = [
        {"asin": "A1", "condition_code": "CON_TARA", "condition_description": "Arañazo", "price": 10},
        {"asin": "A1", "condition_code": "CON_TARA", "condition_description": "Arañazo", "price": 8},
    ]
    result = deduplicate_by_asin(items)
    assert len(result) == 1
    assert result[0]["stock"] == 2
    assert result[0]["price"] == 8


def test_dedup_different_conditions():
    items = [
        {"asin": "A1", "condition_code": "PERFECTO", "condition_description": "", "price": 10},
        {"asin": "A1", "condition_code": "CON_TARA", "condition_description": "", "price": 5},
    ]
    result = deduplicate_by_asin(items)
    assert len(result) == 2


def test_dedup_fallback_to_id_base():
    items = [
        {"id_base": "LPN001", "condition_code": "PERFECTO", "price": 10},
        {"id_base": "LPN001", "condition_code": "PERFECTO", "price": 12},
    ]
    result = deduplicate_by_asin(items)
    assert len(result) == 1
    assert result[0]["stock"] == 2


def test_dedup_empty():
    result = deduplicate_by_asin([])
    assert result == []


def test_dedup_preserves_first_item_data():
    items = [
        {"asin": "A1", "condition_code": "PERFECTO", "price": 10, "images": "img1.jpg"},
        {"asin": "A1", "condition_code": "PERFECTO", "price": 8, "images": "img2.jpg"},
    ]
    result = deduplicate_by_asin(items)
    assert result[0]["images"] == "img1.jpg"
    assert result[0]["price"] == 8


def test_dedup_min_price():
    items = [
        {"asin": "A1", "condition_code": "PERFECTO", "price": 30},
        {"asin": "A1", "condition_code": "PERFECTO", "price": 10},
        {"asin": "A1", "condition_code": "PERFECTO", "price": 20},
    ]
    result = deduplicate_by_asin(items)
    assert result[0]["price"] == 10
    assert result[0]["stock"] == 3


# ─── FeedSyncService ───────────────────────────────────────────────────────

def test_sync_empty():
    load = MagicMock(return_value=[])
    upload = MagicMock()
    svc = FeedSyncService(load_feed=load, upload_file=upload)

    result = svc.sync()
    assert result["status"] == "empty"
    upload.assert_not_called()


def test_sync_full_pipeline():
    items = [
        {
            "id_base": "LPNWE001",
            "price": 50.0,
            "external_category": "Electronics",
            "condition_code": "PERFECTO",
            "images_raw": "a.jpg,b.jpg",
            "shipping_weight_kg": 2.0,
        },
        {
            "id_base": "LPNWE002",
            "price": 100.0,
            "external_category": "Electronics",
            "condition_code": "CON_TARA",
            "condition_description": "scratch",
            "images_raw": "c.jpg",
            "shipping_weight_kg": 3.0,
        },
    ]
    load = MagicMock(return_value=items)
    upload = MagicMock()
    svc = FeedSyncService(load_feed=load, upload_file=upload)

    result = svc.sync()
    assert result["status"] == "success"
    assert result["items"] == 2
    upload.assert_called_once()

    uploaded_items = upload.call_args[0][1]
    for item in uploaded_items:
        assert "id" in item
        assert item["status"] in ("as_good_as_new", "fair")
        assert "store" in item
        assert item["shipping"] == "true"


def test_sync_filters_low_price():
    items = [
        {"id_base": "LPN1", "price": 1.0, "external_category": "X"},
        {"id_base": "LPN2", "price": 5.0, "external_category": "X"},
    ]
    load = MagicMock(return_value=items)
    upload = MagicMock()
    svc = FeedSyncService(load_feed=load, upload_file=upload, min_price=2.0)

    result = svc.sync()
    assert result["items"] == 1


def test_sync_motor_exempt_from_price_filter():
    items = [
        {"id_base": "LPN1", "price": 0.5, "external_category": "Motor coche"},
    ]
    load = MagicMock(return_value=items)
    upload = MagicMock()
    svc = FeedSyncService(load_feed=load, upload_file=upload, min_price=2.0)

    result = svc.sync()
    assert result["items"] == 1


def test_process_sets_shipping():
    svc = FeedSyncService(
        load_feed=MagicMock(), upload_file=MagicMock(),
    )
    items = [
        {"id_base": "L1", "price": 100.0, "external_category": "", "shipping_weight_kg": 2.0},
        {"id_base": "L2", "price": 50.0, "external_category": "", "shipping_weight_kg": 35.0},
    ]
    result = svc.process(items)
    assert result[0]["shipping"] == "true"
    assert result[1]["shipping"] == ""


def test_process_sets_free_shipping():
    svc = FeedSyncService(
        load_feed=MagicMock(), upload_file=MagicMock(),
    )
    items = [
        {"id_base": "L1", "price": 100.0, "external_category": "", "shipping_weight_kg": 2.0},
        {"id_base": "L2", "price": 50.0, "external_category": "", "shipping_weight_kg": 2.0},
    ]
    result = svc.process(items)
    assert result[0]["free_shipping"] == "true"
    assert result[1]["free_shipping"] == ""


def test_process_normalizes_images():
    svc = FeedSyncService(
        load_feed=MagicMock(), upload_file=MagicMock(),
    )
    items = [
        {"id_base": "L1", "price": 10.0, "external_category": "",
         "images_raw": "a.jpg, b.jpg, c.jpg"},
    ]
    result = svc.process(items)
    assert result[0]["images"] == "a.jpg|b.jpg|c.jpg"


def test_process_truncates_title():
    def build_title(item):
        return "A" * 100

    svc = FeedSyncService(
        load_feed=MagicMock(), upload_file=MagicMock(),
        build_title=build_title, max_title_len=60,
    )
    items = [{"id_base": "L1", "price": 10.0, "external_category": ""}]
    result = svc.process(items)
    assert len(result[0]["title"]) == 60


def test_process_truncates_description():
    def build_desc(item):
        return "B" * 1000

    svc = FeedSyncService(
        load_feed=MagicMock(), upload_file=MagicMock(),
        build_description=build_desc, max_desc_len=640,
    )
    items = [{"id_base": "L1", "price": 10.0, "external_category": ""}]
    result = svc.process(items)
    assert len(result[0]["description"]) == 640


def test_process_id_truncated():
    svc = FeedSyncService(
        load_feed=MagicMock(), upload_file=MagicMock(),
        max_id_len=20,
    )
    items = [{"id_base": "A" * 25, "price": 10.0, "external_category": ""}]
    result = svc.process(items)
    assert len(result[0]["id"]) <= 20


def test_process_dedup_integration():
    svc = FeedSyncService(
        load_feed=MagicMock(), upload_file=MagicMock(),
    )
    items = [
        {"id_base": "L1", "asin": "A1", "condition_code": "PERFECTO",
         "price": 10.0, "external_category": ""},
        {"id_base": "L2", "asin": "A1", "condition_code": "PERFECTO",
         "price": 8.0, "external_category": ""},
    ]
    result = svc.process(items)
    assert len(result) == 1
    assert result[0]["stock"] == 2
    assert result[0]["price"] == 8.0
