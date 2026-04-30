# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-30

Initial public release. Published to PyPI as `sentinel-trace`.

### Added

- `AsyncLogger` — thread-safe, non-blocking JSONL logger backed by a single
  background worker thread. Auto-injected ISO-8601 UTC `timestamp` on every
  record. Line-buffered file writes for record-level durability.
- `SentinelConfig` — Pydantic-validated configuration: `log_file` (Path),
  `max_queue_size` (>0), `enqueue_timeout` (≥0).
- `@trace(logger=None, *, label=None)` — decorator that records function
  duration and outcome. Works with both sync and async functions. Resolves the
  default logger at call time, not decoration time. When `label` is supplied,
  it is appended to the function name in brackets (`run[checkout]`).
- `TimeBlock(logger, label)` — context manager that records the duration of a
  code block. Captures exception type and message without swallowing.
- `get_logger()` / `set_default_logger()` — process-wide default logger
  helpers, lock-protected via double-checked locking.
- Idempotent `shutdown()` registered with `atexit` for clean drain at
  interpreter exit. `flush(timeout)` for explicit drain.
- Worker self-healing: I/O errors propagate to a top-level handler that marks
  the logger unhealthy and refuses further enqueues. Serialization errors are
  recoverable — one bad record cannot kill the worker.
- `is_healthy()` — public health check.
- PEP 561 `py.typed` marker — downstream `mypy` consumers see Sentinel's
  annotations.

### Tooling

- Strict typing under `mypy --strict`, lint-clean under ruff
  (`E,F,W,B,SIM,UP,N,I,C4,RET,PTH,TCH,ASYNC`).
- 38+ tests covering config validation, logger durability and concurrency,
  tracer sync/async paths, label semantics, TimeBlock, worker self-healing.
- GitHub Actions CI matrix on Python 3.10, 3.11, 3.12 with ruff, mypy,
  bandit, and coverage gating at 90%.

### Known limitations

- No log rotation. Use `logrotate` or pass a date-stamped path.
- No multi-process aggregation. Each process writes its own file.
- Worker self-heal does not auto-restart. Failure is detected, surfaced via
  `is_healthy()`, and further records are refused — restart the process.
- No distributed trace propagation, custom tags, or argument capture in this
  release. See `feature_roadmap.md` for the planned 0.2.0 surface.

[Unreleased]: https://github.com/amadhusudan/sentinel-trace/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/amadhusudan/sentinel-trace/releases/tag/v0.1.0
