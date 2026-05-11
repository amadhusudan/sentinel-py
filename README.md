# sentinel-trace

A thread-safe, asynchronous observability toolkit for Python. Drops structured
JSONL logs to disk from a background worker so your hot path stays fast.

## Install

```bash
pip install sentinel-trace
```

## Usage

```python
from sentinel import AsyncLogger, SentinelConfig, TimeBlock, tag, trace

logger = AsyncLogger(SentinelConfig(log_file="app.jsonl"))

@trace(logger)
def fetch_user(user_id: int) -> dict:
    ...

@trace(logger, label="checkout")        # group records under a domain term
@trace(logger, slow_ms=500)             # flag records >500ms as `slow: true`
@trace(logger, sample=0.1)              # keep ~10% of root traces
async def fetch_user_async(user_id: int) -> dict:
    ...

def crunch():
    with TimeBlock(logger, label="data_crunching"):
        ...

# Custom tags attach to every record emitted inside the scope.
with tag(user_id=42, request_id="req-001"):
    fetch_user(42)

logger.flush()      # block until queue drained
logger.shutdown()   # idempotent; also runs at interpreter exit
```

`@trace()` (no args) uses a process-wide default logger that writes to
`sentinel_logs.jsonl` in the working directory.

## Tracing

Every `@trace` and `TimeBlock` call emits a record carrying `trace_id`,
`span_id`, and `parent_span_id`. Nested calls share `trace_id`; child records
link to their parent. Records form a tree post-processable with `jq`, DuckDB,
or pandas.

```json
{"timestamp": "2026-04-30T00:00:00+00:00", "function": "fetch_user", "duration_ms": 12.3, "cpu_time_ms": 0.4, "status": "success", "error_type": null, "error": null, "trace_id": "a1b2c3d4...", "span_id": "e5f6...", "parent_span_id": "9a8b..."}
```

When `@trace` is given a `label`, it's appended to the function name in brackets
(`run[checkout]`). When tags are in scope, records carry a `tags` object. When
`slow_ms` is set and breached, records carry `"slow": true`.

### Sampling

`@trace(sample=0.1)` keeps ~10% of root traces. The decision is made once at
the trace root and inherited by every child span — a kept trace stays kept
end-to-end, so flame charts are never missing nodes. Sampled-out calls still
execute the wrapped function and propagate context; they just don't emit a
record.

## CLI

A `sentinel` executable is installed with the package:

```bash
sentinel tail app.jsonl              # one-shot pretty-print (flat)
sentinel tail app.jsonl --tree       # render each trace as a tree
sentinel tail app.jsonl --follow     # tail -f mode (composes with --tree)
sentinel tail app.jsonl --no-color
python -m sentinel tail app.jsonl    # equivalent module form
```

**Flat mode** (default) prints one line per record in arrival order, colorized
by status. Short trace IDs are shown for grouping; tags render inline.

**Tree mode** (`--tree`) buffers records by `trace_id` and flushes one complete
trace at a time, drawing the span hierarchy with box-drawing characters:

```
trace 6abe7cc3
render_profile 5.24ms success [user_id=42 request_id=req-001]
└─ fetch_user 5.16ms success [user_id=42 request_id=req-001]
   └─ db_query 5.09ms success [user_id=42 request_id=req-001]
[67d772ca] maybe_slow 50.12ms success SLOW
[724f8b5d] cpu_bound 4.00ms success
```

Single-span traces collapse to one line with an inline `[<short_id>]` prefix.
On EOF (or process exit in `--follow` mode), any incomplete traces — those
whose root span never arrived — are flushed flat as orphans so nothing is
lost.

`NO_COLOR` honored; color auto-disabled when stdout is not a TTY.

## When to use this — and when not to

Sentinel is a **thin, single-process, file-backed timing logger**. Pick it when:

- You want microsecond-overhead `@trace`/`TimeBlock` on a service or batch job.
- You're happy to grep / `jq` / load JSONL into DuckDB or pandas after the fact.
- You don't want to operate an OpenTelemetry collector, Datadog Agent, or
  Prometheus exporter for this workload.

**Reach for something else when:**

- You need distributed tracing across services with span propagation —
  use [OpenTelemetry](https://opentelemetry.io).
- You need real-time metrics with PromQL queries — use Prometheus + a metrics
  library.
- You need full-fidelity APM (DB query plans, code-level profiling,
  user-session replay) — that's what Datadog / New Relic / Sentry exist for.

## Known limitations

- **No log rotation.** The file grows unbounded. Use `logrotate` externally or
  pass a date-stamped `log_file` path.
- **No multi-process aggregation.** Each process writes its own file. If
  multiple processes share a `log_file`, writes are not arbitrated — one of
  them will lose lines.
- **Worker self-heal does not auto-restart.** I/O failures are detected and
  surfaced via `logger.is_healthy()`; the worker refuses further records
  rather than silently dropping them. Restart the process to recover.
- **No backpressure by default** (`enqueue_timeout=0.0`). Saturating the queue
  drops records with a warning. Set `enqueue_timeout > 0` if you'd rather
  block producers than drop.
- **No trace ID / span propagation, no automatic argument capture, no
  resource (memory/CPU) metrics yet** — see the roadmap.

## Operational tips

- Call `logger.flush(timeout=...)` before forking or before invoking external
  processes that depend on the log being on disk.
- Catch `is_healthy() == False` in long-running services and alert / restart.
- For high-throughput services, increase `max_queue_size` proportionally to
  your peak per-second log rate × peak worker write latency.

## Development

```bash
pip install -e ".[dev]"
ruff check sentinel tests examples
ruff format --check sentinel tests examples
mypy sentinel
bandit -r sentinel -ll
pytest --cov=sentinel --cov-report=term-missing
```
