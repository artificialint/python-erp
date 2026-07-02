"""SQLAlchemy declarative base, shared enums, and the common table mixin.

Every erp_data table gets ``id`` (PK), ``status`` (active|archived soft-delete),
and ``created_at`` / ``updated_at`` via :class:`CommonMixin`. Enums are stored as
portable VARCHAR + CHECK (``native_enum=False``) so SQLite and Postgres/MySQL
behave identically.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for every erp_data model."""


class Status(str, enum.Enum):
    active = "active"
    archived = "archived"


class OrgType(str, enum.Enum):
    group = "group"
    company = "company"
    branch = "branch"
    department = "department"


class PartyType(str, enum.Enum):
    customer = "customer"
    supplier = "supplier"
    bank = "bank"
    consultant = "consultant"
    person = "person"
    carrier = "carrier"


class Role(str, enum.Enum):
    admin = "admin"
    user = "user"


class RuleType(str, enum.Enum):
    country_pair = "country_pair"
    product_specific = "product_specific"
    seller_default = "seller_default"


class ItemType(str, enum.Enum):
    product = "product"
    service = "service"


class DocumentType(str, enum.Enum):
    quotation = "quotation"
    proforma_invoice = "proforma_invoice"
    commercial_invoice = "commercial_invoice"


class ImportOutcome(str, enum.Enum):
    completed = "completed"
    completed_with_errors = "completed_with_errors"
    failed = "failed"


def status_column() -> Mapped[Status]:
    return mapped_column(
        SAEnum(Status, native_enum=False, length=16),
        default=Status.active,
        nullable=False,
    )


class CommonMixin:
    """id + status + timestamps shared by every table."""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    status: Mapped[Status] = mapped_column(
        SAEnum(Status, native_enum=False, length=16),
        default=Status.active,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
