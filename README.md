# sentinel-trace

A thread-safe, asynchronous observability toolkit for Python. Drops structured
JSONL logs to disk from a background worker so your hot path stays fast.

## Install

```bash
pip install sentinel-trace
```

## Usage

```python
from sentinel import AsyncLogger, SentinelConfig, TimeBlock, trace

logger = AsyncLogger(SentinelConfig(log_file="app.jsonl"))

@trace(logger)
def fetch_user(user_id: int) -> dict:
    ...

@trace(logger, label="checkout")  # group records under a domain term
def run(order_id: int) -> None:
    ...

@trace(logger)
async def fetch_user_async(user_id: int) -> dict:
    ...

def crunch():
    with TimeBlock(logger, label="data_crunching"):
        ...

logger.flush()      # block until queue drained
logger.shutdown()   # idempotent; also runs at interpreter exit
```

`@trace()` (no args) uses a process-wide default logger that writes to
`sentinel_logs.jsonl` in the working directory.

## Log format

One JSON object per line:

```json
{"timestamp": "2026-04-29T17:00:00+00:00", "function": "fetch_user", "duration_ms": 12.3, "status": "success", "error_type": null}
```

When `@trace` is given a `label`, it's appended to the function name in brackets:

```json
{"timestamp": "2026-04-29T17:00:00+00:00", "function": "run[checkout]", "duration_ms": 12.3, "status": "success", "error_type": null}
```

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
