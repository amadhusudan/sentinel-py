import functools
import time
from typing import Callable, Any, TypeVar, ParamSpec
from sentinel.logger import AsyncLogger

_default_logger = None


def get_logger():
    global _default_logger
    if _default_logger is None:
        _default_logger = AsyncLogger()
    return _default_logger


P = ParamSpec("P")
R = TypeVar("R")


def trace(logger: AsyncLogger = None):
    _logger = logger or get_logger()
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start_time = time.perf_counter()
            status = "success"
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                status = f"error: {type(e).__name__}"
                raise
            finally:
                end_time = time.perf_counter()
                _logger.log({
                    "function": func.__name__,
                    "duration_ms": (end_time - start_time) * 1000,
                    "status": status
                })
        return wrapper
    return decorator


class TimeBlock:
    def __init__(self, logger, label: str):
        self.logger = logger
        self.label = label
        self.start_time: Optional[float] = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        end_time = time.perf_counter()
        duration_ms = (end_time - self.start_time) * 1000
        
        status = "success" if exc_type is None else "error"
        
        self.logger.log({
            "block_label": self.label,
            "duration_ms": duration_ms,
            "status": status,
            "error": str(exc_val) if exc_val else "n/a"
        })

        return False
