"""Validated monitoring-only configuration; no credentials or commands."""
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class BackupRule(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=500)
    pattern: str = Field(default='*.bak', min_length=1, max_length=200)
    schedule: Literal['daily', 'monthly'] = 'daily'
    recursive: bool = False
    date_from_filename: bool = True
    max_age_hours: float = Field(default=30, ge=1, le=8760, allow_inf_nan=False)
    grace_hours: float = Field(default=36, ge=0, le=672, allow_inf_nan=False)
    min_size_bytes: int = Field(default=1024**3, ge=0, le=1024**5)


class MonitoringSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    backups: list[BackupRule] = Field(default_factory=list, max_length=20)
    services: list[str] = Field(default_factory=list, max_length=100)
