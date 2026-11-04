"""Vendor API schemas."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field



class CatalogueItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    tolerance: int = Field(default=0, ge=0, le=100000)


class VendorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    bank_reference: str = Field(min_length=1, max_length=128,
                                description="Transient; only its fingerprint is stored")
    catalogue: list[CatalogueItemIn] = Field(default_factory=list, max_length=500)
    per_invoice_cap: Decimal | None = None


class VendorUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    catalogue: list[CatalogueItemIn] | None = Field(default=None, max_length=500)
    per_invoice_cap: Decimal | None = None
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


class BankChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bank_reference: str = Field(min_length=1, max_length=128)
