from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

import pytest

from sentinel import (
    AsyncLogger,
    SentinelConfig,
    TimeBlock,
    current_span_id,
    current_trace_id,
    set_default_logger,
    tag,
    trace,
)
from sentinel import tracer as tracer_module

if TYPE_CHECKING:
    from pathlib import Path


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


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


# ---------------------------------------------------------------------------
# B1 — trace + span IDs with parent linkage
# ---------------------------------------------------------------------------


def test_trace_records_include_trace_and_span_ids(logger, log_file):
    @trace(logger)
    def f() -> None:
        pass

    f()
    logger.shutdown()

    record = _read(log_file)[0]
    assert isinstance(record["trace_id"], str)
    assert len(record["trace_id"]) > 0
    assert isinstance(record["span_id"], str)
    assert len(record["span_id"]) > 0
    assert record["parent_span_id"] is None


def test_nested_trace_calls_share_trace_id_and_link_parent(logger, log_file):
    @trace(logger)
    def inner() -> None:
        pass

    @trace(logger)
    def outer() -> None:
        inner()

    outer()
    logger.shutdown()

    records = _read(log_file)
    # Post-order: inner finishes (and emits) before outer.
    assert records[0]["function"] == "inner"
    assert records[1]["function"] == "outer"
    assert records[0]["trace_id"] == records[1]["trace_id"]
    assert records[0]["parent_span_id"] == records[1]["span_id"]
    assert records[1]["parent_span_id"] is None


def test_independent_traces_get_distinct_trace_ids(logger, log_file):
    @trace(logger)
    def f() -> None:
        pass

    f()
    f()
    logger.shutdown()

    records = _read(log_file)
    assert records[0]["trace_id"] != records[1]["trace_id"]


async def test_async_trace_propagates_trace_id(logger, log_file):
    @trace(logger)
    async def inner() -> None:
        await asyncio.sleep(0)

    @trace(logger)
    async def outer() -> None:
        await inner()

    await outer()
    logger.shutdown()

    records = _read(log_file)
    assert records[0]["trace_id"] == records[1]["trace_id"]
    assert records[0]["parent_span_id"] == records[1]["span_id"]


def test_timeblock_participates_in_trace_tree(logger, log_file):
    @trace(logger)
    def outer() -> None:
        with TimeBlock(logger, label="work"):
            pass

    outer()
    logger.shutdown()

    records = _read(log_file)
    assert records[0]["label"] == "work"
    assert records[1]["function"] == "outer"
    assert records[0]["trace_id"] == records[1]["trace_id"]
    assert records[0]["parent_span_id"] == records[1]["span_id"]


def test_timeblock_starts_fresh_trace_when_standalone(logger, log_file):
    with TimeBlock(logger, label="solo"):
        pass

    logger.shutdown()
    record = _read(log_file)[0]
    assert record["parent_span_id"] is None
    assert isinstance(record["trace_id"], str) and len(record["trace_id"]) > 0


def test_current_trace_id_returns_none_outside_trace():
    assert current_trace_id() is None
    assert current_span_id() is None


def test_current_trace_id_visible_inside_trace(logger):
    seen: list[str | None] = []

    @trace(logger)
    def f() -> None:
        seen.append(current_trace_id())

    f()
    logger.shutdown()

    assert seen[0] is not None
    assert len(seen[0]) > 0


def test_trace_context_pops_after_call(logger):
    @trace(logger)
    def f() -> None:
        pass

    f()
    logger.shutdown()

    # Outside the @trace call, context vars must be back to their defaults.
    assert current_trace_id() is None
    assert current_span_id() is None


# ---------------------------------------------------------------------------
# B2 — custom tags via context
# ---------------------------------------------------------------------------


def test_tag_attaches_to_records_in_scope(logger, log_file):
    @trace(logger)
    def f() -> None:
        pass

    with tag(user_id=42, request_id="abc"):
        f()

    logger.shutdown()
    record = _read(log_file)[0]
    assert record["tags"] == {"user_id": 42, "request_id": "abc"}


def test_tag_field_absent_when_no_tags(logger, log_file):
    @trace(logger)
    def f() -> None:
        pass

    f()
    logger.shutdown()
    record = _read(log_file)[0]
    assert "tags" not in record


def test_tag_nesting_merges_with_inner_overriding(logger, log_file):
    @trace(logger)
    def f() -> None:
        pass

    with tag(env="prod", user_id=1), tag(user_id=2):
        f()

    logger.shutdown()
    record = _read(log_file)[0]
    assert record["tags"] == {"env": "prod", "user_id": 2}


def test_tag_pops_on_scope_exit(logger, log_file):
    @trace(logger)
    def f() -> None:
        pass

    with tag(scoped="yes"):
        f()
    f()

    logger.shutdown()
    records = _read(log_file)
    assert records[0]["tags"] == {"scoped": "yes"}
    assert "tags" not in records[1]


def test_tag_visible_on_timeblock_records(logger, log_file):
    with tag(component="ingest"), TimeBlock(logger, label="block"):
        pass

    logger.shutdown()
    record = _read(log_file)[0]
    assert record["tags"] == {"component": "ingest"}


# ---------------------------------------------------------------------------
# B4 — slow-call threshold
# ---------------------------------------------------------------------------


def test_slow_threshold_breached_marks_slow_true(logger, log_file):
    @trace(logger, slow_ms=10)
    def f() -> None:
        time.sleep(0.02)

    f()
    logger.shutdown()

    record = _read(log_file)[0]
    assert record.get("slow") is True


def test_slow_threshold_not_breached_no_slow_field(logger, log_file):
    @trace(logger, slow_ms=10_000)
    def f() -> None:
        pass

    f()
    logger.shutdown()

    record = _read(log_file)[0]
    assert "slow" not in record


def test_slow_disabled_no_slow_field_even_when_slow(logger, log_file):
    @trace(logger)
    def f() -> None:
        time.sleep(0.02)

    f()
    logger.shutdown()

    record = _read(log_file)[0]
    assert "slow" not in record


# ---------------------------------------------------------------------------
# B6 — CPU vs wall time
# ---------------------------------------------------------------------------


def test_cpu_time_in_record(logger, log_file):
    @trace(logger)
    def f() -> int:
        return sum(range(100))

    f()
    logger.shutdown()
    record = _read(log_file)[0]
    assert "cpu_time_ms" in record
    assert record["cpu_time_ms"] >= 0


def test_cpu_time_less_than_wall_time_when_sleeping(logger, log_file):
    @trace(logger)
    def f() -> None:
        time.sleep(0.05)

    f()
    logger.shutdown()
    record = _read(log_file)[0]
    # Sleep does not consume CPU, so cpu_time should be markedly less than wall.
    # Allow a small absolute slack for scheduler noise.
    assert record["cpu_time_ms"] < record["duration_ms"] - 10


def test_cpu_time_on_timeblock(logger, log_file):
    with TimeBlock(logger, label="block"):
        sum(range(1000))

    logger.shutdown()
    record = _read(log_file)[0]
    assert "cpu_time_ms" in record
    assert record["cpu_time_ms"] >= 0


# ---------------------------------------------------------------------------
# B13 — sampling
# ---------------------------------------------------------------------------


def test_sample_one_always_emits(logger, log_file):
    @trace(logger, sample=1.0)
    def f() -> None:
        pass

    for _ in range(10):
        f()
    logger.shutdown()

    assert len(_read(log_file)) == 10


def test_sample_zero_never_emits(logger, log_file):
    @trace(logger, sample=0.0)
    def f() -> None:
        pass

    for _ in range(100):
        f()
    logger.shutdown()

    assert _read(log_file) == []


def test_sample_inherited_when_parent_drops(logger, log_file):
    @trace(logger, sample=1.0)
    def inner() -> None:
        pass

    @trace(logger, sample=0.0)
    def root() -> None:
        inner()  # inherited drop, even though local sample=1.0

    root()
    logger.shutdown()

    assert _read(log_file) == []


def test_sample_inherited_when_parent_keeps(logger, log_file):
    @trace(logger, sample=0.0)
    def inner() -> None:
        pass

    @trace(logger, sample=1.0)
    def root() -> None:
        inner()
        inner()

    root()
    logger.shutdown()

    records = _read(log_file)
    assert len(records) == 3  # 2 inner + 1 root, all kept


def test_sampled_out_function_still_runs(logger):
    called: list[str] = []

    @trace(logger, sample=0.0)
    def f() -> str:
        called.append("yes")
        return "result"

    assert f() == "result"
    assert called == ["yes"]
    logger.shutdown()


async def test_async_trace_sample_zero_drops_record(logger, log_file):
    """Cover the async wrapper's `if span.sampled` false branch."""

    @trace(logger, sample=0.0)
    async def f() -> str:
        return "ok"

    assert await f() == "ok"
    logger.shutdown()
    assert _read(log_file) == []


def test_timeblock_sample_zero_drops_record(logger, log_file):
    """Cover TimeBlock.__exit__'s `if span.sampled` false branch."""

    with TimeBlock(logger, label="dropped", sample=0.0):
        pass

    logger.shutdown()
    assert _read(log_file) == []


def test_sampled_out_call_still_exposes_trace_id_in_context(logger):
    seen: list[str | None] = []

    @trace(logger, sample=0.0)
    def f() -> None:
        seen.append(current_trace_id())

    f()
    logger.shutdown()

    # Even when sampled out, the trace context is established inside the call
    # so that nested operations and any user-side logging can correlate.
    assert seen[0] is not None
