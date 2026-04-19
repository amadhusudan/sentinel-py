import functools
import time
from typing import Callable, Any, TypeVar, ParamSpec
from src.async_logger import AsyncLogger

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
                # Send the data to our background worker
                print ("logging for func", func.__name__)
                _logger.log({
                    "function": func.__name__,
                    "duration_ms": (end_time - start_time) * 1000,
                    "status": status
                })
        return wrapper
    return decorator


