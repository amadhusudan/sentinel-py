from importlib.metadata import PackageNotFoundError, version

from .config import SentinelConfig
from .context import current_span_id, current_trace_id, tag
from .logger import AsyncLogger
from .tracer import TimeBlock, get_logger, set_default_logger, trace

try:
    __version__ = version("sentinel-trace")
except PackageNotFoundError:  # pragma: no cover  -- only fires from an uninstalled checkout
    __version__ = "0.0.0+unknown"

__all__ = [
    "AsyncLogger",
    "SentinelConfig",
    "TimeBlock",
    "__version__",
    "current_span_id",
    "current_trace_id",
    "get_logger",
    "set_default_logger",
    "tag",
    "trace",
]
