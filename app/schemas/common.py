"""Shared API shapes: pagination (errors use the envelope in main.py)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PagedQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
