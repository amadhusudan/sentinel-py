from pathlib import Path

import pytest
from pydantic import ValidationError

from sentinel import SentinelConfig


def test_config_defaults_match_documented_values():
    config = SentinelConfig()

    assert config.log_file == Path("sentinel_logs.jsonl")
    assert config.max_queue_size == 1000
    assert config.enqueue_timeout == 0.0


def test_config_accepts_custom_values(tmp_path):
    log_file = tmp_path / "custom.jsonl"

    config = SentinelConfig(log_file=log_file, max_queue_size=50, enqueue_timeout=0.25)

    assert config.log_file == log_file
    assert config.max_queue_size == 50
    assert config.enqueue_timeout == 0.25


def test_config_str_log_file_coerced_to_path(tmp_path):
    config = SentinelConfig(log_file=str(tmp_path / "x.jsonl"))

    assert isinstance(config.log_file, Path)


@pytest.mark.parametrize("bad_size", [0, -1])
def test_config_non_positive_max_queue_size_rejected(bad_size):
    with pytest.raises(ValidationError):
        SentinelConfig(max_queue_size=bad_size)


def test_config_negative_timeout_rejected():
    with pytest.raises(ValidationError):
        SentinelConfig(enqueue_timeout=-0.1)


def test_config_does_not_create_directories_as_side_effect(tmp_path):
    target = tmp_path / "does_not_exist_yet" / "log.jsonl"

    SentinelConfig(log_file=target)

    assert not target.parent.exists()
