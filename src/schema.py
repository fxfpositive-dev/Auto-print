from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class StatementEntry(BaseModel):
    """Common schema for statement entries across providers."""

    date: date = Field(..., description="Transaction date")
    merchant: str = Field(..., description="Merchant or store name")
    amount: Decimal = Field(..., description="Transaction amount")
    note: str | None = Field(default=None, description="Optional memo")
