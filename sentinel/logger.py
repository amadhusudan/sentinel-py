from __future__ import annotations

import atexit
import json
import logging
import queue
import threading
from datetime import datetime, timezone
from typing import Any

from sentinel.config import SentinelConfig

_log = logging.getLogger("sentinel")


class AsyncLogger:
    """Thread-safe, non-blocking JSONL logger backed by a single worker thread."""

    _SENTINEL = object()

    def __init__(self, config: SentinelConfig | None = None) -> None:
        self._config = config or SentinelConfig()
        self._config.log_file.parent.mkdir(parents=True, exist_ok=True)

        self._queue: queue.Queue[Any] = queue.Queue(maxsize=self._config.max_queue_size)
        self._closed = False
        self._worker_failed = False
        self._lock = threading.Lock()

        self._worker = threading.Thread(
            target=self._process_logs,
            name="sentinel-logger",
            daemon=True,
        )
        self._worker.start()
        atexit.register(self.shutdown)

    def _process_logs(self) -> None:
        # Line-buffered so each record is durable as soon as the newline is written.
        try:
            with self._config.log_file.open("a", encoding="utf-8", buffering=1) as fh:
                while True:
                    item = self._queue.get()
                    try:
                        if item is self._SENTINEL:
                            return
                        self._write_record(item, fh)
                    finally:
                        self._queue.task_done()
        except Exception:
            _log.exception("sentinel worker died; further log() calls will be dropped")
            with self._lock:
                self._closed = True
                self._worker_failed = True
            self._drain_queue_after_failure()

    def _drain_queue_after_failure(self) -> None:
        # Mark every remaining item done so any in-flight flush() unblocks.
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
            self._queue.task_done()

    @staticmethod
    def _write_record(record: dict[str, Any], fh: Any) -> None:
        # Serialization errors are recoverable — drop the record, keep the worker alive.
        try:
            line = json.dumps(record, default=str)
        except Exception:
            _log.exception("failed to serialize log record; skipping")
            return
        # I/O errors are not recoverable here — they propagate up to the worker
        # so that self-healing can mark the logger unhealthy.
        fh.write(line + "\n")

    def log(self, data: dict[str, Any]) -> None:
        """Enqueue a record. Drops with a warning if the logger is closed or the queue is full."""
        if self._closed:
            if self._worker_failed:
                _log.warning("log() called on failed logger; dropping record")
            else:
                _log.warning("log() called after shutdown; dropping record")
            return

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }

        try:
            if self._config.enqueue_timeout > 0:
                self._queue.put(record, timeout=self._config.enqueue_timeout)
            else:
                self._queue.put_nowait(record)
        except queue.Full:
            _log.warning("sentinel queue full; dropping record")

    def is_healthy(self) -> bool:
        """Return False if the worker thread has died from an unrecoverable error."""
        return not self._worker_failed

    def flush(self, timeout: float | None = None) -> bool:
        """Block until all currently-queued records have been written.

        Returns False immediately if the worker has died, otherwise True if the
        queue drained within the given timeout (or no timeout was supplied).
        """
        if self._worker_failed:
            return False

        if timeout is None:
            self._queue.join()
            return True

        done = threading.Event()

        def _waiter() -> None:
            self._queue.join()
            done.set()

        threading.Thread(target=_waiter, daemon=True).start()
        return done.wait(timeout)

    def shutdown(self, timeout: float | None = None) -> None:
        """Drain the queue, stop the worker, and close the file. Idempotent."""
        with self._lock:
            if self._closed:
                return
            self._closed = True

        self._queue.put(self._SENTINEL)
        self._worker.join(timeout=timeout)
