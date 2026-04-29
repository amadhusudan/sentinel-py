from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import pytest

from sentinel import AsyncLogger, SentinelConfig, TimeBlock, set_default_logger, trace
from sentinel import tracer as tracer_module

if TYPE_CHECKING:
    from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@pytest.fixture
def log_file(tmp_path) -> Path:
    return tmp_path / "trace.jsonl"


@pytest.fixture
def logger(log_file):
    inst = AsyncLogger(SentinelConfig(log_file=log_file))
    yield inst
    inst.shutdown()


@pytest.fixture(autouse=True)
def reset_default_logger():
    yield
    if tracer_module._default_logger is not None:
        tracer_module._default_logger.shutdown()
    set_default_logger(None)


def test_trace_records_sync_function_success(logger, log_file):
    @trace(logger)
    def add(a: int, b: int) -> int:
        return a + b

    assert add(2, 3) == 5
    logger.shutdown()

    records = _read_jsonl(log_file)
    assert len(records) == 1
    assert records[0]["function"] == "add"
    assert records[0]["status"] == "success"
    assert records[0]["error_type"] is None
    assert records[0]["duration_ms"] >= 0


def test_trace_appends_label_to_function_name(logger, log_file):
    @trace(logger, label="checkout")
    def run() -> str:
        return "ok"

    run()
    logger.shutdown()

    records = _read_jsonl(log_file)
    assert records[0]["function"] == "run[checkout]"


def test_trace_label_disambiguates_same_function_name(logger, log_file):
    @trace(logger, label="primary")
    def run() -> str:
        return "a"

    @trace(logger, label="secondary")
    def run() -> str:  # noqa: F811 — intentional shadowing for the test
        return "b"

    run()
    logger.shutdown()

    records = _read_jsonl(log_file)
    assert len(records) == 1
    assert records[0]["function"] == "run[secondary]"


async def test_trace_label_propagates_to_async_records(logger, log_file):
    @trace(logger, label="signup")
    async def go() -> str:
        return "done"

    await go()
    logger.shutdown()

    records = _read_jsonl(log_file)
    assert records[0]["function"] == "go[signup]"


def test_trace_label_persists_on_error(logger, log_file):
    @trace(logger, label="risky")
    def fail() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError):
        fail()

    logger.shutdown()

    records = _read_jsonl(log_file)
    assert records[0]["function"] == "fail[risky]"
    assert records[0]["status"] == "error"


def test_trace_records_sync_function_exception_and_reraises(logger, log_file):
    @trace(logger)
    def boom() -> None:
        raise ValueError("bad input #42")

    with pytest.raises(ValueError, match="bad input #42"):
        boom()

    logger.shutdown()

    records = _read_jsonl(log_file)
    assert len(records) == 1
    assert records[0]["status"] == "error"
    assert records[0]["error_type"] == "ValueError"
    assert records[0]["error"] == "bad input #42"


def test_trace_records_async_exception_includes_message(logger, log_file):
    @trace(logger)
    async def fail() -> None:
        raise RuntimeError("kaboom 99")

    with pytest.raises(RuntimeError):
        import asyncio

        asyncio.run(fail())

    logger.shutdown()

    records = _read_jsonl(log_file)
    assert records[0]["error_type"] == "RuntimeError"
    assert records[0]["error"] == "kaboom 99"


def test_trace_success_records_have_null_error(logger, log_file):
    @trace(logger)
    def ok() -> int:
        return 1

    ok()
    logger.shutdown()

    records = _read_jsonl(log_file)
    assert records[0]["error"] is None


async def test_trace_records_async_function_success(logger, log_file):
    @trace(logger)
    async def fetch() -> str:
        await asyncio.sleep(0.01)
        return "ok"

    assert await fetch() == "ok"
    logger.shutdown()

    records = _read_jsonl(log_file)
    assert records[0]["function"] == "fetch"
    assert records[0]["status"] == "success"
    # Awaited sleep counted toward duration.
    assert records[0]["duration_ms"] >= 10


async def test_trace_records_async_function_exception_and_reraises(logger, log_file):
    @trace(logger)
    async def fail() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError, match="kaboom"):
        await fail()

    logger.shutdown()

    records = _read_jsonl(log_file)
    assert records[0]["status"] == "error"
    assert records[0]["error_type"] == "RuntimeError"


def test_trace_preserves_function_metadata(logger):
    @trace(logger)
    def documented(x: int) -> int:
        """Adds one."""
        return x + 1

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Adds one."


def test_trace_resolves_default_logger_at_call_time(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    @trace()
    def f() -> int:
        return 7

    # Now install our own default logger AFTER decoration.
    target_file = tmp_path / "late.jsonl"
    custom = AsyncLogger(SentinelConfig(log_file=target_file))
    set_default_logger(custom)

    assert f() == 7
    custom.shutdown()

    records = _read_jsonl(target_file)
    assert len(records) == 1
    assert records[0]["function"] == "f"


def test_trace_default_logger_singleton_is_thread_safe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    set_default_logger(None)

    import threading

    seen: list[AsyncLogger] = []
    barrier = threading.Barrier(10)

    def grab() -> None:
        barrier.wait()
        seen.append(tracer_module.get_logger())

    threads = [threading.Thread(target=grab) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All threads got the same instance.
    assert len({id(x) for x in seen}) == 1


def test_trace_with_explicit_none_uses_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    custom = AsyncLogger(SentinelConfig(log_file=tmp_path / "x.jsonl"))
    set_default_logger(custom)

    @trace(logger=None)
    def f() -> str:
        return "y"

    assert f() == "y"
    custom.shutdown()

    records = _read_jsonl(tmp_path / "x.jsonl")
    assert records[0]["function"] == "f"


def test_timeblock_records_success(logger, log_file):
    with TimeBlock(logger, label="work"):
        pass
    logger.shutdown()

    records = _read_jsonl(log_file)
    assert records[0]["label"] == "work"
    assert records[0]["status"] == "success"
    assert records[0]["error_type"] is None
    assert records[0]["error"] is None


def test_timeblock_records_error_and_propagates(logger, log_file):
    with pytest.raises(KeyError), TimeBlock(logger, label="boom"):
        raise KeyError("missing")

    logger.shutdown()

    records = _read_jsonl(log_file)
    assert records[0]["label"] == "boom"
    assert records[0]["status"] == "error"
    assert records[0]["error_type"] == "KeyError"
    assert "missing" in records[0]["error"]


def test_timeblock_duration_is_positive(logger, log_file):
    import time

    with TimeBlock(logger, label="sleep"):
        time.sleep(0.02)

    logger.shutdown()

    records = _read_jsonl(log_file)
    assert records[0]["label"] == "sleep"
    assert records[0]["duration_ms"] >= 20


def test_trace_decorator_no_logger_argument_works(tmp_path, monkeypatch, caplog):
    monkeypatch.chdir(tmp_path)
    custom = AsyncLogger(SentinelConfig(log_file=tmp_path / "default.jsonl"))
    set_default_logger(custom)

    @trace()
    def add(a: int, b: int) -> int:
        return a + b

    with caplog.at_level(logging.DEBUG, logger="sentinel"):
        assert add(1, 2) == 3

    custom.shutdown()
    records = _read_jsonl(tmp_path / "default.jsonl")
    assert records[0]["function"] == "add"
