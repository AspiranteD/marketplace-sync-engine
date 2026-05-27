"""
ThreadManager for queue-based batch processing of database writes.

Features:
  - Typed message queue (create, update, batch_create, batch_update, progress, stop)
  - Configurable batch size with automatic flush when buffer is full
  - Dedicated writer thread (daemon=False for graceful shutdown)
  - Pluggable callbacks per message type
  - Named locks for synchronized access (hashes, counter, state, cache)
  - Passthrough mode: when disabled, all operations are no-ops
    (existing code manages commits directly)
  - Graceful shutdown: flush pending buffers, signal stop, join with timeout
  - Timeout-based queue polling (0.5s) with periodic buffer checks
"""
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class WriterMessage:
    """Typed message for the writer queue."""
    tipo: str  # 'create', 'update', 'batch_create', 'batch_update', 'progress', 'stop'
    datos: Any
    account_id: Optional[int] = None
    callback: Optional[Callable] = None


class ThreadManager:
    """
    Queue-based batch writer for database operations.

    When enabled=True:
      - Messages are queued and processed by a dedicated writer thread
      - Individual ops (create/update) can optionally buffer for batch commits
      - Buffers auto-flush when they reach batch_size
      - Final flush on shutdown

    When enabled=False (default):
      - All operations are no-ops (passthrough mode)
      - Existing code handles database commits directly
      - No threads are started
    """

    def __init__(self, batch_size: int = 100, enabled: bool = False):
        self.task_queue = queue.Queue()
        self.writer_thread = None
        self.writer_active = threading.Event()
        self.batch_size = batch_size
        self.enabled = enabled

        self.lock_hashes = threading.Lock()
        self.lock_counter = threading.Lock()
        self.lock_state = threading.Lock()
        self.lock_cache = threading.Lock()

        self.callbacks: Dict[str, Optional[Callable]] = {
            "create": None,
            "update": None,
            "batch_create": None,
            "batch_update": None,
            "progress": None,
        }

        self.create_buffer: List[Any] = []
        self.update_buffer: List[Any] = []
        self.buffer_lock = threading.Lock()

    def set_callback(self, tipo: str, callback: Callable):
        """Configure a callback for a specific message type."""
        if tipo in self.callbacks:
            self.callbacks[tipo] = callback

    def start_writer(self):
        """Start the writer thread (only if enabled)."""
        if not self.enabled:
            logger.debug("ThreadManager disabled, skipping writer start")
            return

        if self.writer_thread is None or not self.writer_thread.is_alive():
            self.writer_active.set()
            self.writer_thread = threading.Thread(
                target=self._run_writer,
                name="BatchWriter",
                daemon=False,
            )
            self.writer_thread.start()
            logger.info("Writer thread started")

    def stop_writer(self):
        """Stop the writer thread gracefully."""
        if not self.enabled:
            return

        self.writer_active.clear()
        self.task_queue.put(WriterMessage(tipo="stop", datos=None))
        self._flush_buffers()

        if self.writer_thread:
            self.writer_thread.join(timeout=30)
            if self.writer_thread.is_alive():
                logger.warning("Writer thread did not stop after 30s")
            else:
                logger.info("Writer thread stopped")

    def _run_writer(self):
        """Main writer loop: process messages from queue."""
        logger.info("Writer thread running")

        while self.writer_active.is_set() or not self.task_queue.empty():
            try:
                msg = self.task_queue.get(timeout=0.5)

                if msg.tipo == "stop":
                    break

                if msg.tipo in ("create", "update"):
                    self._process_single(msg)
                elif msg.tipo in ("batch_create", "batch_update"):
                    self._process_batch(msg)
                elif msg.tipo == "progress":
                    self._process_progress(msg)

                self.task_queue.task_done()

            except queue.Empty:
                self._check_and_flush()
                time.sleep(0.1)
            except Exception as e:
                logger.error("Error in writer thread: %s", e)
                time.sleep(2)

        self._flush_buffers()
        logger.info("Writer thread finished")

    def _process_single(self, msg: WriterMessage):
        """Process a single create/update operation."""
        cb = self.callbacks.get(msg.tipo)
        if cb:
            try:
                cb(msg.datos)
            except Exception as e:
                logger.error("Error in %s callback: %s", msg.tipo, e)

    def _process_batch(self, msg: WriterMessage):
        """Process a batch of operations."""
        cb = self.callbacks.get(msg.tipo)
        if cb:
            try:
                cb(msg.datos)
                logger.debug("Batch %s: %d items", msg.tipo, len(msg.datos))
            except Exception as e:
                logger.error("Error in batch %s: %s", msg.tipo, e)

    def _process_progress(self, msg: WriterMessage):
        """Process a progress update."""
        cb = self.callbacks.get("progress")
        if cb:
            try:
                cb(msg.datos, msg.account_id)
            except Exception as e:
                logger.error("Error in progress callback: %s", e)

    def _check_and_flush(self):
        """Check if buffers are full and flush them."""
        if not self.enabled:
            return
        with self.buffer_lock:
            if len(self.create_buffer) >= self.batch_size:
                self._flush_create()
            if len(self.update_buffer) >= self.batch_size:
                self._flush_update()

    def _flush_buffers(self):
        """Flush all pending buffers."""
        if not self.enabled:
            return
        with self.buffer_lock:
            if self.create_buffer:
                self._flush_create()
            if self.update_buffer:
                self._flush_update()

    def _flush_create(self):
        """Flush the create buffer."""
        if not self.create_buffer:
            return
        cb = self.callbacks.get("batch_create")
        if cb:
            try:
                cb(self.create_buffer.copy())
                logger.info("Batch create flushed: %d items", len(self.create_buffer))
            except Exception as e:
                logger.error("Error in batch create flush: %s", e)
        self.create_buffer.clear()

    def _flush_update(self):
        """Flush the update buffer."""
        if not self.update_buffer:
            return
        cb = self.callbacks.get("batch_update")
        if cb:
            try:
                cb(self.update_buffer.copy())
                logger.info("Batch update flushed: %d items", len(self.update_buffer))
            except Exception as e:
                logger.error("Error in batch update flush: %s", e)
        self.update_buffer.clear()

    def enqueue(
        self,
        tipo: str,
        datos: Any,
        account_id: Optional[int] = None,
        callback: Optional[Callable] = None,
        use_buffer: bool = False,
    ):
        """
        Enqueue a message for processing.

        If enabled=False, this is a no-op (passthrough).
        If use_buffer=True and tipo is create/update, accumulates in buffers
        for batch processing.
        """
        if not self.enabled:
            return

        if use_buffer and tipo in ("create", "update"):
            with self.buffer_lock:
                if tipo == "create":
                    self.create_buffer.append(datos)
                    if len(self.create_buffer) >= self.batch_size:
                        self._flush_create()
                elif tipo == "update":
                    self.update_buffer.append(datos)
                    if len(self.update_buffer) >= self.batch_size:
                        self._flush_update()
        else:
            self.task_queue.put(WriterMessage(
                tipo=tipo,
                datos=datos,
                account_id=account_id,
                callback=callback,
            ))

    def wait_for_completion(self, timeout: int = 120):
        """Wait for the queue to drain."""
        if not self.enabled:
            return
        logger.info("Waiting for all messages to be processed...")
        start = time.time()
        while not self.task_queue.empty():
            if time.time() - start > timeout:
                logger.warning("Timeout waiting for completion (%ds)", timeout)
                break
            time.sleep(2)
        self._flush_buffers()

    def get_lock(self, name: str) -> threading.Lock:
        """Get a named lock for external synchronization."""
        locks = {
            "hashes": self.lock_hashes,
            "counter": self.lock_counter,
            "state": self.lock_state,
            "cache": self.lock_cache,
        }
        return locks.get(name, threading.Lock())
