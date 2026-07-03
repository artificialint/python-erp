"""INV-1: desktop orchestrator service (headless — no Qt in the pytest suite)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from adapters.desktop import service
from adapters.desktop.sample_seed import seed_sample
from erp_data import assembly
from erp_data.db import models
from erp_data.db.base import PartyType


def _seed(session) -> tuple[models.Employee, models.Party]:
    seed_sample(session)
    employee = session.execute(select(models.Employee)).scalar_one()
    buyer = session.execute(
        select(models.Party).where(models.Party.party_type == PartyType.customer)
    ).scalar_one()
    return employee, buyer


def test_service_creates_document(flow_session) -> None:
    employee, buyer = _seed(flow_session)
    form = service.InvoiceFormInput(
        seller_code="IST",
        buyer={"party_id": buyer.id},
        lines=[service.InvoiceLineInput(product_code="PRD-001", quantity=10)],
        document_type="proforma_invoice",
        issue_date="2026-06-07",
    )
    outcome = service.create_document(flow_session, employee_id=employee.id, form=form)

    assert outcome.document_no.startswith("PRF-IST-2026-")
    assert outcome.grand_total == pytest.approx(1200.0)  # price-list 100 * 10 + 20% TR VAT
    document = flow_session.get(models.Document, outcome.document_id)
    assert document is not None
    lines = flow_session.execute(
        select(models.DocumentLine).where(models.DocumentLine.document_id == document.id)
    ).scalars().all()
    assert len(lines) == 1


def test_service_manual_price(flow_session) -> None:
    employee, buyer = _seed(flow_session)
    form = service.InvoiceFormInput(
        seller_code="IST",
        buyer={"party_id": buyer.id},
        lines=[service.InvoiceLineInput(product_code="PRD-001", quantity=2, unit_price=500.0)],
    )
    outcome = service.create_document(flow_session, employee_id=employee.id, form=form)
    assert outcome.subtotal == pytest.approx(1000.0)  # 2 * 500 manual override


def test_service_unauthorized_seller_raises(flow_session) -> None:
    employee, buyer = _seed(flow_session)
    form = service.InvoiceFormInput(
        seller_code="DXB",  # employee has no permission for DXB
        buyer={"party_id": buyer.id},
        lines=[service.InvoiceLineInput(product_code="PRD-001", quantity=1)],
    )
    with pytest.raises(assembly.PermissionDenied):
        service.create_document(flow_session, employee_id=employee.id, form=form)
