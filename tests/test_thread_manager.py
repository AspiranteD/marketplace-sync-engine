"""Tests for ThreadManager."""
import pytest
import threading
import time
from unittest.mock import MagicMock

from src.worker.thread_manager import ThreadManager, WriterMessage


# ─── WriterMessage ──────────────────────────────────────────────────────────

def test_message_basic():
    msg = WriterMessage(tipo="create", datos={"id": 1})
    assert msg.tipo == "create"
    assert msg.datos == {"id": 1}
    assert msg.account_id is None
    assert msg.callback is None


def test_message_with_all_fields():
    cb = MagicMock()
    msg = WriterMessage(tipo="update", datos=[1, 2], account_id=5, callback=cb)
    assert msg.account_id == 5
    assert msg.callback is cb


# ─── Disabled (passthrough) mode ────────────────────────────────────────────

def test_disabled_by_default():
    tm = ThreadManager()
    assert not tm.enabled


def test_disabled_start_is_noop():
    tm = ThreadManager(enabled=False)
    tm.start_writer()
    assert tm.writer_thread is None


def test_disabled_stop_is_noop():
    tm = ThreadManager(enabled=False)
    tm.stop_writer()


def test_disabled_enqueue_is_noop():
    tm = ThreadManager(enabled=False)
    tm.enqueue("create", {"id": 1})
    assert tm.task_queue.empty()


def test_disabled_wait_is_noop():
    tm = ThreadManager(enabled=False)
    tm.wait_for_completion(timeout=1)


def test_disabled_flush_is_noop():
    tm = ThreadManager(enabled=False)
    tm._flush_buffers()


# ─── Enabled mode ──────────────────────────────────────────────────────────

def test_enabled_start_stop():
    tm = ThreadManager(enabled=True)
    tm.start_writer()
    assert tm.writer_thread is not None
    assert tm.writer_thread.is_alive()
    tm.stop_writer()
    assert not tm.writer_thread.is_alive()


def test_process_single_create():
    tm = ThreadManager(enabled=True)
    cb = MagicMock()
    tm.set_callback("create", cb)
    tm.start_writer()

    tm.enqueue("create", {"id": 1})
    time.sleep(0.5)

    tm.stop_writer()
    cb.assert_called_once_with({"id": 1})


def test_process_single_update():
    tm = ThreadManager(enabled=True)
    cb = MagicMock()
    tm.set_callback("update", cb)
    tm.start_writer()

    tm.enqueue("update", {"id": 2, "name": "test"})
    time.sleep(0.5)

    tm.stop_writer()
    cb.assert_called_once()


def test_process_batch_create():
    tm = ThreadManager(enabled=True)
    cb = MagicMock()
    tm.set_callback("batch_create", cb)
    tm.start_writer()

    data = [{"id": i} for i in range(5)]
    tm.enqueue("batch_create", data)
    time.sleep(0.5)

    tm.stop_writer()
    cb.assert_called_once_with(data)


def test_process_progress():
    tm = ThreadManager(enabled=True)
    cb = MagicMock()
    tm.set_callback("progress", cb)
    tm.start_writer()

    tm.enqueue("progress", {"percent": 50}, account_id=3)
    time.sleep(0.5)

    tm.stop_writer()
    cb.assert_called_once_with({"percent": 50}, 3)


# ─── Buffer mode ───────────────────────────────────────────────────────────

def test_buffer_create_accumulates():
    tm = ThreadManager(batch_size=3, enabled=True)
    cb = MagicMock()
    tm.set_callback("batch_create", cb)
    tm.start_writer()

    tm.enqueue("create", {"id": 1}, use_buffer=True)
    tm.enqueue("create", {"id": 2}, use_buffer=True)
    assert len(tm.create_buffer) == 2
    cb.assert_not_called()

    tm.stop_writer()


def test_buffer_auto_flush_at_batch_size():
    tm = ThreadManager(batch_size=2, enabled=True)
    cb = MagicMock()
    tm.set_callback("batch_create", cb)

    tm.enqueue("create", {"id": 1}, use_buffer=True)
    tm.enqueue("create", {"id": 2}, use_buffer=True)

    cb.assert_called_once()
    assert len(tm.create_buffer) == 0


def test_buffer_update_accumulates():
    tm = ThreadManager(batch_size=3, enabled=True)
    cb = MagicMock()
    tm.set_callback("batch_update", cb)
    tm.start_writer()

    tm.enqueue("update", {"id": 1}, use_buffer=True)
    assert len(tm.update_buffer) == 1

    tm.stop_writer()


def test_buffer_flush_on_stop():
    tm = ThreadManager(batch_size=100, enabled=True)
    cb = MagicMock()
    tm.set_callback("batch_create", cb)
    tm.start_writer()

    tm.enqueue("create", {"id": 1}, use_buffer=True)
    tm.enqueue("create", {"id": 2}, use_buffer=True)

    tm.stop_writer()
    cb.assert_called_once()
    assert len(cb.call_args[0][0]) == 2


# ─── Locks ──────────────────────────────────────────────────────────────────

def test_get_named_lock():
    tm = ThreadManager()
    for name in ("hashes", "counter", "state", "cache"):
        lock = tm.get_lock(name)
        assert hasattr(lock, "acquire")
        assert hasattr(lock, "release")


def test_get_unknown_lock():
    tm = ThreadManager()
    lock = tm.get_lock("unknown")
    assert hasattr(lock, "acquire")
    assert hasattr(lock, "release")


def test_named_locks_are_different():
    tm = ThreadManager()
    assert tm.get_lock("hashes") is not tm.get_lock("counter")
    assert tm.get_lock("state") is not tm.get_lock("cache")


def test_same_named_lock_is_same():
    tm = ThreadManager()
    assert tm.get_lock("hashes") is tm.get_lock("hashes")


# ─── Callbacks ──────────────────────────────────────────────────────────────

def test_set_callback():
    tm = ThreadManager()
    cb = MagicMock()
    tm.set_callback("create", cb)
    assert tm.callbacks["create"] is cb


def test_set_invalid_callback():
    tm = ThreadManager()
    cb = MagicMock()
    tm.set_callback("nonexistent", cb)
    assert "nonexistent" not in tm.callbacks


def test_callback_error_doesnt_crash():
    tm = ThreadManager(enabled=True)
    cb = MagicMock(side_effect=RuntimeError("DB down"))
    tm.set_callback("create", cb)
    tm.start_writer()

    tm.enqueue("create", {"id": 1})
    time.sleep(0.5)

    tm.stop_writer()
    cb.assert_called_once()


# ─── Wait for completion ───────────────────────────────────────────────────

def test_wait_timeout():
    tm = ThreadManager(enabled=True)
    tm.start_writer()

    start = time.time()
    tm.wait_for_completion(timeout=1)
    elapsed = time.time() - start

    assert elapsed < 3
    tm.stop_writer()


# ─── Thread safety ─────────────────────────────────────────────────────────

def test_concurrent_enqueue():
    tm = ThreadManager(enabled=True)
    results = []
    cb = MagicMock(side_effect=lambda d: results.append(d))
    tm.set_callback("create", cb)
    tm.start_writer()

    threads = []
    for i in range(10):
        t = threading.Thread(target=tm.enqueue, args=("create", {"id": i}))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    time.sleep(1)
    tm.stop_writer()

    assert len(results) == 10


def test_batch_size_config():
    tm = ThreadManager(batch_size=50)
    assert tm.batch_size == 50


def test_default_batch_size():
    tm = ThreadManager()
    assert tm.batch_size == 100
