"""Pydantic models for the ParcelPilot assessment workbook."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict


class Account(BaseModel):
    """Representation of the accounts worksheet row."""

    model_config = ConfigDict(extra="ignore")

    account_id: str
    account_name: str
    plan: str
    status: str
    csm: str
    contract_file: Optional[str] = None
    premium_support: bool
    notes: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Account":
        return cls.model_validate(row)


class Order(BaseModel):
    """Representation of the orders worksheet row."""

    model_config = ConfigDict(extra="ignore")

    order_id: str
    account_id: str
    carrier: str
    status: str
    booked_at: Optional[str] = None
    pickup_window_start: Optional[str] = None
    pickup_window_end: Optional[str] = None
    pickup_actual_at: Optional[str] = None
    shipment_fee_inr: int
    carrier_fault: bool
    customer_fault: bool
    cancellation_requested_at: Optional[str] = None
    notes: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Order":
        return cls.model_validate(row)


class Ticket(BaseModel):
    """Representation of the tickets worksheet row."""

    model_config = ConfigDict(extra="ignore")

    ticket_id: str
    account_id: str
    created_at: str
    status: str
    subject: str
    description: str
    channel: str
    assigned_to: str
    last_customer_message_at: Optional[str] = None
    historical_resolution: Optional[str] = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Ticket":
        return cls.model_validate(row)
