from __future__ import annotations

import functools
import inspect
import threading
import time
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, cast

from sentinel.context import Span, current_tags, start_span
from sentinel.logger import AsyncLogger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from types import TracebackType

P = ParamSpec("P")
R = TypeVar("R")

_default_logger: AsyncLogger | None = None
_default_lock = threading.Lock()


def get_logger() -> AsyncLogger:
    """Return the process-wide default logger, creating it on first use."""
    global _default_logger
    if _default_logger is None:
        with _default_lock:
            if _default_logger is None:
                _default_logger = AsyncLogger()
    return _default_logger


def set_default_logger(logger: AsyncLogger | None) -> None:
    """Override (or clear) the process-wide default logger. Primarily for tests."""
    global _default_logger
    with _default_lock:
        _default_logger = logger


def _build_trace_record(
    *,
    function: str,
    label: str | None,
    duration_ms: float,
    cpu_time_ms: float,
    status: str,
    error_type: str | None,
    error_msg: str | None,
    span: Span,
    slow_ms: float | None,
) -> dict[str, Any]:
    name = f"{function}[{label}]" if label else function
    record: dict[str, Any] = {
        "function": name,
        "duration_ms": duration_ms,
        "cpu_time_ms": cpu_time_ms,
        "status": status,
        "error_type": error_type,
        "error": error_msg,
        "trace_id": span.trace_id,
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
    }
    tags = current_tags()
    if tags:
        record["tags"] = tags
    # `slow` is only present when (a) a threshold was configured AND (b) it was breached.
    # Absence means "not slow" — keeps the schema lean.
    if slow_ms is not None and duration_ms > slow_ms:
        record["slow"] = True
    return record


def trace(
    logger: AsyncLogger | None = None,
    *,
    label: str | None = None,
    slow_ms: float | None = None,
    sample: float = 1.0,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that records function duration and outcome to the given logger.

    Works with both sync and async functions. The default logger is resolved at
    *call* time, so decoration order does not matter.

    Arguments:
        logger: explicit logger; if None, uses the process-wide default.
        label: optional human-readable name appended in brackets to the function
            name (e.g. ``run[checkout]``). Useful when the function name alone
            is ambiguous or you want to group records under a domain term.
        slow_ms: if set, records that exceed this wall-clock duration get
            ``slow: true`` added to the emitted record. Absence of the field
            means the call was below threshold (or no threshold was configured).
        sample: per-trace sampling probability in [0.0, 1.0]. Decision is made
            at the trace *root* (the outermost ``@trace``/``TimeBlock``); nested
            spans inherit it. Sampled-out calls still execute the wrapped
            function and propagate the context — they just don't emit a record.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                active = logger or get_logger()
                span = start_span(sample)
                start = time.perf_counter()
                cpu_start = time.process_time()
                status = "success"
                error_type: str | None = None
                error_msg: str | None = None
                try:
                    return await cast("Callable[P, Awaitable[R]]", func)(*args, **kwargs)
                except Exception as exc:
                    status = "error"
                    error_type = type(exc).__name__
                    error_msg = str(exc)
                    raise
                finally:
                    duration_ms = (time.perf_counter() - start) * 1000
                    cpu_time_ms = (time.process_time() - cpu_start) * 1000
                    if span.sampled:
                        active.log(
                            _build_trace_record(
                                function=func.__name__,
                                label=label,
                                duration_ms=duration_ms,
                                cpu_time_ms=cpu_time_ms,
                                status=status,
                                error_type=error_type,
                                error_msg=error_msg,
                                span=span,
                                slow_ms=slow_ms,
                            )
                        )
                    span.close()

            return cast("Callable[P, R]", async_wrapper)

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            active = logger or get_logger()
            span = start_span(sample)
            start = time.perf_counter()
            cpu_start = time.process_time()
            status = "success"
            error_type: str | None = None
            error_msg: str | None = None
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                status = "error"
                error_type = type(exc).__name__
                error_msg = str(exc)
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                cpu_time_ms = (time.process_time() - cpu_start) * 1000
                if span.sampled:
                    active.log(
                        _build_trace_record(
                            function=func.__name__,
                            label=label,
                            duration_ms=duration_ms,
                            cpu_time_ms=cpu_time_ms,
                            status=status,
                            error_type=error_type,
                            error_msg=error_msg,
                            span=span,
                            slow_ms=slow_ms,
                        )
                    )
                span.close()

        return wrapper

    return decorator


class TimeBlock:
    """Context manager that records the duration of a code block.

    Participates in the trace tree: when entered inside an active ``@trace``,
    it inherits the parent's trace ID and links via ``parent_span_id``.
    Standalone use starts a fresh trace.
    """

    def __init__(self, logger: AsyncLogger, label: str, *, sample: float = 1.0) -> None:
        self.logger = logger
        self.label = label
        self.sample = sample
        self._start_time: float | None = None
        self._cpu_start: float | None = None
        self._span: Span | None = None

    def __enter__(self) -> TimeBlock:
        self._span = start_span(self.sample)
        self._start_time = time.perf_counter()
        self._cpu_start = time.process_time()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        # __enter__ set these; the with-statement guarantees it ran.
        start = cast("float", self._start_time)
        cpu_start = cast("float", self._cpu_start)
        span = cast("Span", self._span)

        duration_ms = (time.perf_counter() - start) * 1000
        cpu_time_ms = (time.process_time() - cpu_start) * 1000

        if span.sampled:
            record: dict[str, Any] = {
                "label": self.label,
                "duration_ms": duration_ms,
                "cpu_time_ms": cpu_time_ms,
                "status": "success" if exc_type is None else "error",
                "error_type": exc_type.__name__ if exc_type else None,
                "error": str(exc_val) if exc_val else None,
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
            }
            tags = current_tags()
            if tags:
                record["tags"] = tags
            self.logger.log(record)
        span.close()
