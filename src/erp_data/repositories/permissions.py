"""Permission queries — the ergonomic core the caller/UI relies on.

Answers "which seller companies can this employee invoice for?" (autocomplete
source) and "is the employee admin or user for company X?".
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from erp_data.db import models
from erp_data.db.base import Role, Status


def permitted_organizations(
    session: Session, employee_id: int, module_code: str = "invoice"
) -> list[models.Organization]:
    """Organizations the employee may act for in a module (seller autocomplete source)."""
    stmt = (
        select(models.Organization)
        .join(
            models.EmployeeCompanyPermission,
            models.EmployeeCompanyPermission.organization_id == models.Organization.id,
        )
        .where(
            models.EmployeeCompanyPermission.employee_id == employee_id,
            models.EmployeeCompanyPermission.module_code == module_code,
            models.EmployeeCompanyPermission.status == Status.active,
            models.Organization.status == Status.active,
        )
        .distinct()
    )
    return list(session.execute(stmt).scalars().all())


def roles_for(
    session: Session, employee_id: int, organization_id: int, module_code: str = "invoice"
) -> set[Role]:
    """The set of roles the employee holds for (organization, module)."""
    stmt = select(models.EmployeeCompanyPermission.role).where(
        models.EmployeeCompanyPermission.employee_id == employee_id,
        models.EmployeeCompanyPermission.organization_id == organization_id,
        models.EmployeeCompanyPermission.module_code == module_code,
        models.EmployeeCompanyPermission.status == Status.active,
    )
    return set(session.execute(stmt).scalars().all())


def can_invoice_for(
    session: Session, employee_id: int, organization_id: int, module_code: str = "invoice"
) -> bool:
    """True if the employee holds any role (admin|user) for the (organization, module)."""
    return bool(roles_for(session, employee_id, organization_id, module_code))


def is_admin(
    session: Session, employee_id: int, organization_id: int, module_code: str = "invoice"
) -> bool:
    return Role.admin in roles_for(session, employee_id, organization_id, module_code)
