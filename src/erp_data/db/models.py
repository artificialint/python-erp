"""ORM models for the ERP data layer (14 tables).

See docs/PYTHON_ERP_INV0_PLAN.md §2. Conventions (via CommonMixin): ``id`` PK,
``status`` soft-delete, ``created_at``/``updated_at``. Money = float (v1); country
= ISO-3166 alpha-2; currency = ISO-4217. Enums = portable VARCHAR + CHECK.

erp_data has NO dependency on erp_engine (CONTRACT_v1 §8.1).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_data.db.base import (
    Base,
    CommonMixin,
    DocumentType,
    ImportOutcome,
    ItemType,
    OrgType,
    PartyType,
    Role,
    RuleType,
)


class Organization(CommonMixin, Base):
    """OUR seller companies (CONTRACT_v1 `seller` side; ``code`` == SELLER_CODE)."""

    __tablename__ = "organizations"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    org_type: Mapped[OrgType] = mapped_column(
        SAEnum(OrgType, native_enum=False, length=16), default=OrgType.company, nullable=False
    )
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(2))
    phone: Mapped[str | None] = mapped_column(String(60))
    email: Mapped[str | None] = mapped_column(String(160))
    tax_no: Mapped[str | None] = mapped_column(String(60))
    default_currency: Mapped[str | None] = mapped_column(String(3))
    bank_name: Mapped[str | None] = mapped_column(String(160))
    bank_account: Mapped[str | None] = mapped_column(String(60))
    iban: Mapped[str | None] = mapped_column(String(40))
    swift_code: Mapped[str | None] = mapped_column(String(16))


class Party(CommonMixin, Base):
    """Counterparties + persons (customer/supplier/bank/consultant/person/carrier)."""

    __tablename__ = "parties"

    party_type: Mapped[PartyType] = mapped_column(
        SAEnum(PartyType, native_enum=False, length=16), nullable=False
    )
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(2))
    phone: Mapped[str | None] = mapped_column(String(60))
    email: Mapped[str | None] = mapped_column(String(160))
    tax_no: Mapped[str | None] = mapped_column(String(60))
    default_discount_percent: Mapped[float | None] = mapped_column(Float)
    default_payment_term_code: Mapped[str | None] = mapped_column(String(32))


class Employee(CommonMixin, Base):
    """Login user = a person (party) promoted with credentials + a title."""

    __tablename__ = "employees"

    person_party_id: Mapped[int] = mapped_column(
        ForeignKey("parties.id"), unique=True, nullable=False
    )
    username: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(120))


class EmployeeCompanyPermission(CommonMixin, Base):
    """(employee, organization, module_code, role) grant — the permission model."""

    __tablename__ = "employee_company_permissions"
    __table_args__ = (
        UniqueConstraint(
            "employee_id",
            "organization_id",
            "module_code",
            "role",
            name="uq_employee_company_module_role",
        ),
    )

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    module_code: Mapped[str] = mapped_column(String(60), nullable=False)
    role: Mapped[Role] = mapped_column(SAEnum(Role, native_enum=False, length=16), nullable=False)


class ProductService(CommonMixin, Base):
    __tablename__ = "products_services"

    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    hs_code: Mapped[str | None] = mapped_column(String(24))
    unit: Mapped[str | None] = mapped_column(String(16))
    item_type: Mapped[ItemType] = mapped_column(
        SAEnum(ItemType, native_enum=False, length=16), default=ItemType.product, nullable=False
    )
    product_tax_percent: Mapped[float | None] = mapped_column(Float)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))


class PriceList(CommonMixin, Base):
    __tablename__ = "price_lists"

    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(160))
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    currency: Mapped[str | None] = mapped_column(String(3))
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)


class PriceListItem(CommonMixin, Base):
    __tablename__ = "price_list_items"
    __table_args__ = (
        UniqueConstraint("price_list_id", "product_id", name="uq_pricelist_product"),
    )

    price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products_services.id"), nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    min_quantity: Mapped[float | None] = mapped_column(Float)


class TaxRule(CommonMixin, Base):
    __tablename__ = "tax_rules"

    rule_type: Mapped[RuleType] = mapped_column(
        SAEnum(RuleType, native_enum=False, length=24), nullable=False
    )
    seller_country: Mapped[str | None] = mapped_column(String(2))
    buyer_country: Mapped[str | None] = mapped_column(String(2))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products_services.id"))
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(60), nullable=False)


class PaymentTerm(CommonMixin, Base):
    __tablename__ = "payment_terms"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class DocnoRule(CommonMixin, Base):
    __tablename__ = "docno_rules"
    __table_args__ = (
        UniqueConstraint("organization_id", "document_type", name="uq_docno_org_doctype"),
    )

    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, native_enum=False, length=24), nullable=False
    )
    template: Mapped[str] = mapped_column(String(120), nullable=False)
    counter_scope: Mapped[str] = mapped_column(String(60), nullable=False)


class Document(CommonMixin, Base):
    """Issued document — IMMUTABLE snapshot (``snapshot_json`` = full engine result)."""

    __tablename__ = "documents"

    document_no: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(
        SAEnum(DocumentType, native_enum=False, length=24), nullable=False
    )
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    buyer_party_id: Mapped[int | None] = mapped_column(ForeignKey("parties.id"))
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    subtotal_amount: Mapped[float] = mapped_column(Float, default=0.0)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0)
    freight_amount: Mapped[float] = mapped_column(Float, default=0.0)
    net_amount: Mapped[float] = mapped_column(Float, default=0.0)
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0)
    grand_total: Mapped[float] = mapped_column(Float, default=0.0)
    snapshot_json: Mapped[dict | None] = mapped_column(JSON)
    created_by_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))

    lines: Mapped[list["DocumentLine"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentLine(CommonMixin, Base):
    __tablename__ = "document_lines"
    __table_args__ = (
        UniqueConstraint("document_id", "line_no", name="uq_document_line_no"),
    )

    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(60))
    product_description: Mapped[str | None] = mapped_column(String(500))
    hs_code: Mapped[str | None] = mapped_column(String(24))
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit: Mapped[str | None] = mapped_column(String(16))
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    discount_percent: Mapped[float] = mapped_column(Float, default=0.0)
    discount_amount: Mapped[float] = mapped_column(Float, default=0.0)
    tax_percent: Mapped[float] = mapped_column(Float, default=0.0)
    tax_reason: Mapped[str | None] = mapped_column(String(60))
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0)
    line_total: Mapped[float] = mapped_column(Float, default=0.0)

    document: Mapped["Document"] = relationship(back_populates="lines")


class ImportBatch(CommonMixin, Base):
    __tablename__ = "import_batches"

    template_type: Mapped[str] = mapped_column(String(60), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255))
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[ImportOutcome] = mapped_column(
        SAEnum(ImportOutcome, native_enum=False, length=32),
        default=ImportOutcome.completed,
        nullable=False,
    )
    created_by_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))

    errors: Mapped[list["ImportRowError"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class ImportRowError(CommonMixin, Base):
    """Row-level import error (table ``import_errors``). Named to avoid shadowing
    the built-in ``ImportError`` exception."""

    __tablename__ = "import_errors"

    import_batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id"), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    column_name: Mapped[str | None] = mapped_column(String(60))
    error_code: Mapped[str] = mapped_column(String(60), nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)

    batch: Mapped["ImportBatch"] = relationship(back_populates="errors")
