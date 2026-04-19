import threading
import queue
import time
from typing import Any, Dict
import json

class AsyncLogger:
    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        # The sentinel value tells the thread to stop
        self._sentinel = object()
        self._worker_thread = threading.Thread(target=self._process_logs, daemon=True)
        self._worker_thread.start()

    def _process_logs(self):
        """The background worker logic."""
        while True:
            item = self._queue.get()
            if item is self._sentinel:
                break
            
            # For now, we just print. 
            # Later, this will write to SQLite.
            self._write_to_storage(item)
            self._queue.task_done()

    def _write_to_storage(self, data: Dict[str, Any]):
        """Appends a single log entry as a JSON line."""
        time.sleep(0.01)  # 10ms delay
        print(f"[SENTINEL-LOG] {data}")
        try:
            with open("sentinel_logs.jsonl", "a", encoding="utf-8") as f:
                # json.dumps converts the dict to a string
                line = json.dumps(data)
                f.write(line + "\n")
        except Exception as e:
            # Crucial: If logging fails, don't crash the main app!
            print(f"Logging Error: {e}")

    def log(self, data: Dict[str, Any]):
        """The public method to drop data into the queue."""
        self._queue.put(data)

    def shutdown(self):
        """Cleanly close the thread."""
        self._queue.put(self._sentinel)
        self._worker_thread.join()

