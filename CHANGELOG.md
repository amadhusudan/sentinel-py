# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-04-30

Tracing foundations: records form a tree, custom tags scope to a block, slow
calls are flagged, CPU time is captured alongside wall time, sampling drops
noise at the trace root, and a `sentinel tail` CLI pretty-prints JSONL.

### Added

- **Trace + span IDs (B1)** — `contextvars`-backed. Every record from `@trace`
  and `TimeBlock` now carries `trace_id`, `span_id`, and `parent_span_id`.
  Nested calls share `trace_id`; child records link to their parent via
  `parent_span_id`. Records form a tree post-processable with `jq` or pandas.
- **Custom tags (B2)** — `sentinel.tag(**kwargs)` context manager. Tags merge
  into every record emitted within the scope under a `tags` key; absent if no
  tags are active. Nests cleanly — inner tags shadow outer on key collisions.
- **Slow-call threshold (B4)** — `@trace(slow_ms=500)` adds `"slow": true` to
  records whose wall-clock duration exceeds the threshold. Field is absent
  when below threshold or no threshold is configured.
- **CPU vs wall time (B6)** — every record now includes `cpu_time_ms` via
  `time.process_time()`. Reveals I/O-bound vs CPU-bound work at zero
  configuration cost.
- **Sampling (B13)** — `@trace(sample=0.1)` keeps ~10% of root traces.
  Decision is made once at the trace root; nested spans inherit it (parent-
  based sampling), so a kept trace stays kept end-to-end. Sampled-out calls
  still execute the wrapped function and propagate context — they just don't
  emit a record.
- **`sentinel` CLI (B15)** — `sentinel tail <path>` and `python -m sentinel
  tail <path>` pretty-print Sentinel JSONL with color, short trace IDs,
  slow/error highlights, and inline tags. `--follow` for `tail -f` behavior.
  `--tree` renders each trace as a box-drawing tree (buffers by `trace_id`
  and flushes when the root arrives; single-span traces collapse inline;
  orphans flushed flat on EOF). Honors `NO_COLOR`; auto-detects TTY.
- **Public helpers** — `current_trace_id()` and `current_span_id()` for users
  who want to correlate their own logs with Sentinel records.

### Record schema additions

Records emitted by `@trace` and `TimeBlock` now include these fields by default:
- `trace_id` (string, always)
- `span_id` (string, always)
- `parent_span_id` (string or null, always)
- `cpu_time_ms` (number, always)
- `tags` (object, only when tags are in scope)
- `slow` (boolean true, only when `slow_ms` was set and exceeded)

### Tooling

- `[project.scripts]` entry installs a `sentinel` executable on `pip install`.
- 60+ tests passing; coverage maintained above 90%.

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

[Unreleased]: https://github.com/amadhusudan/sentinel-trace/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/amadhusudan/sentinel-trace/releases/tag/v0.2.0
[0.1.0]: https://github.com/amadhusudan/sentinel-trace/releases/tag/v0.1.0
