"""Contextvars-backed trace context: trace IDs, span IDs, tags, sampling.

This module is the foundation for v0.2.0 tracing features. The public API
surface is intentionally small — most users only need `tag()`,
`current_trace_id()`, and `current_span_id()`. Span lifecycle is managed
internally by `@trace` and `TimeBlock`.

Design notes:
- Span tree is parent-based: the first call without an active trace creates a
  new trace; nested calls inherit the trace_id and link to their parent.
- Sampling is parent-based too: the decision is made at the trace root and
  inherited by every child span. This guarantees a kept trace stays kept
  end-to-end (no orphan child spans missing a parent).
- contextvars propagate across threads and async tasks via copy_context, so
  this works correctly under threading, asyncio, and trio.
"""

from __future__ import annotations

import contextlib
import contextvars
import random
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator


_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sentinel_trace_id", default=None
)
_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sentinel_span_id", default=None
)
_sampled: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "sentinel_sampled", default=None
)
_tags: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "sentinel_tags", default=None
)

# Sampling uses a non-crypto PRNG by design — sampling decisions don't need
# crypto-strong randomness, and random.SystemRandom is ~100× slower per call,
# which matters on the hot path. nosec annotation tells bandit this is intentional.
_RNG = random.Random()  # nosec B311


def _new_id() -> str:
    """Return a 16-hex-char identifier (64 random bits). Enough for single-process tracing."""
    return uuid.uuid4().hex[:16]


def current_trace_id() -> str | None:
    """Return the trace ID of the currently active span, or None if no trace is active."""
    return _trace_id.get()


def current_span_id() -> str | None:
    """Return the span ID of the currently active span, or None if no span is active."""
    return _span_id.get()


def current_tags() -> dict[str, Any]:
    """Return a shallow copy of the tags currently in scope (empty dict if none)."""
    current = _tags.get()
    return dict(current) if current else {}


class Span:
    """Internal: tracks the contextvar tokens for an active span lifetime.

    Callers (the `@trace` decorator and `TimeBlock`) must invoke `close()` in
    a finally block to pop the contextvar values they pushed.
    """

    __slots__ = ("_tokens", "parent_span_id", "sampled", "span_id", "trace_id")

    def __init__(
        self,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None,
        sampled: bool,
        tokens: list[tuple[contextvars.ContextVar[Any], contextvars.Token[Any]]],
    ) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.sampled = sampled
        self._tokens = tokens

    def close(self) -> None:
        # Reset in reverse to mirror the push order — defensive, not strictly required.
        for var, tok in reversed(self._tokens):
            var.reset(tok)


def start_span(sample: float = 1.0) -> Span:
    """Begin a new span. Caller MUST invoke `.close()` in a finally block.

    `sample` is the per-call sampling probability for the *trace root*. Nested
    spans inherit the root's keep/drop decision regardless of their own
    `sample` argument — see module docstring.
    """
    parent_span_id = _span_id.get()
    parent_trace_id = _trace_id.get()
    parent_sampled = _sampled.get()

    if parent_trace_id is None:
        trace_id = _new_id()
        sampled = _RNG.random() < sample
    else:
        trace_id = parent_trace_id
        # Parent decided; child inherits. The `is not None` check is defensive —
        # in practice, _sampled is always set whenever _trace_id is set.
        sampled = parent_sampled if parent_sampled is not None else True

    span_id = _new_id()

    tokens: list[tuple[contextvars.ContextVar[Any], contextvars.Token[Any]]] = [
        (_trace_id, _trace_id.set(trace_id)),
        (_span_id, _span_id.set(span_id)),
        (_sampled, _sampled.set(sampled)),
    ]

    return Span(trace_id, span_id, parent_span_id, sampled, tokens)


@contextlib.contextmanager
def tag(**kwargs: Any) -> Iterator[None]:
    """Attach kwargs to every Sentinel record emitted within this scope.

    Nests cleanly — inner tags shadow outer tags on key collisions:

        with tag(env="prod", user_id=1):
            with tag(user_id=2):  # overrides outer user_id
                do_work()         # records carry tags={"env": "prod", "user_id": 2}

    Tags are merged into the record under the `tags` key. If no tags are
    active, the `tags` key is omitted entirely.
    """
    parent = _tags.get() or {}
    merged = {**parent, **kwargs}
    tok = _tags.set(merged)
    try:
        yield
    finally:
        _tags.reset(tok)
