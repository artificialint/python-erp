"""Proforma Invoice — Pydantic models for the v1 contract.

Source of truth:
    template/docs/CONTRACT_v1.md
    template/docs/modules/PROFORMA_v1.md

This file is the executable mirror of the contract. If the contract
changes, this file changes in the same commit. Tests verify the shape.

Monetary amounts use ``float`` in v1 to match the JSON examples in the
contract. A future revision may switch to ``Decimal`` once the precision
policy is locked.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─────────────────────────────────────────────────────────────────────
# Envelope
# ─────────────────────────────────────────────────────────────────────


class Context(BaseModel):
    """Non-business transport/application metadata.

    Contract reference: CONTRACT_v1.md §6.
    """

    source: str
    actor_type: str
    actor_id: Optional[int] = None
    customer_id: Optional[int] = None
    tenant_slug: Optional[str] = None
    locale: str = "tr-TR"
    timezone: str = "Europe/Istanbul"


class RequestEnvelope(BaseModel):
    """Top-level request envelope shared by every module.

    Contract reference: CONTRACT_v1.md §5.1.
    """

    schema_version: Literal["contract_v1"]
    module: Literal["proforma_invoice"]
    request_id: str
    context: Context
    payload: "ProformaPayload"


class ValidationError(BaseModel):
    """Field-targeted input validation error.

    Contract reference: CONTRACT_v1.md §12.1.
    """

    code: str
    field: Optional[str] = None
    message: str


class ExecutionError(BaseModel):
    """Engine-side execution failure not attributable to a payload field.

    Contract reference: CONTRACT_v1.md §12.2.
    """

    code: str
    field: Optional[str] = None
    message: str


class Warning(BaseModel):
    """Non-blocking advisory the engine surfaces alongside a successful result.

    Contract reference: CONTRACT_v1.md §12.3.
    """

    code: str
    field: Optional[str] = None
    message: str


class ResponseEnvelope(BaseModel):
    """Top-level response envelope.

    Contract reference: CONTRACT_v1.md §5.2.
    """

    schema_version: Literal["contract_v1"] = "contract_v1"
    module: Literal["proforma_invoice"] = "proforma_invoice"
    request_id: str
    status: Literal["ok", "validation_error", "execution_error"]
    result: Optional["ProformaResult"] = None
    errors: list[ValidationError | ExecutionError] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)

    # Allow either ValidationError or ExecutionError instances in `errors`.
    model_config = ConfigDict(arbitrary_types_allowed=True)


# ─────────────────────────────────────────────────────────────────────
# Request payload — submitted form data
# ─────────────────────────────────────────────────────────────────────


class Header(BaseModel):
    """Document header inputs.

    Contract reference: CONTRACT_v1.md §7.2.
    """

    document_type: Literal["quotation", "proforma_invoice", "commercial_invoice"] = (
        "proforma_invoice"
    )
    issue_date: str  # ISO date YYYY-MM-DD
    document_no: Optional[str] = None  # engine generates if absent
    currency: str  # ISO 4217; v1 must match seller default
    valid_until: Optional[str] = None  # engine sets issue_date + 30 if absent
    buyer_po_reference: Optional[str] = None


class Seller(BaseModel):
    """Seller block. ``company_code`` is the canonical selector.

    Contract reference: CONTRACT_v1.md §7.3.
    """

    company_code: str
    company_name: str
    address: str
    city: str
    country: str  # ISO 3166-1 alpha-2
    phone: Optional[str] = None
    email: Optional[str] = None
    tax_no: Optional[str] = None


class Buyer(BaseModel):
    """Buyer block.

    Contract reference: CONTRACT_v1.md §7.4.
    """

    company_name: str
    address: str
    city: str
    country: str
    phone: Optional[str] = None
    email: Optional[str] = None
    tax_no: Optional[str] = None
    customer_no: Optional[int] = None  # A4 — buyer master number; label for {CUSTOMER_NO}
    source: Literal["db_lookup", "manual_entry"] = "manual_entry"


class ShipTo(BaseModel):
    """Ship-to block.

    Contract reference: CONTRACT_v1.md §7.5.
    """

    same_as_buyer: bool = True
    company_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    source: Literal["buyer_copy", "db_lookup", "manual_entry"] = "buyer_copy"


class LineItem(BaseModel):
    """A single proforma line item.

    Contract reference: CONTRACT_v1.md §7.6.

    The engine recomputes ``line_total``; clients should not provide it.
    ``tax_percent`` may be left ``None`` so the engine can apply the
    precedence chain.
    """

    line_no: int
    product_code: str
    product_description: Optional[str] = None
    hs_code: Optional[str] = None
    quantity: float
    unit: Optional[str] = None
    unit_price: float
    discount_percent: float = 0.0
    tax_percent: Optional[float] = None
    line_notes: Optional[str] = ""

    @field_validator("quantity")
    @classmethod
    def _quantity_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("quantity must be > 0")
        return value


class Terms(BaseModel):
    """Commercial terms.

    Contract reference: CONTRACT_v1.md §7.7.
    """

    freight_cost: float = 0.0
    delivery_term: str = "EXW"
    delivery_location: Optional[str] = None
    delivery_date: Optional[str] = None
    payment_term: Optional[str] = None


class Banking(BaseModel):
    """Banking block — typically resolved from selected seller.

    Contract reference: CONTRACT_v1.md §7.8.
    """

    bank_name: Optional[str] = None
    bank_account: Optional[str] = None
    iban: Optional[str] = None
    swift_code: Optional[str] = None


class Notes(BaseModel):
    """Notes block.

    Contract reference: CONTRACT_v1.md §7.9.
    """

    notes_to_buyer: Optional[str] = None
    internal_notes: Optional[str] = None


class Numbering(BaseModel):
    """Document-numbering config (A4, 2026-07-05).

    Caller-supplied numbering rule (from the tenant's
    ``customer_module_settings.settings_json.numbering``). Absent / None
    fields fall back to the engine defaults (legacy PRF template +
    ``per_seller_annual``), preserving backward compatibility.

    Contract reference: CONTRACT_v1.md §10.
    """

    template: Optional[str] = None
    counter_scope: Optional[str] = None
    seq: Optional[int] = None  # A5 — caller-supplied sequence → render-only (no counter)


class ProformaPayload(BaseModel):
    """Top-level proforma payload.

    Contract reference: CONTRACT_v1.md §7.1.
    """

    header: Header
    seller: Seller
    buyer: Buyer
    ship_to: ShipTo
    line_items: list[LineItem]
    terms: Terms = Field(default_factory=Terms)
    banking: Banking = Field(default_factory=Banking)
    notes: Notes = Field(default_factory=Notes)
    numbering: Numbering = Field(default_factory=Numbering)  # A4

    @field_validator("line_items")
    @classmethod
    def _at_least_one_line(cls, value: list[LineItem]) -> list[LineItem]:
        if len(value) < 1:
            raise ValueError("at least one line item is required")
        return value


# ─────────────────────────────────────────────────────────────────────
# Result — engine output
# ─────────────────────────────────────────────────────────────────────


class ResultDocument(BaseModel):
    """Engine-resolved document identity.

    Contract reference: CONTRACT_v1.md §11.2.
    """

    document_type: Literal["quotation", "proforma_invoice", "commercial_invoice"] = (
        "proforma_invoice"
    )
    document_no: str
    issue_date: str
    valid_until: str
    currency: str


class ResultParties(BaseModel):
    """Engine-normalized parties block.

    Contract reference: CONTRACT_v1.md §11.3.
    """

    seller: Seller
    buyer: Buyer
    ship_to: ShipTo


class ResultLineItem(BaseModel):
    """One line item after engine computation.

    Contract reference: CONTRACT_v1.md §11.4.
    """

    line_no: int
    product_code: str
    product_description: Optional[str] = None
    hs_code: Optional[str] = None
    quantity: float
    unit: Optional[str] = None
    unit_price: float
    discount_percent: float = 0.0
    discount_amount: float = 0.0
    tax_percent: float = 0.0
    tax_reason: str
    tax_amount: float = 0.0
    line_total: float = 0.0


class ResultTotals(BaseModel):
    """Document-level totals summary.

    Contract reference: CONTRACT_v1.md §11.5.
    """

    subtotal_amount: float
    discount_amount: float
    freight_amount: float
    net_amount: float
    tax_amount: float
    grand_total: float


class CalculationTrace(BaseModel):
    """Lightweight reasoning metadata.

    Contract reference: CONTRACT_v1.md §11.6.
    """

    tax_precedence_applied: list[str] = Field(default_factory=list)
    tax_reason_summary: list[str] = Field(default_factory=list)
    document_number_template: Optional[str] = None
    counter_scope: Optional[str] = None


class ProformaResult(BaseModel):
    """Full engine result for a proforma_invoice request.

    Contract reference: CONTRACT_v1.md §11.1.
    """

    document: ResultDocument
    parties: ResultParties
    line_items: list[ResultLineItem]
    totals: ResultTotals
    calculation_trace: CalculationTrace


# ─────────────────────────────────────────────────────────────────────
# Forward-reference resolution (Pydantic v2)
# ─────────────────────────────────────────────────────────────────────

RequestEnvelope.model_rebuild()
ResponseEnvelope.model_rebuild()
