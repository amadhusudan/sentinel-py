from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING

import pytest

from sentinel import AsyncLogger, SentinelConfig

if TYPE_CHECKING:
    from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture
def log_file(tmp_path) -> Path:
    return tmp_path / "logs.jsonl"


@pytest.fixture
def logger(log_file):
    inst = AsyncLogger(SentinelConfig(log_file=log_file))
    yield inst
    inst.shutdown()


def test_logger_writes_single_record_to_file(logger, log_file):
    logger.log({"event": "test", "value": 42})
    logger.shutdown()

    records = _read_jsonl(log_file)
    assert len(records) == 1
    assert records[0]["event"] == "test"
    assert records[0]["value"] == 42


def test_logger_writes_multiple_records_in_order(logger, log_file):
    for i in range(20):
        logger.log({"i": i})
    logger.shutdown()

    records = _read_jsonl(log_file)
    assert [r["i"] for r in records] == list(range(20))


def test_logger_injects_timestamp_field(logger, log_file):
    logger.log({"event": "x"})
    logger.shutdown()

    records = _read_jsonl(log_file)
    assert "timestamp" in records[0]
    # ISO-8601 with timezone offset
    assert "T" in records[0]["timestamp"]
    assert records[0]["timestamp"].endswith("+00:00")


def test_logger_user_can_override_timestamp(logger, log_file):
    logger.log({"timestamp": "2020-01-01T00:00:00+00:00", "event": "x"})
    logger.shutdown()

    records = _read_jsonl(log_file)
    assert records[0]["timestamp"] == "2020-01-01T00:00:00+00:00"


def test_logger_serializes_non_json_native_values_via_str(logger, log_file):
    class Custom:
        def __str__(self) -> str:
            return "custom-instance"

    logger.log({"obj": Custom(), "set": {1, 2, 3}})
    logger.shutdown()

    records = _read_jsonl(log_file)
    assert records[0]["obj"] == "custom-instance"
    # set repr will be a string like "{1, 2, 3}"
    assert isinstance(records[0]["set"], str)


def test_logger_creates_missing_parent_directory(tmp_path):
    nested = tmp_path / "a" / "b" / "c" / "log.jsonl"
    inst = AsyncLogger(SentinelConfig(log_file=nested))

    inst.log({"event": "x"})
    inst.shutdown()

    assert nested.exists()


def test_logger_shutdown_is_idempotent(logger):
    logger.shutdown()
    logger.shutdown()  # must not raise or hang
    logger.shutdown()


def test_logger_log_after_shutdown_drops_with_warning(logger, log_file, caplog):
    logger.log({"event": "before"})
    logger.shutdown()

    with caplog.at_level(logging.WARNING, logger="sentinel"):
        logger.log({"event": "after"})

    records = _read_jsonl(log_file)
    assert [r["event"] for r in records] == ["before"]
    assert any("after shutdown" in rec.message for rec in caplog.records)


def test_logger_flush_drains_queue(logger, log_file):
    for i in range(50):
        logger.log({"i": i})

    assert logger.flush(timeout=2.0) is True

    # File should contain all records even though we haven't called shutdown.
    records = _read_jsonl(log_file)
    assert len(records) == 50


def test_logger_queue_full_drops_with_warning(tmp_path, caplog):
    config = SentinelConfig(log_file=tmp_path / "log.jsonl", max_queue_size=1)
    inst = AsyncLogger(config)

    in_write = threading.Event()
    unblock = threading.Event()

    def slow_write(record, fh):
        in_write.set()
        unblock.wait(timeout=5.0)
        fh.write(json.dumps(record) + "\n")

    inst._write_record = slow_write  # type: ignore[assignment]

    inst.log({"i": 1})  # worker grabs this and blocks
    assert in_write.wait(timeout=2.0)

    inst.log({"i": 2})  # fills queue (size=1)

    with caplog.at_level(logging.WARNING, logger="sentinel"):
        inst.log({"i": 3})  # must drop

    assert any("queue full" in rec.message for rec in caplog.records)

    unblock.set()
    inst.shutdown()


def test_logger_uses_logging_module_not_print(capsys, logger, log_file):
    logger.log({"event": "x"})
    logger.shutdown()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_logger_concurrent_writers_all_records_persisted(log_file):
    inst = AsyncLogger(
        SentinelConfig(log_file=log_file, max_queue_size=10_000, enqueue_timeout=1.0)
    )

    def writer(start: int) -> None:
        for i in range(start, start + 100):
            inst.log({"i": i})

    threads = [threading.Thread(target=writer, args=(s,)) for s in range(0, 1000, 100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    inst.shutdown()

    records = _read_jsonl(log_file)
    assert sorted(r["i"] for r in records) == list(range(1000))


def test_logger_worker_survives_serialization_errors(tmp_path, caplog):
    inst = AsyncLogger(SentinelConfig(log_file=tmp_path / "log.jsonl"))

    class Unstringable:
        def __str__(self) -> str:
            raise RuntimeError("nope")

    with caplog.at_level(logging.ERROR, logger="sentinel"):
        inst.log({"bad": Unstringable()})
        inst.log({"good": "yes"})

    inst.shutdown()

    # Worker stayed alive, the second record landed.
    records = _read_jsonl(tmp_path / "log.jsonl")
    assert any(r.get("good") == "yes" for r in records)
    assert any("failed to serialize" in rec.message for rec in caplog.records)
    assert inst.is_healthy() is True


def test_logger_is_healthy_after_construction(logger):
    assert logger.is_healthy() is True


def test_logger_io_error_marks_worker_unhealthy(tmp_path, caplog):
    inst = AsyncLogger(SentinelConfig(log_file=tmp_path / "log.jsonl"))

    def failing_write(record, fh):
        raise OSError("disk gone")

    inst._write_record = failing_write  # type: ignore[assignment]

    with caplog.at_level(logging.ERROR, logger="sentinel"):
        inst.log({"trigger": "death"})
        # Wait for the worker to actually die.
        inst._worker.join(timeout=2.0)

    assert inst.is_healthy() is False
    assert any("worker died" in rec.message for rec in caplog.records)


def test_logger_log_after_worker_death_drops_with_warning(tmp_path, caplog):
    inst = AsyncLogger(SentinelConfig(log_file=tmp_path / "log.jsonl"))

    def failing_write(record, fh):
        raise OSError("disk gone")

    inst._write_record = failing_write  # type: ignore[assignment]
    inst.log({"trigger": "death"})
    inst._worker.join(timeout=2.0)
    assert inst.is_healthy() is False

    with caplog.at_level(logging.WARNING, logger="sentinel"):
        inst.log({"event": "after death"})

    assert any("failed logger" in rec.message for rec in caplog.records)


def test_logger_flush_returns_false_after_worker_death(tmp_path):
    inst = AsyncLogger(SentinelConfig(log_file=tmp_path / "log.jsonl"))

    def failing_write(record, fh):
        raise OSError("disk gone")

    inst._write_record = failing_write  # type: ignore[assignment]
    inst.log({"trigger": "death"})
    inst._worker.join(timeout=2.0)

    assert inst.flush(timeout=1.0) is False


def test_logger_shutdown_after_worker_death_is_safe(tmp_path):
    inst = AsyncLogger(SentinelConfig(log_file=tmp_path / "log.jsonl"))

    def failing_write(record, fh):
        raise OSError("disk gone")

    inst._write_record = failing_write  # type: ignore[assignment]
    inst.log({"trigger": "death"})
    inst._worker.join(timeout=2.0)

    inst.shutdown(timeout=1.0)  # must not raise or hang
