from importlib.metadata import PackageNotFoundError, version

from .config import SentinelConfig
from .logger import AsyncLogger
from .tracer import TimeBlock, get_logger, set_default_logger, trace

try:
    __version__ = version("sentinel-trace")
except PackageNotFoundError:  # not installed (e.g. running from a fresh checkout)
    __version__ = "0.0.0+unknown"

__all__ = [
    "AsyncLogger",
    "SentinelConfig",
    "TimeBlock",
    "__version__",
    "get_logger",
    "set_default_logger",
    "trace",
]
