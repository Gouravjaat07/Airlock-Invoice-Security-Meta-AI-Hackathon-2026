"""Fact, provenance, and producer records.

Every extracted value keeps its source artifact, producing adapter,
taint class, and validation status. Validation status is field-level;
there is no global `verified=true` flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import FieldStatus
from app.domain.taint import TaintClass


@dataclass(frozen=True)
class Source:
    artifact_id: str
    artifact_kind: str
    page: int | None = None
    region: str | None = None
    timecode: str | None = None

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "artifact_kind": self.artifact_kind,
            "page": self.page,
            "region": self.region,
            "timecode": self.timecode,
        }

    @staticmethod
    def from_dict(data: dict) -> "Source":
        return Source(
            artifact_id=str(data.get("artifact_id", "")),
            artifact_kind=str(data.get("artifact_kind", "")),
            page=data.get("page"),
            region=data.get("region"),
            timecode=data.get("timecode"),
        )


@dataclass(frozen=True)
class Producer:
    adapter: str
    adapter_version: str
    model_id: str | None = None
    prompt_version: str | None = None
    extracted_at: str | None = None
    request_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "extracted_at": self.extracted_at,
            "request_id": self.request_id,
        }

    @staticmethod
    def from_dict(data: dict) -> "Producer":
        return Producer(
            adapter=str(data.get("adapter", "")),
            adapter_version=str(data.get("adapter_version", "")),
            model_id=data.get("model_id"),
            prompt_version=data.get("prompt_version"),
            extracted_at=data.get("extracted_at"),
            request_id=data.get("request_id"),
        )


@dataclass
class Fact:
    id: str
    case_id: str
    field: str
    value: Any
    source: Source
    producer: Producer
    taint: TaintClass
    validation_status: FieldStatus = FieldStatus.UNCONFIRMED
    validated_by: list[str] = field(default_factory=list)
    created_at: str | None = None
