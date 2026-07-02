"""Assembly bridge: DB records <-> CONTRACT_v1 payloads / documents.

erp_data has ZERO dependency on erp_engine. This module ONLY:
  * ``build_proforma_payload`` — resolve DB records + enforce the seller permission,
    then return a plain CONTRACT_v1 request dict (no engine import).
  * ``persist_document`` — consume the engine's *result* dict and write an immutable
    Document (+ DocumentLine) snapshot.

The engine call itself lives in the orchestrator (the demo / a future desktop
adapter), which imports both erp_data and erp_engine. This preserves CONTRACT_v1
§8.1 (the engine never touches the DB; the caller resolves everything).

Unit-price precedence (Codex): manual ``unit_price`` on the line > valid
price_list_item (seller / currency / issue_date) > ``PriceNotFound``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from erp_data.db import models
from erp_data.db.base import DocumentType
from erp_data.repositories import permissions


class AssemblyError(Exception):
    """Base error for payload assembly / persistence."""


class PermissionDenied(AssemblyError):
    """The employee is not authorized to invoice for the requested seller."""


class PriceNotFound(AssemblyError):
    """No manual price and no valid price-list entry for a product."""


class ReferenceNotFound(AssemblyError):
    """A referenced master record (seller / buyer / product) does not exist."""


def _to_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value))
    return date.today()


def _resolve_unit_price(
    session: Session, product_id: int, organization_id: int, currency: str | None, on_date: date
) -> float | None:
    """Latest valid price_list_item for (product, seller-or-shared, currency, date)."""
    stmt = (
        select(models.PriceListItem.unit_price)
        .join(models.PriceList, models.PriceList.id == models.PriceListItem.price_list_id)
        .where(
            models.PriceListItem.product_id == product_id,
            or_(
                models.PriceList.organization_id == organization_id,
                models.PriceList.organization_id.is_(None),
            ),
            models.PriceList.valid_from <= on_date,
            or_(models.PriceList.valid_to.is_(None), models.PriceList.valid_to >= on_date),
        )
    )
    if currency:
        stmt = stmt.where(models.PriceList.currency == currency)
    stmt = stmt.order_by(models.PriceList.valid_from.desc())
    return session.execute(stmt).scalars().first()


def _party_block(party: models.Party, *, source: str) -> dict:
    return {
        "company_name": party.legal_name,
        "address": party.address or "",
        "city": party.city or "",
        "country": party.country or "",
        "phone": party.phone,
        "email": party.email,
        "tax_no": party.tax_no,
        "source": source,
    }


def build_proforma_payload(
    session: Session,
    *,
    employee_id: int,
    seller_code: str,
    buyer: dict,
    line_items: list[dict],
    document_type: str = "proforma_invoice",
    currency: str | None = None,
    issue_date: date | str | None = None,
    buyer_po_reference: str | None = None,
    request_id: str | None = None,
    context: dict | None = None,
) -> dict:
    """Resolve DB records into a CONTRACT_v1 request dict (engine-ready).

    Enforces the seller permission before building anything (an unauthorized seller
    raises ``PermissionDenied`` — the engine never sees the request).
    """
    seller = session.execute(
        select(models.Organization).where(models.Organization.code == seller_code)
    ).scalar_one_or_none()
    if seller is None:
        raise ReferenceNotFound(f"seller organization '{seller_code}' not found")

    if not permissions.can_invoice_for(session, employee_id, seller.id, "invoice"):
        raise PermissionDenied(
            f"employee {employee_id} is not authorized to invoice for '{seller_code}'"
        )

    on_date = _to_date(issue_date)
    curr = currency or seller.default_currency

    # buyer: db_lookup (party_id) or manual dict
    if buyer.get("party_id"):
        party = session.get(models.Party, buyer["party_id"])
        if party is None:
            raise ReferenceNotFound(f"buyer party id {buyer['party_id']} not found")
        buyer_block = _party_block(party, source="db_lookup")
    else:
        buyer_block = {
            "company_name": buyer.get("company_name", ""),
            "address": buyer.get("address", ""),
            "city": buyer.get("city", ""),
            "country": buyer.get("country", ""),
            "phone": buyer.get("phone"),
            "email": buyer.get("email"),
            "tax_no": buyer.get("tax_no"),
            "source": "manual_entry",
        }

    payload_lines: list[dict] = []
    for index, item in enumerate(line_items, start=1):
        code = item["product_code"]
        product = session.execute(
            select(models.ProductService).where(models.ProductService.code == code)
        ).scalar_one_or_none()
        if product is None:
            raise ReferenceNotFound(f"product '{code}' not found")

        unit_price = item.get("unit_price")
        if unit_price is None:  # precedence 2: price-list lookup
            unit_price = _resolve_unit_price(session, product.id, seller.id, curr, on_date)
        if unit_price is None:  # precedence 3: explicit error
            raise PriceNotFound(
                f"no price for product '{code}' (seller {seller_code}, {curr}, {on_date})"
            )

        payload_lines.append({
            "line_no": item.get("line_no", index),
            "product_code": product.code,
            "product_description": product.description,
            "hs_code": product.hs_code,
            "quantity": item["quantity"],
            "unit": product.unit,
            "unit_price": float(unit_price),
            "discount_percent": item.get("discount_percent", 0.0),
            "tax_percent": item.get("tax_percent"),
            "line_notes": item.get("line_notes", ""),
        })

    ctx = {
        "source": "erp_data.assembly",
        "actor_type": "employee",
        "actor_id": employee_id,
        "customer_id": None,
        "tenant_slug": None,
        "locale": "tr-TR",
        "timezone": "Europe/Istanbul",
    }
    if context:
        ctx.update(context)

    return {
        "schema_version": "contract_v1",
        "module": "proforma_invoice",
        "request_id": request_id or f"req_{seller_code}_{on_date.isoformat()}",
        "context": ctx,
        "payload": {
            "header": {
                "document_type": document_type,
                "issue_date": on_date.isoformat(),
                "document_no": None,
                "currency": curr,
                "valid_until": None,
                "buyer_po_reference": buyer_po_reference,
            },
            "seller": {
                "company_code": seller.code,
                "company_name": seller.legal_name,
                "address": seller.address or "",
                "city": seller.city or "",
                "country": seller.country or "",
                "phone": seller.phone,
                "email": seller.email,
                "tax_no": seller.tax_no,
            },
            "buyer": buyer_block,
            "ship_to": {"same_as_buyer": True, "source": "buyer_copy"},
            "line_items": payload_lines,
            "terms": {
                "freight_cost": 0.0,
                "delivery_term": "EXW",
                "delivery_location": None,
                "delivery_date": None,
                "payment_term": None,
            },
            "banking": {
                "bank_name": seller.bank_name,
                "bank_account": seller.bank_account,
                "iban": seller.iban,
                "swift_code": seller.swift_code,
            },
            "notes": {"notes_to_buyer": None, "internal_notes": None},
        },
    }


def persist_document(
    session: Session,
    result_envelope: dict,
    *,
    created_by_employee_id: int | None = None,
    buyer_party_id: int | None = None,
) -> models.Document:
    """Persist an engine ``ok`` result as an immutable Document (+ DocumentLine)."""
    if result_envelope.get("status") != "ok" or not result_envelope.get("result"):
        raise AssemblyError(
            f"cannot persist a non-ok engine response (status={result_envelope.get('status')!r})"
        )
    result = result_envelope["result"]
    doc = result["document"]
    totals = result["totals"]

    seller_code = result["parties"]["seller"]["company_code"]
    seller = session.execute(
        select(models.Organization).where(models.Organization.code == seller_code)
    ).scalar_one_or_none()
    if seller is None:
        raise ReferenceNotFound(f"seller '{seller_code}' not found while persisting")

    document = models.Document(
        document_no=doc["document_no"],
        document_type=DocumentType(doc["document_type"]),
        organization_id=seller.id,
        buyer_party_id=buyer_party_id,
        issue_date=_to_date(doc["issue_date"]),
        valid_until=_to_date(doc["valid_until"]) if doc.get("valid_until") else None,
        currency=doc.get("currency"),
        subtotal_amount=totals["subtotal_amount"],
        discount_amount=totals["discount_amount"],
        freight_amount=totals["freight_amount"],
        net_amount=totals["net_amount"],
        tax_amount=totals["tax_amount"],
        grand_total=totals["grand_total"],
        snapshot_json=result,
        created_by_employee_id=created_by_employee_id,
    )
    session.add(document)
    session.flush()

    for line in result["line_items"]:
        session.add(
            models.DocumentLine(
                document_id=document.id,
                line_no=line["line_no"],
                product_code=line.get("product_code"),
                product_description=line.get("product_description"),
                hs_code=line.get("hs_code"),
                quantity=line.get("quantity", 0.0),
                unit=line.get("unit"),
                unit_price=line.get("unit_price", 0.0),
                discount_percent=line.get("discount_percent", 0.0),
                discount_amount=line.get("discount_amount", 0.0),
                tax_percent=line.get("tax_percent", 0.0),
                tax_reason=line.get("tax_reason"),
                tax_amount=line.get("tax_amount", 0.0),
                line_total=line.get("line_total", 0.0),
            )
        )
    session.flush()
    return document
