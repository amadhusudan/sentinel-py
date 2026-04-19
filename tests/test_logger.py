import os
import time
import json
from sentinel import AsyncLogger, SentinelConfig

def test_logger_writes_to_file(tmp_path):
    log_file = tmp_path / "test_logs.jsonl"
    config = SentinelConfig(log_file=str(log_file))
    
    logger = AsyncLogger(config=config)
    
    test_data = {"event": "test", "value": 42}
    logger.log(test_data)
    
    logger.shutdown()
    
    assert log_file.exists()
    with open(log_file, "r") as f:
        content = json.loads(f.read())
        assert content["event"] == "test"
        assert content["value"] == 42