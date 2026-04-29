from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class SentinelConfig(BaseModel):
    log_file: Path = Field(default=Path("sentinel_logs.jsonl"))
    max_queue_size: int = Field(default=1000, gt=0)
    enqueue_timeout: float = Field(default=0.0, ge=0.0)
