"""`sentinel` CLI — pretty-print live tail for Sentinel JSONL output.

Usage:
    sentinel tail /path/to/log.jsonl              # flat live tail
    sentinel tail /path/to/log.jsonl --follow     # tail -f mode
    sentinel tail /path/to/log.jsonl --tree       # render trace tree
    sentinel tail /path/to/log.jsonl --no-color

Tree mode buffers records by `trace_id` and flushes one complete trace at a
time, when the root span (`parent_span_id == null`) arrives. Records arrive
in post-order (children before parents), so this buffering is required to
reconstruct the tree. On EOF (non-follow) or process exit, any buffered
records belonging to incomplete traces are flushed flat as orphans.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, TextIO

_RESET = "\033[0m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_GRAY = "\033[90m"
_BOLD = "\033[1m"


def _color(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}{_RESET}" if enabled else text


def _status_str(record: dict[str, Any], use_color: bool) -> str:
    status = str(record.get("status", ""))
    slow = bool(record.get("slow", False))
    if status == "error":
        return _color(status, _RED, use_color)
    if slow:
        return _color(f"{status} SLOW", _YELLOW, use_color)
    return _color(status, _GREEN, use_color)


def _format_record(record: dict[str, Any], use_color: bool) -> str:
    """Flat-mode formatter: timestamp + short trace ID + name + duration + status + tags."""
    ts = str(record.get("timestamp", ""))
    name = str(record.get("function") or record.get("label") or "?")
    duration = float(record.get("duration_ms", 0.0))
    trace_id = str(record.get("trace_id", ""))
    trace_short = trace_id[:8] if trace_id else ""

    parts: list[str] = []
    if ts:
        parts.append(_color(ts, _GRAY, use_color))
    if trace_short:
        parts.append(_color(f"[{trace_short}]", _GRAY, use_color))
    parts.append(_color(name, _BOLD, use_color))
    parts.append(f"{duration:.2f}ms")
    parts.append(_status_str(record, use_color))

    err = record.get("error")
    if err:
        parts.append(_color(f"({err})", _RED, use_color))

    tags = record.get("tags")
    if isinstance(tags, dict) and tags:
        tag_str = " ".join(f"{k}={v}" for k, v in tags.items())
        parts.append(_color(f"[{tag_str}]", _GRAY, use_color))

    return " ".join(parts)


def _format_node_compact(record: dict[str, Any], use_color: bool) -> str:
    """Tree-mode node formatter: drops timestamp + trace-ID (shown once per trace)."""
    name = str(record.get("function") or record.get("label") or "?")
    duration = float(record.get("duration_ms", 0.0))

    parts: list[str] = [
        _color(name, _BOLD, use_color),
        f"{duration:.2f}ms",
        _status_str(record, use_color),
    ]

    err = record.get("error")
    if err:
        parts.append(_color(f"({err})", _RED, use_color))

    tags = record.get("tags")
    if isinstance(tags, dict) and tags:
        tag_str = " ".join(f"{k}={v}" for k, v in tags.items())
        parts.append(_color(f"[{tag_str}]", _GRAY, use_color))

    return " ".join(parts)


def _print_tree(records: list[dict[str, Any]], use_color: bool, out: TextIO) -> None:
    """Render one complete trace as a box-drawing tree, pre-order DFS.

    `records` is a list of records all sharing the same `trace_id`. Exactly
    one is expected to have `parent_span_id == None` (the root). Children are
    ordered by `timestamp` (start-time order ≈ ascending across short spans).
    """
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    for r in records:
        by_parent.setdefault(r.get("parent_span_id"), []).append(r)
    for children in by_parent.values():
        children.sort(key=lambda r: str(r.get("timestamp", "")))

    roots = by_parent.get(None, [])
    if not roots:
        # No identifiable root — emit flat so the user still sees the data.
        for r in records:
            print(_format_record(r, use_color), file=out)
        return

    trace_id = str(roots[0].get("trace_id", ""))
    trace_short = trace_id[:8] if trace_id else ""

    # Single-span trace: render inline with the trace ID prefix to avoid a
    # redundant "trace <id>" header on its own line. Saves 1 line per orphan.
    if len(records) == 1 and trace_short:
        prefix = _color(f"[{trace_short}]", _GRAY, use_color)
        print(f"{prefix} {_format_node_compact(roots[0], use_color)}", file=out)
        return

    # _ingest_tree guarantees trace_id is a non-empty string before bucketing,
    # so trace_short here is always non-empty — no guard needed.
    print(_color(f"trace {trace_short}", _GRAY, use_color), file=out)

    def walk(node: dict[str, Any], prefix: str, is_last: bool, is_root: bool) -> None:
        if is_root:
            line = _format_node_compact(node, use_color)
            child_prefix = ""
        else:
            connector = "└─ " if is_last else "├─ "
            line = prefix + connector + _format_node_compact(node, use_color)
            child_prefix = prefix + ("   " if is_last else "│  ")
        print(line, file=out)

        children = by_parent.get(str(node.get("span_id", "")), [])
        for i, child in enumerate(children):
            walk(child, child_prefix, i == len(children) - 1, is_root=False)

    for i, root in enumerate(roots):
        walk(root, "", i == len(roots) - 1, is_root=True)


def _parse_line(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    return record


def _emit_flat(line: str, use_color: bool, out: TextIO) -> None:
    record = _parse_line(line)
    if record is None:
        return
    print(_format_record(record, use_color), file=out)


def _ingest_tree(
    line: str,
    buffers: dict[str, list[dict[str, Any]]],
    use_color: bool,
    out: TextIO,
) -> None:
    record = _parse_line(line)
    if record is None:
        return

    trace_id = record.get("trace_id")
    if not isinstance(trace_id, str) or not trace_id:
        # No trace context — emit flat so we don't lose the record.
        print(_format_record(record, use_color), file=out)
        return

    buffers.setdefault(trace_id, []).append(record)

    # Root span just arrived → trace is complete, flush its buffer.
    if record.get("parent_span_id") is None:
        _print_tree(buffers.pop(trace_id), use_color, out)
        out.flush()


def _flush_orphans(
    buffers: dict[str, list[dict[str, Any]]],
    use_color: bool,
    out: TextIO,
) -> None:
    """Emit any traces whose root never arrived (incomplete or interrupted)."""
    for records in buffers.values():
        # Best-effort: render what we have; _print_tree falls back to flat
        # if no root is present.
        _print_tree(records, use_color, out)


def _tail(
    path: Path,
    *,
    follow: bool,
    tree: bool,
    use_color: bool,
    out: TextIO,
) -> None:
    buffers: dict[str, list[dict[str, Any]]] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if tree:
                _ingest_tree(line, buffers, use_color, out)
            else:
                _emit_flat(line, use_color, out)

        if not follow:
            if tree:
                _flush_orphans(buffers, use_color, out)
            return

        # tail -f loop. 100ms poll is fine for an interactive tool.
        # Excluded from coverage: testing this requires a concurrent writer
        # thread AND a way to interrupt the worker — both produce flaky tests
        # without commensurate safety. The loop body is small and read-only.
        try:  # pragma: no cover
            while True:
                line = fh.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                if tree:
                    _ingest_tree(line, buffers, use_color, out)
                else:
                    _emit_flat(line, use_color, out)
                    out.flush()
        finally:  # pragma: no cover
            if tree:
                _flush_orphans(buffers, use_color, out)


def _resolve_color(no_color: bool, out: TextIO) -> bool:
    if no_color:
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    isatty = getattr(out, "isatty", None)
    return bool(isatty()) if callable(isatty) else False


def _format_subparser_options(subparser: argparse.ArgumentParser, cmd: str) -> str:
    """Render a subparser's options as an indented block for the top-level help epilog.

    Iterating `_actions` is the documented introspection path for argparse; the
    leading underscore is a Python-stdlib quirk, not an internal-API marker.
    """
    lines = [f"options for `sentinel {cmd}`:"]
    for action in subparser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        spec = ", ".join(action.option_strings) if action.option_strings else action.dest
        help_text = action.help or ""
        lines.append(f"  {spec:<20} {help_text}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sentinel",
        description="Sentinel — utilities for inspecting JSONL trace logs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    tail_parser = subparsers.add_parser("tail", help="Pretty-print a Sentinel JSONL file.")
    tail_parser.add_argument("path", help="Path to the JSONL log file.")
    tail_parser.add_argument(
        "-f",
        "--follow",
        action="store_true",
        help="Follow the file as it grows (like tail -f).",
    )
    tail_parser.add_argument(
        "--tree",
        action="store_true",
        help="Render each trace as a tree (buffers per trace_id until root arrives).",
    )
    tail_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color codes (also disabled when stdout is not a TTY).",
    )

    # Surface every subcommand's flags in `sentinel --help` so users don't have
    # to drill into `sentinel <cmd> --help` to discover them.
    parser.epilog = "\n\n".join(
        _format_subparser_options(subp, cmd) for cmd, subp in subparsers.choices.items()
    )

    args = parser.parse_args(argv)

    if args.command == "tail":
        path = Path(args.path)
        if not path.exists():
            print(f"sentinel: {path}: no such file", file=sys.stderr)
            return 1

        use_color = _resolve_color(args.no_color, sys.stdout)
        try:
            _tail(
                path,
                follow=args.follow,
                tree=args.tree,
                use_color=use_color,
                out=sys.stdout,
            )
        except KeyboardInterrupt:  # pragma: no cover  -- needs OS signal injection
            return 130
        return 0

    return 1  # pragma: no cover  -- argparse rejects unknown commands before we get here
