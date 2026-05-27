"""Tests for store assignment logic."""
import pytest

from src.sync.store_assignment import (
    STORE_MOTOR, STORE_EXPENSIVE, STORE_CHEAP, DEFAULT_TOP_N,
    assign_store, batch_assign_stores,
)


# ─── assign_store ────────────────────────────────────────────────────────────

def test_motor_category_always_motor():
    assert assign_store("Recambios motor", 500.0, 0) == STORE_MOTOR
    assert assign_store("Motor coche", 1.0, 9999) == STORE_MOTOR
    assert assign_store("MOTOR", 0.0, 0) == STORE_MOTOR


def test_motor_case_insensitive():
    assert assign_store("accesorios MOTOR", 100, 0) == STORE_MOTOR


def test_no_price_goes_cheap():
    assert assign_store("Electronics", None, 0) == STORE_CHEAP
    assert assign_store("Electronics", 0, 0) == STORE_CHEAP
    assert assign_store("Electronics", -5, 0) == STORE_CHEAP


def test_expensive_when_few_above():
    assert assign_store("Electronics", 100.0, 4999) == STORE_EXPENSIVE


def test_expensive_at_boundary():
    assert assign_store("Electronics", 100.0, DEFAULT_TOP_N - 1) == STORE_EXPENSIVE


def test_cheap_at_boundary():
    assert assign_store("Electronics", 100.0, DEFAULT_TOP_N) == STORE_CHEAP


def test_cheap_when_many_above():
    assert assign_store("Electronics", 10.0, 10000) == STORE_CHEAP


def test_empty_category_not_motor():
    assert assign_store("", 100.0, 0) == STORE_EXPENSIVE


def test_none_category_not_motor():
    assert assign_store(None, 100.0, 0) == STORE_EXPENSIVE


# ─── batch_assign_stores ────────────────────────────────────────────────────

def test_batch_empty():
    stats = batch_assign_stores([])
    assert stats["total"] == 0


def test_batch_motor_only():
    items = [
        {"category": "Motor", "price": 50.0},
        {"category": "motor recambios", "price": 200.0},
    ]
    stats = batch_assign_stores(items)
    assert stats["motor"] == 2
    assert stats["expensive"] == 0
    assert stats["cheap"] == 0
    for item in items:
        assert item["store"] == STORE_MOTOR


def test_batch_price_ranking():
    items = [{"category": "A", "price": float(i)} for i in range(10)]
    stats = batch_assign_stores(items, top_n=3)

    expensive = [it for it in items if it["store"] == STORE_EXPENSIVE]
    cheap = [it for it in items if it["store"] == STORE_CHEAP]

    assert len(expensive) == 3
    assert len(cheap) == 7
    assert stats["expensive"] == 3
    assert stats["cheap"] == 7


def test_batch_top_n_prices_correct():
    items = [
        {"category": "X", "price": 100.0},
        {"category": "X", "price": 50.0},
        {"category": "X", "price": 200.0},
        {"category": "X", "price": 10.0},
    ]
    batch_assign_stores(items, top_n=2)

    for item in items:
        if item["price"] >= 100.0:
            assert item["store"] == STORE_EXPENSIVE, f"price={item['price']} should be expensive"
        else:
            assert item["store"] == STORE_CHEAP, f"price={item['price']} should be cheap"


def test_batch_mixed_motor_and_ranked():
    items = [
        {"category": "motor", "price": 5.0},
        {"category": "Electronics", "price": 500.0},
        {"category": "Electronics", "price": 100.0},
        {"category": "Electronics", "price": 10.0},
    ]
    stats = batch_assign_stores(items, top_n=1)

    assert items[0]["store"] == STORE_MOTOR
    assert items[1]["store"] == STORE_EXPENSIVE
    assert items[2]["store"] == STORE_CHEAP
    assert items[3]["store"] == STORE_CHEAP
    assert stats["motor"] == 1
    assert stats["expensive"] == 1
    assert stats["cheap"] == 2


def test_batch_zero_price_goes_cheap():
    items = [{"category": "A", "price": 0}]
    batch_assign_stores(items, top_n=10)
    assert items[0]["store"] == STORE_CHEAP


def test_batch_none_price_goes_cheap():
    items = [{"category": "A", "price": None}]
    batch_assign_stores(items, top_n=10)
    assert items[0]["store"] == STORE_CHEAP


def test_batch_tracks_updates():
    items = [
        {"category": "A", "price": 100.0, "store": STORE_CHEAP},
        {"category": "A", "price": 50.0, "store": STORE_CHEAP},
    ]
    stats = batch_assign_stores(items, top_n=1)
    assert stats["updated"] >= 1


def test_batch_tracks_unchanged():
    items = [
        {"category": "A", "price": 100.0, "store": STORE_EXPENSIVE},
    ]
    stats = batch_assign_stores(items, top_n=10)
    assert stats["unchanged"] == 1


def test_batch_custom_keys():
    items = [
        {"cat": "motor", "p": 10.0},
        {"cat": "other", "p": 100.0},
    ]
    stats = batch_assign_stores(items, category_key="cat", price_key="p", top_n=5)
    assert items[0]["store"] == STORE_MOTOR
    assert items[1]["store"] == STORE_EXPENSIVE


def test_batch_large_dataset():
    items = [{"category": "X", "price": float(i)} for i in range(200)]
    stats = batch_assign_stores(items, top_n=50)
    assert stats["expensive"] == 50
    assert stats["cheap"] == 150
    assert stats["total"] == 200


def test_constants():
    assert STORE_MOTOR == 16
    assert STORE_EXPENSIVE == 17
    assert STORE_CHEAP == 14
    assert DEFAULT_TOP_N == 5100
