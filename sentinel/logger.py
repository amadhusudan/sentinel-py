import threading
import queue
import time
from typing import Any, Dict, Optional
import json
import atexit
from sentinel.config import SentinelConfig

class AsyncLogger:
    def __init__(self, config: Optional[SentinelConfig] = None):
        self._config = config or SentinelConfig()
        self._queue: queue.Queue = queue.Queue(maxsize=self._config.max_queue_size)
        self._sentinel = object()
        self._worker_thread = threading.Thread(target=self._process_logs, daemon=True)
        self._worker_thread.start()
        atexit.register(self.shutdown)

    def _process_logs(self):
        """The background worker logic."""
        while True:
            item = self._queue.get()
            if item is self._sentinel:
                self._queue.task_done() 
                break

            self._write_to_storage(item)
            self._queue.task_done()

    def _write_to_storage(self, data: Dict[str, Any]):
        """Appends a single log entry as a JSON line."""
        try:
            with open(self._config.log_file, "a", encoding="utf-8") as f:
                line = json.dumps(data)
                f.write(line + "\n")
        except Exception as e:
            print(f"Logging Error: {e}")

    def log(self, data: Dict[str, Any]):
        """The public method to drop data into the queue."""
        try:
            self._queue.put(data, timeout=0.1)
        except queue.Full:
            print("[SENTINEL] Warning: Log queue full, dropping record.")

    def shutdown(self):
        """Cleanly close the thread."""
        self._queue.join()
        self._queue.put(self._sentinel)
        self._worker_thread.join()

