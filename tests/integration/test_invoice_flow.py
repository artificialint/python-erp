"""INV-0.5 integration: data layer -> CONTRACT_v1 payload -> engine -> Document.

Proves the caller->engine boundary (CONTRACT_v1 §8.1) end to end without any UI:
sample import -> permission -> assemble -> create_proforma -> persist.
"""

from __future__ import annotations

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from erp_data import assembly
from erp_data.db import models
from erp_data.db.base import PartyType, Role
from erp_data.imports.importer import import_file
from erp_data.imports.templates import TEMPLATES
from erp_engine.modules.proforma import create_proforma

SAMPLES: dict[str, list[list]] = {
    "companies": [
        ["IST", "UNO AgentAI Ltd", "", "company", "Levent", "Istanbul", "TR",
         "", "", "1234567890", "TRY", "Example Bank", "1000123", "TR00", "EXAMPTR"],
        ["DXB", "UNO Dubai FZE", "", "company", "JLT", "Dubai", "AE",
         "", "", "", "AED", "", "", "", ""],
    ],
    "customers": [
        ["Anadolu Ticaret Ltd", "Ataturk Cad. 1", "Ankara", "TR",
         "", "buyer@example.com", "9876543210", "", ""],
    ],
    "products": [
        ["PRD-001", "Industrial Sensor", "902519", "PCS", "product", "", ""],
        ["PRD-NOPRICE", "No Price Item", "", "PCS", "product", "", ""],
    ],
    "price_lists": [
        ["PL-IST-2026", "IST", "PRD-001", "TRY", "100", "", "2026-01-01", ""],
    ],
}


def _write(path, template_type: str, rows: list[list]) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(TEMPLATES[template_type].columns)
    for row in rows:
        worksheet.append(row)
    workbook.save(path)


def _setup(session, tmp_path) -> tuple[models.Employee, models.Party]:
    for template_type, rows in SAMPLES.items():
        path = tmp_path / f"{template_type}.xlsx"
        _write(path, template_type, rows)
        import_file(session, template_type, path)

    murat = models.Party(party_type=PartyType.person, legal_name="Murat Demir")
    session.add(murat)
    session.flush()
    employee = models.Employee(person_party_id=murat.id, username="murat", title="Sales Manager")
    session.add(employee)
    session.flush()
    ist = session.execute(
        select(models.Organization).where(models.Organization.code == "IST")
    ).scalar_one()
    session.add(
        models.EmployeeCompanyPermission(
            employee_id=employee.id, organization_id=ist.id, module_code="invoice", role=Role.admin
        )
    )
    session.commit()
    buyer = session.execute(
        select(models.Party).where(
            models.Party.party_type == PartyType.customer,
            models.Party.legal_name == "Anadolu Ticaret Ltd",
        )
    ).scalar_one()
    return employee, buyer


def test_end_to_end_invoice_flow(flow_session, tmp_path) -> None:
    employee, buyer = _setup(flow_session, tmp_path)

    payload = assembly.build_proforma_payload(
        flow_session,
        employee_id=employee.id,
        seller_code="IST",
        buyer={"party_id": buyer.id},
        line_items=[{"product_code": "PRD-001", "quantity": 10}],
        document_type="proforma_invoice",
        issue_date="2026-06-07",
    )
    # unit_price resolved from the price list (100)
    assert payload["payload"]["line_items"][0]["unit_price"] == 100.0

    response = create_proforma(payload)
    assert response["status"] == "ok"
    assert response["result"]["document"]["document_type"] == "proforma_invoice"

    document = assembly.persist_document(
        flow_session, response, created_by_employee_id=employee.id, buyer_party_id=buyer.id
    )
    flow_session.commit()

    assert document.document_no.startswith("PRF-IST-2026-")
    assert document.grand_total == pytest.approx(1200.0)  # 1000 + 20% TR domestic VAT
    assert document.snapshot_json is not None
    lines = flow_session.execute(
        select(models.DocumentLine).where(models.DocumentLine.document_id == document.id)
    ).scalars().all()
    assert len(lines) == 1
    assert lines[0].line_total == pytest.approx(1200.0)


def test_unauthorized_seller_raises(flow_session, tmp_path) -> None:
    employee, buyer = _setup(flow_session, tmp_path)
    with pytest.raises(assembly.PermissionDenied):
        assembly.build_proforma_payload(
            flow_session,
            employee_id=employee.id,
            seller_code="DXB",  # no permission granted for DXB
            buyer={"party_id": buyer.id},
            line_items=[{"product_code": "PRD-001", "quantity": 1}],
        )


def test_manual_unit_price_overrides_price_list(flow_session, tmp_path) -> None:
    employee, buyer = _setup(flow_session, tmp_path)
    payload = assembly.build_proforma_payload(
        flow_session,
        employee_id=employee.id,
        seller_code="IST",
        buyer={"party_id": buyer.id},
        line_items=[{"product_code": "PRD-001", "quantity": 5, "unit_price": 250.0}],
    )
    assert payload["payload"]["line_items"][0]["unit_price"] == 250.0  # overrides the list's 100


def test_price_not_found_raises(flow_session, tmp_path) -> None:
    employee, buyer = _setup(flow_session, tmp_path)
    with pytest.raises(assembly.PriceNotFound):
        assembly.build_proforma_payload(
            flow_session,
            employee_id=employee.id,
            seller_code="IST",
            buyer={"party_id": buyer.id},
            line_items=[{"product_code": "PRD-NOPRICE", "quantity": 1}],  # no price at all
        )
