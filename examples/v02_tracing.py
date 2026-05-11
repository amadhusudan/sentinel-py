"""Example exercising every v0.2.0 feature: trace+span IDs, tags, slow-call
threshold, CPU time, sampling, and the CLI live-tail.

Run:
    python examples/v02_tracing.py
    sentinel tail /tmp/sentinel_v02_example.jsonl
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

from sentinel import (
    AsyncLogger,
    SentinelConfig,
    TimeBlock,
    set_default_logger,
    tag,
    trace,
)


def main() -> None:
    log_path = Path(tempfile.gettempdir()) / "sentinel_v02_example.jsonl"
    if log_path.exists():
        log_path.unlink()

    logger = AsyncLogger(SentinelConfig(log_file=log_path))
    set_default_logger(logger)

    # B1 — nested @trace + TimeBlock share a trace_id; child records carry
    # parent_span_id pointing at the enclosing span.
    @trace(logger)
    def fetch_user(user_id: int) -> dict[str, str | int]:
        with TimeBlock(logger, label="db_query"):
            time.sleep(0.005)
        return {"id": user_id, "name": "alice"}

    @trace(logger)
    def render_profile(user_id: int) -> str:
        user = fetch_user(user_id)
        return f"<profile>{user['name']}</profile>"

    # B2 — custom tags attach to every record emitted inside the scope.
    with tag(user_id=42, request_id="req-001"):
        render_profile(42)

    # B4 — slow_ms marks records exceeding the threshold.
    @trace(logger, slow_ms=10)
    def maybe_slow() -> None:
        time.sleep(0.05)  # >> 10ms → record gets `slow: true`

    maybe_slow()

    # B6 — cpu_time_ms is recorded on every call automatically.
    @trace(logger)
    def cpu_bound() -> int:
        return sum(i * i for i in range(100_000))

    cpu_bound()

    # B13 — sample=0.5 emits ~50% of root traces; children inherit the
    # decision so a kept trace stays kept end-to-end.
    @trace(logger, sample=0.5)
    def maybe_logged() -> None:
        pass

    for _ in range(20):
        maybe_logged()

    # Async path
    @trace(logger)
    async def async_op() -> None:
        await asyncio.sleep(0.01)

    asyncio.run(async_op())

    logger.flush(timeout=2.0)
    logger.shutdown(timeout=2.0)

    print(f"Wrote records to {log_path}")
    print(f"Inspect with:\n    sentinel tail {log_path}")


if __name__ == "__main__":
    main()
