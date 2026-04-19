import time
import json
from sentinel import trace, AsyncLogger, SentinelConfig

def test_trace_decorator(tmp_path):
    log_file = tmp_path / "trace_logs.jsonl"
    logger = AsyncLogger(config=SentinelConfig(log_file=str(log_file)))

    @trace(logger=logger)
    def simple_func():
        time.sleep(0.1)
        return "success"

    result = simple_func()
    logger.shutdown()

    assert result == "success"
    
    with open(log_file, "r") as f:
        log_entry = json.loads(f.read())
        assert log_entry["function"] == "simple_func"
        assert log_entry["duration_ms"] >= 100