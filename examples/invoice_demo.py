"""INV-0.5 end-to-end demo — data layer feeds the deterministic engine.

Run headlessly:  python examples/invoice_demo.py

Chain: bootstrap temp SQLite -> load invoice manifest -> import sample
companies/customers/products/price_lists -> create an employee + permission ->
query permitted sellers -> assemble a CONTRACT_v1 payload -> call the engine ->
persist the result as a Document (+ lines) -> print. Then a NEGATIVE case: an
unauthorized seller raises PermissionDenied.

No PySide6, no PDF, no PHP, no AI, no real secrets — temp DB only.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from openpyxl import Workbook  # noqa: E402
from sqlalchemy import select  # noqa: E402

from erp_data import assembly  # noqa: E402
from erp_data.db import models  # noqa: E402
from erp_data.db.base import PartyType, Role  # noqa: E402
from erp_data.db.init_db import bootstrap  # noqa: E402
from erp_data.imports.importer import import_file  # noqa: E402
from erp_data.imports.templates import TEMPLATES  # noqa: E402
from erp_data.registry.loader import find_module  # noqa: E402
from erp_data.repositories import permissions  # noqa: E402
from erp_engine.modules.proforma import create_proforma  # noqa: E402

SAMPLES: dict[str, list[list]] = {
    "companies": [
        ["IST", "UNO AgentAI Ltd", "", "company", "Levent Mah.", "Istanbul", "TR",
         "+90 212 000 00 00", "sales@example.com", "1234567890", "TRY",
         "Example Bank", "1000123", "TR000000000000000000000000", "EXAMPTR"],
        ["DXB", "UNO Dubai FZE", "", "company", "JLT", "Dubai", "AE",
         "", "", "", "AED", "", "", "", ""],
    ],
    "customers": [
        ["Anadolu Ticaret Ltd", "Ataturk Cad. 1", "Ankara", "TR",
         "+90 312 000 00 00", "buyer@example.com", "9876543210", "", ""],
    ],
    "products": [
        ["PRD-001", "Industrial Sensor", "902519", "PCS", "product", "", ""],
    ],
    "price_lists": [
        ["PL-IST-2026", "IST", "PRD-001", "TRY", "100", "", "2026-01-01", ""],
    ],
}


def _write_template(path: Path, template_type: str, rows: list[list]) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(TEMPLATES[template_type].columns)
    for row in rows:
        worksheet.append(row)
    workbook.save(path)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="erp_demo_"))
    os.environ["ERP_ENGINE_COUNTER_DB"] = str(tmp / "counters.db")  # keep repo counter clean

    engine, session_factory = bootstrap(tmp / "erp.sqlite")
    with session_factory() as session:
        module = find_module("invoice")
        print(f"module: {module.code} v{module.version} (engine_module={module.engine_module})")

        for template_type, rows in SAMPLES.items():
            path = tmp / f"{template_type}.xlsx"
            _write_template(path, template_type, rows)
            batch = import_file(session, template_type, path)
            print(f"import {template_type:11s}: {batch.valid_rows} valid, "
                  f"{batch.invalid_rows} invalid ({batch.outcome.value})")

        # promote a person to an employee + grant IST/invoice.admin (the "UI" step)
        person = session.execute(
            select(models.Party).where(models.Party.legal_name == "Anadolu Ticaret Ltd")
        ).scalar_one()  # reuse as our buyer below
        murat = models.Party(party_type=PartyType.person, legal_name="Murat Demir")
        session.add(murat)
        session.flush()
        employee = models.Employee(person_party_id=murat.id, username="murat", title="Sales Manager")
        session.add(employee)
        session.flush()
        ist = session.execute(select(models.Organization).where(models.Organization.code == "IST")).scalar_one()
        session.add(models.EmployeeCompanyPermission(
            employee_id=employee.id, organization_id=ist.id, module_code="invoice", role=Role.admin))
        session.commit()

        permitted = [o.code for o in permissions.permitted_organizations(session, employee.id)]
        print(f"permitted sellers for {employee.username}: {permitted}")

        buyer = session.execute(
            select(models.Party).where(
                models.Party.party_type == PartyType.customer,
                models.Party.legal_name == "Anadolu Ticaret Ltd",
            )
        ).scalar_one()

        # ── positive: assemble -> engine -> persist ─────────────────────
        payload = assembly.build_proforma_payload(
            session,
            employee_id=employee.id,
            seller_code="IST",
            buyer={"party_id": buyer.id},
            line_items=[{"product_code": "PRD-001", "quantity": 10}],
            document_type="proforma_invoice",
            issue_date="2026-06-07",
        )
        response = create_proforma(payload)
        print(f"engine status: {response['status']}")
        document = assembly.persist_document(
            session, response, created_by_employee_id=employee.id, buyer_party_id=buyer.id
        )
        session.commit()

        print("--- persisted document ---")
        print(f"  document_type : {document.document_type.value}")
        print(f"  document_no   : {document.document_no}")
        print(f"  currency      : {document.currency}")
        print(f"  subtotal      : {document.subtotal_amount}")
        print(f"  tax           : {document.tax_amount}")
        print(f"  grand_total   : {document.grand_total}")
        lines = session.execute(
            select(models.DocumentLine).where(models.DocumentLine.document_id == document.id)
        ).scalars().all()
        print(f"  document_lines: {len(lines)} "
              f"(unit_price from price list = {lines[0].unit_price})")

        # ── negative: unauthorized seller ───────────────────────────────
        try:
            assembly.build_proforma_payload(
                session,
                employee_id=employee.id,
                seller_code="DXB",  # Murat has no permission here
                buyer={"party_id": buyer.id},
                line_items=[{"product_code": "PRD-001", "quantity": 1}],
            )
            print("NEGATIVE CASE FAILED: DXB should have been blocked")
            return 1
        except assembly.PermissionDenied as exc:
            print(f"unauthorized seller DXB blocked: PermissionDenied ({exc})")

    engine.dispose()
    print("\nOK - data layer feeds the engine end to end.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
