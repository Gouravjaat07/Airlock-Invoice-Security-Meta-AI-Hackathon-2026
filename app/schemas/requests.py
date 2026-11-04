"""Request/response models for auth, cases, proposals, payments, audit."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: str = Field(min_length=4, max_length=64)


class ChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csrf_token: str | None = Field(default=None, max_length=128)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(min_length=1, max_length=128)
    pin: str = Field(min_length=4, max_length=64)
    csrf_token: str | None = Field(default=None, max_length=128)


class FactEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: object
    csrf_token: str | None = Field(default=None, max_length=128)


class ProcessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str | None = Field(default=None, max_length=128)


class EvalRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenarios: list[str] = Field(min_length=1, max_length=64)
    csrf_token: str | None = Field(default=None, max_length=128)
