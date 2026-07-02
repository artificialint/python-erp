"""INV-0: permission queries — permitted companies + admin/user roles."""

from __future__ import annotations

from erp_data.db import models
from erp_data.db.base import PartyType, Role
from erp_data.repositories import permissions


def _make_employee(session) -> tuple[models.Employee, dict[str, models.Organization]]:
    orgs = {
        code: models.Organization(code=code, legal_name=f"Company {code}")
        for code in ("A", "B", "C")
    }
    session.add_all(orgs.values())
    person = models.Party(party_type=PartyType.person, legal_name="Murat")
    session.add(person)
    session.flush()
    employee = models.Employee(person_party_id=person.id, username="murat", title="Sales Manager")
    session.add(employee)
    session.flush()
    session.add_all(
        [
            models.EmployeeCompanyPermission(
                employee_id=employee.id, organization_id=orgs["A"].id,
                module_code="invoice", role=Role.admin,
            ),
            models.EmployeeCompanyPermission(
                employee_id=employee.id, organization_id=orgs["B"].id,
                module_code="invoice", role=Role.user,
            ),
        ]
    )
    session.commit()
    return employee, orgs


def test_permitted_organizations_excludes_unauthorized(erp_session) -> None:
    employee, orgs = _make_employee(erp_session)
    permitted = permissions.permitted_organizations(erp_session, employee.id, "invoice")
    assert sorted(o.code for o in permitted) == ["A", "B"]  # C has no grant


def test_can_invoice_for(erp_session) -> None:
    employee, orgs = _make_employee(erp_session)
    assert permissions.can_invoice_for(erp_session, employee.id, orgs["A"].id) is True
    assert permissions.can_invoice_for(erp_session, employee.id, orgs["C"].id) is False


def test_admin_vs_user(erp_session) -> None:
    employee, orgs = _make_employee(erp_session)
    assert permissions.is_admin(erp_session, employee.id, orgs["A"].id) is True
    assert permissions.is_admin(erp_session, employee.id, orgs["B"].id) is False  # user role
