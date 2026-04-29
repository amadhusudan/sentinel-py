from __future__ import annotations

import functools
import inspect
import threading
import time
from typing import TYPE_CHECKING, ParamSpec, TypeVar, cast

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


def trace(
    logger: AsyncLogger | None = None,
    *,
    label: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that records function duration and outcome to the given logger.

    Works with both sync and async functions. The default logger is resolved at
    *call* time, so decoration order does not matter.

    ``label`` is an optional human-readable name attached to every record emitted
    by the decorated function. Useful when the function name alone is ambiguous
    (e.g. ``run`` defined in many modules) or when you want to group related
    traces under a domain term ("checkout", "user_signup") regardless of the
    underlying function name.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                active = logger or get_logger()
                start = time.perf_counter()
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
                    active.log(
                        {
                            "function": (f"{func.__name__}[{label}]" if label else func.__name__),
                            "duration_ms": (time.perf_counter() - start) * 1000,
                            "status": status,
                            "error_type": error_type,
                            "error": error_msg,
                        }
                    )

            return cast("Callable[P, R]", async_wrapper)

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            active = logger or get_logger()
            start = time.perf_counter()
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
                active.log(
                    {
                        "function": (f"{func.__name__}[{label}]" if label else func.__name__),
                        "duration_ms": (time.perf_counter() - start) * 1000,
                        "status": status,
                        "error_type": error_type,
                        "error": error_msg,
                    }
                )

        return wrapper

    return decorator


class TimeBlock:
    """Context manager that records the duration of a code block."""

    def __init__(self, logger: AsyncLogger, label: str) -> None:
        self.logger = logger
        self.label = label
        self.start_time: float | None = None

    def __enter__(self) -> TimeBlock:
        self.start_time = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        # start_time is set in __enter__; the with statement guarantees it ran.
        start = cast("float", self.start_time)
        duration_ms = (time.perf_counter() - start) * 1000

        self.logger.log(
            {
                "label": self.label,
                "duration_ms": duration_ms,
                "status": "success" if exc_type is None else "error",
                "error_type": exc_type.__name__ if exc_type else None,
                "error": str(exc_val) if exc_val else None,
            }
        )
