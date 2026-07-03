"""First-run demo seed — populates a working sample dataset when the DB is empty.

So the desktop opens onto a working invoice form instead of an empty screen. The
real import UI (companies/products pages) is a later sprint.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from erp_data.db import models
from erp_data.db.base import OrgType, PartyType, Role


def is_empty(session: Session) -> bool:
    return session.execute(select(func.count()).select_from(models.Organization)).scalar_one() == 0


def seed_sample(session: Session) -> None:
    """Idempotent: seed IST/DXB orgs, a customer, a product+price, and an employee
    (murat, invoice.admin for IST) — only if the DB has no organizations yet."""
    if not is_empty(session):
        return

    ist = models.Organization(
        code="IST", legal_name="UNO AgentAI Ltd", org_type=OrgType.company,
        address="Levent Mah.", city="Istanbul", country="TR", default_currency="TRY",
        bank_name="Example Bank", bank_account="1000123", iban="TR00", swift_code="EXAMPTR",
    )
    dxb = models.Organization(
        code="DXB", legal_name="UNO Dubai FZE", org_type=OrgType.company,
        city="Dubai", country="AE", default_currency="AED",
    )
    session.add_all([ist, dxb])
    session.flush()

    session.add(models.Party(
        party_type=PartyType.customer, legal_name="Anadolu Ticaret Ltd",
        address="Ataturk Cad. 1", city="Ankara", country="TR",
        email="buyer@example.com", tax_no="9876543210",
    ))
    product = models.ProductService(
        code="PRD-001", description="Industrial Sensor", hs_code="902519", unit="PCS"
    )
    session.add(product)
    session.flush()

    price_list = models.PriceList(
        code="PL-IST-2026", organization_id=ist.id, currency="TRY", valid_from=date(2026, 1, 1)
    )
    session.add(price_list)
    session.flush()
    session.add(models.PriceListItem(
        price_list_id=price_list.id, product_id=product.id, unit_price=100.0
    ))

    murat = models.Party(party_type=PartyType.person, legal_name="Murat Demir")
    session.add(murat)
    session.flush()
    employee = models.Employee(person_party_id=murat.id, username="murat", title="Sales Manager")
    session.add(employee)
    session.flush()
    session.add(models.EmployeeCompanyPermission(
        employee_id=employee.id, organization_id=ist.id, module_code="invoice", role=Role.admin
    ))
    session.commit()
