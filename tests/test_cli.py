from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sentinel import cli

if TYPE_CHECKING:
    from pathlib import Path


def _write_records(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_tail_prints_function_records(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    _write_records(
        p,
        [
            {
                "timestamp": "2026-04-30T00:00:00Z",
                "function": "fetch",
                "duration_ms": 5.5,
                "status": "success",
                "trace_id": "abc123def456ghi7",
            },
        ],
    )

    exit_code = cli.main(["tail", "--no-color", str(p)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "fetch" in out
    assert "5.50ms" in out
    assert "success" in out
    assert "abc123de" in out  # short trace id


def test_tail_prints_timeblock_label_records(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    _write_records(
        p,
        [
            {
                "timestamp": "ts",
                "label": "ingest_block",
                "duration_ms": 1.0,
                "status": "success",
                "trace_id": "x" * 16,
            },
        ],
    )

    cli.main(["tail", "--no-color", str(p)])
    out = capsys.readouterr().out
    assert "ingest_block" in out


def test_tail_shows_error_and_message(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    _write_records(
        p,
        [
            {
                "timestamp": "ts",
                "function": "boom",
                "duration_ms": 1.0,
                "status": "error",
                "error": "kaboom!",
                "trace_id": "t",
            },
        ],
    )

    cli.main(["tail", "--no-color", str(p)])
    out = capsys.readouterr().out
    assert "boom" in out
    assert "error" in out
    assert "kaboom!" in out


def test_tail_marks_slow_records(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    _write_records(
        p,
        [
            {
                "timestamp": "ts",
                "function": "lag",
                "duration_ms": 500.0,
                "status": "success",
                "slow": True,
                "trace_id": "t",
            },
        ],
    )

    cli.main(["tail", "--no-color", str(p)])
    out = capsys.readouterr().out
    assert "SLOW" in out


def test_tail_renders_tags(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    _write_records(
        p,
        [
            {
                "timestamp": "ts",
                "function": "f",
                "duration_ms": 1.0,
                "status": "success",
                "trace_id": "t",
                "tags": {"user_id": 42, "env": "prod"},
            },
        ],
    )

    cli.main(["tail", "--no-color", str(p)])
    out = capsys.readouterr().out
    assert "user_id=42" in out
    assert "env=prod" in out


def test_tail_missing_file_returns_exit_1(tmp_path, capsys):
    exit_code = cli.main(["tail", "--no-color", str(tmp_path / "nope.jsonl")])
    err = capsys.readouterr().err

    assert exit_code == 1
    assert "nope.jsonl" in err
    assert "no such file" in err


def test_tail_skips_malformed_lines_silently(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    p.write_text(
        "not json at all\n"
        '{"function": "ok", "duration_ms": 1, "status": "success", "trace_id": "t"}\n'
    )

    exit_code = cli.main(["tail", "--no-color", str(p)])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "ok" in out  # valid line still emitted


def test_tail_skips_non_dict_json_lines(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    # JSON valid but not a record — array, scalar, etc.
    p.write_text(
        "[1, 2, 3]\n"
        '"a string"\n'
        '{"function": "real", "duration_ms": 1, "status": "success", "trace_id": "t"}\n'
    )

    cli.main(["tail", "--no-color", str(p)])
    out = capsys.readouterr().out
    assert "real" in out
    assert "[1, 2, 3]" not in out


def test_cli_requires_subcommand(capsys):
    with pytest.raises(SystemExit):
        cli.main([])


# ---------------------------------------------------------------------------
# --tree rendering
# ---------------------------------------------------------------------------


def _three_span_trace() -> list[dict]:
    """Post-order completion of: root → mid → leaf."""
    return [
        {
            "timestamp": "2026-04-30T00:00:00.001Z",
            "function": "leaf",
            "duration_ms": 1.0,
            "status": "success",
            "trace_id": "t1",
            "span_id": "s_leaf",
            "parent_span_id": "s_mid",
        },
        {
            "timestamp": "2026-04-30T00:00:00.002Z",
            "function": "mid",
            "duration_ms": 2.0,
            "status": "success",
            "trace_id": "t1",
            "span_id": "s_mid",
            "parent_span_id": "s_root",
        },
        {
            "timestamp": "2026-04-30T00:00:00.003Z",
            "function": "root",
            "duration_ms": 3.0,
            "status": "success",
            "trace_id": "t1",
            "span_id": "s_root",
            "parent_span_id": None,
        },
    ]


def test_tree_renders_root_and_children_with_box_chars(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    _write_records(p, _three_span_trace())

    cli.main(["tail", "--no-color", "--tree", str(p)])
    out = capsys.readouterr().out

    # Header line names the trace
    assert "trace t1" in out
    # Root prints with no connector
    assert "root" in out
    # Box-drawing chars for descendants
    assert "└─ mid" in out or "├─ mid" in out
    assert "└─ leaf" in out or "├─ leaf" in out
    # Pre-order: root before mid before leaf
    root_idx = out.index("root")
    mid_idx = out.index("mid")
    leaf_idx = out.index("leaf")
    assert root_idx < mid_idx < leaf_idx


def test_tree_separates_independent_traces(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    _write_records(
        p,
        [
            # Trace A
            {
                "timestamp": "t1",
                "function": "a_root",
                "duration_ms": 1.0,
                "status": "success",
                "trace_id": "A",
                "span_id": "sa",
                "parent_span_id": None,
            },
            # Trace B
            {
                "timestamp": "t2",
                "function": "b_root",
                "duration_ms": 1.0,
                "status": "success",
                "trace_id": "B",
                "span_id": "sb",
                "parent_span_id": None,
            },
        ],
    )

    cli.main(["tail", "--no-color", "--tree", str(p)])
    out = capsys.readouterr().out

    # Single-span traces render inline with [<short_id>] prefix, not a separate header.
    assert "[A]" in out
    assert "[B]" in out
    assert "a_root" in out
    assert "b_root" in out


def test_tree_renders_two_siblings_under_root(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    _write_records(
        p,
        [
            # sibling 1 finishes first
            {
                "timestamp": "2026-04-30T00:00:00.001Z",
                "function": "child_a",
                "duration_ms": 1.0,
                "status": "success",
                "trace_id": "t",
                "span_id": "c1",
                "parent_span_id": "r",
            },
            # sibling 2 finishes second
            {
                "timestamp": "2026-04-30T00:00:00.002Z",
                "function": "child_b",
                "duration_ms": 1.0,
                "status": "success",
                "trace_id": "t",
                "span_id": "c2",
                "parent_span_id": "r",
            },
            # root
            {
                "timestamp": "2026-04-30T00:00:00.003Z",
                "function": "root",
                "duration_ms": 1.0,
                "status": "success",
                "trace_id": "t",
                "span_id": "r",
                "parent_span_id": None,
            },
        ],
    )

    cli.main(["tail", "--no-color", "--tree", str(p)])
    out = capsys.readouterr().out

    # First sibling uses ├─ (not last), second uses └─ (last).
    assert "├─ child_a" in out
    assert "└─ child_b" in out


def test_tree_orphan_records_emitted_on_eof_when_root_missing(tmp_path, capsys):
    """A trace whose root never arrives (process killed mid-call) is still surfaced."""
    p = tmp_path / "log.jsonl"
    _write_records(
        p,
        [
            {
                "timestamp": "ts",
                "function": "orphan_child",
                "duration_ms": 1.0,
                "status": "success",
                "trace_id": "orphan",
                "span_id": "c",
                "parent_span_id": "missing_root",
            },
        ],
    )

    cli.main(["tail", "--no-color", "--tree", str(p)])
    out = capsys.readouterr().out
    # Falls back to flat formatting since the tree has no root.
    assert "orphan_child" in out


def test_tree_records_without_trace_id_emit_flat(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    # A legacy record without trace_id (e.g. from v0.1.0 output) should still print.
    _write_records(
        p,
        [
            {
                "timestamp": "ts",
                "function": "legacy",
                "duration_ms": 1.0,
                "status": "success",
            },
        ],
    )

    cli.main(["tail", "--no-color", "--tree", str(p)])
    out = capsys.readouterr().out
    assert "legacy" in out


def test_tree_single_span_uses_inline_prefix_not_header(tmp_path, capsys):
    """A trace with only one span renders as a single line with [<short_id>] prefix,
    not the multi-line 'trace <id>' + body form used for multi-span traces."""
    p = tmp_path / "log.jsonl"
    _write_records(
        p,
        [
            {
                "timestamp": "ts",
                "function": "solo",
                "duration_ms": 1.0,
                "status": "success",
                "trace_id": "abcdef0123456789",
                "span_id": "s",
                "parent_span_id": None,
            },
        ],
    )

    cli.main(["tail", "--no-color", "--tree", str(p)])
    out = capsys.readouterr().out

    assert "[abcdef01]" in out
    assert "solo" in out
    # No verbose "trace ..." header for single-span traces.
    assert "trace abcdef01" not in out
    # Single line of output.
    assert out.count("\n") == 1


def test_tree_renders_errored_span_with_message(tmp_path, capsys):
    """Cover the tree-mode error branch in _format_node_compact."""
    p = tmp_path / "log.jsonl"
    _write_records(
        p,
        [
            {
                "timestamp": "ts",
                "function": "fail",
                "duration_ms": 1.0,
                "status": "error",
                "error": "kaboom!",
                "error_type": "ValueError",
                "trace_id": "t",
                "span_id": "s",
                "parent_span_id": None,
            },
        ],
    )

    cli.main(["tail", "--no-color", "--tree", str(p)])
    out = capsys.readouterr().out
    assert "fail" in out
    assert "kaboom!" in out


def test_tree_renders_tags_on_nodes(tmp_path, capsys):
    """Cover the tree-mode tag-rendering branch in _format_node_compact."""
    p = tmp_path / "log.jsonl"
    _write_records(
        p,
        [
            {
                "timestamp": "ts",
                "function": "f",
                "duration_ms": 1.0,
                "status": "success",
                "trace_id": "t",
                "span_id": "s",
                "parent_span_id": None,
                "tags": {"k": "v"},
            },
        ],
    )

    cli.main(["tail", "--no-color", "--tree", str(p)])
    out = capsys.readouterr().out
    assert "k=v" in out


def test_flat_skips_blank_lines(tmp_path, capsys):
    """Cover the empty-line early-return in _parse_line."""
    p = tmp_path / "log.jsonl"
    p.write_text(
        "\n"
        "  \n"
        '{"function": "after_blanks", "duration_ms": 1, "status": "success", "trace_id": "t"}\n'
    )

    cli.main(["tail", "--no-color", str(p)])
    out = capsys.readouterr().out
    assert "after_blanks" in out


def test_tree_skips_blank_lines(tmp_path, capsys):
    """Cover _ingest_tree's `record is None` early-return path."""
    p = tmp_path / "log.jsonl"
    p.write_text(
        "\n"
        "   \n"
        '{"function": "after_blanks", "duration_ms": 1, "status": "success", '
        '"trace_id": "t", "span_id": "s", "parent_span_id": null}\n'
    )

    cli.main(["tail", "--no-color", "--tree", str(p)])
    out = capsys.readouterr().out
    assert "after_blanks" in out


class _FakeStream:
    """Minimal TextIO stand-in for _resolve_color tests."""

    def __init__(self, *, isatty: bool) -> None:
        self._isatty = isatty

    def isatty(self) -> bool:
        return self._isatty


def test_resolve_color_disabled_when_no_color_flag(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert cli._resolve_color(no_color=True, out=_FakeStream(isatty=True)) is False


def test_resolve_color_disabled_when_env_var_set(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert cli._resolve_color(no_color=False, out=_FakeStream(isatty=True)) is False


def test_resolve_color_enabled_when_tty_and_no_env(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert cli._resolve_color(no_color=False, out=_FakeStream(isatty=True)) is True


def test_resolve_color_disabled_when_not_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert cli._resolve_color(no_color=False, out=_FakeStream(isatty=False)) is False


def test_help_lists_all_subcommand_options(capsys):
    """`sentinel --help` must surface every subcommand's flags."""
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    # Subcommand presence
    assert "tail" in out
    # Each tail flag should appear in the top-level help (via the epilog).
    assert "--follow" in out
    assert "--tree" in out
    assert "--no-color" in out
    assert "path" in out


def test_tree_drops_timestamp_in_node_lines(tmp_path, capsys):
    p = tmp_path / "log.jsonl"
    _write_records(p, _three_span_trace())

    cli.main(["tail", "--no-color", "--tree", str(p)])
    out = capsys.readouterr().out

    # Tree-mode node formatter omits the per-record ISO timestamp.
    assert "2026-04-30T00:00:00.001Z" not in out
    assert "2026-04-30T00:00:00.002Z" not in out
    assert "2026-04-30T00:00:00.003Z" not in out
