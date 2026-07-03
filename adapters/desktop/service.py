"""Desktop orchestrator — the ONLY place that imports both erp_data and erp_engine.

form input -> assembly.build_proforma_payload -> engine create_proforma
-> assembly.persist_document. Contains NO Qt; fully headless-testable. Keeps
erp_data engine-free and erp_engine DB-free (CONTRACT_v1 §8.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from erp_data import assembly
from erp_engine.modules.proforma import create_proforma


class ServiceError(Exception):
    """Engine returned a non-ok status (validation/execution)."""

    def __init__(self, message: str, errors: list | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


@dataclass
class InvoiceLineInput:
    product_code: str
    quantity: float
    unit_price: float | None = None  # None -> price-list lookup in assembly
    discount_percent: float = 0.0


@dataclass
class InvoiceFormInput:
    seller_code: str
    buyer: dict  # {"party_id": int} (db_lookup) or manual fields
    lines: list[InvoiceLineInput] = field(default_factory=list)
    document_type: str = "proforma_invoice"
    issue_date: str | None = None


@dataclass
class InvoiceOutcome:
    document_id: int
    document_no: str
    document_type: str
    currency: str | None
    subtotal: float
    tax: float
    grand_total: float


def create_document(session: Session, *, employee_id: int, form: InvoiceFormInput) -> InvoiceOutcome:
    """Assemble -> engine -> persist. Raises assembly.* (permission/price/reference)
    or ServiceError (engine non-ok)."""
    line_items: list[dict] = []
    for line in form.lines:
        item: dict = {
            "product_code": line.product_code,
            "quantity": line.quantity,
            "discount_percent": line.discount_percent,
        }
        if line.unit_price is not None:
            item["unit_price"] = line.unit_price
        line_items.append(item)

    payload = assembly.build_proforma_payload(
        session,
        employee_id=employee_id,
        seller_code=form.seller_code,
        buyer=form.buyer,
        line_items=line_items,
        document_type=form.document_type,
        issue_date=form.issue_date,
    )
    response = create_proforma(payload)
    if response.get("status") != "ok":
        raise ServiceError(f"engine returned {response.get('status')}", response.get("errors"))

    document = assembly.persist_document(
        session,
        response,
        created_by_employee_id=employee_id,
        buyer_party_id=form.buyer.get("party_id"),
    )
    session.commit()
    return InvoiceOutcome(
        document_id=document.id,
        document_no=document.document_no,
        document_type=document.document_type.value,
        currency=document.currency,
        subtotal=document.subtotal_amount,
        tax=document.tax_amount,
        grand_total=document.grand_total,
    )
