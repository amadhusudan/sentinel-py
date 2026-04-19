from pydantic import BaseModel, Field, field_validator
from typing import Optional
import os

class SentinelConfig(BaseModel):
    log_file: str = Field(default="sentinel_logs.jsonl", min_length=1)
    max_queue_size: int = Field(default=1000, gt=0)
    
    @field_validator("log_file")
    @classmethod
    def check_directory(cls, v: str) -> str:
        directory = os.path.dirname(v)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        return v
