"""INV-0: Excel import — happy rows land in DB, invalid rows -> import_errors."""

from __future__ import annotations

from openpyxl import Workbook
from sqlalchemy import select

from erp_data.db import models
from erp_data.imports.importer import import_file
from erp_data.imports.templates import TEMPLATES


def _write_xlsx(path, template_type: str, rows: list[list]) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(TEMPLATES[template_type].columns)
    for row in rows:
        worksheet.append(row)
    workbook.save(path)


def test_companies_import_valid_and_invalid(erp_session, tmp_path) -> None:
    path = tmp_path / "companies.xlsx"
    _write_xlsx(
        path,
        "companies",
        [
            # valid
            ["IST", "UNO AgentAI Ltd", "", "company", "", "Istanbul", "TR",
             "", "", "", "TRY", "", "", "", ""],
            # invalid: legal_name (required) missing
            ["BER", "", "", "company", "", "Berlin", "DE",
             "", "", "", "EUR", "", "", "", ""],
        ],
    )
    batch = import_file(erp_session, "companies", path)

    assert batch.total_rows == 2
    assert batch.valid_rows == 1
    assert batch.invalid_rows == 1
    assert batch.outcome.value == "completed_with_errors"

    orgs = erp_session.execute(select(models.Organization)).scalars().all()
    assert [o.code for o in orgs] == ["IST"]
    assert orgs[0].country == "TR"

    errors = erp_session.execute(select(models.ImportRowError)).scalars().all()
    assert len(errors) == 1
    assert errors[0].error_code == "required_field_missing"
    assert errors[0].row_number == 3  # header=1, valid=2, invalid=3


def test_products_import_happy(erp_session, tmp_path) -> None:
    path = tmp_path / "products.xlsx"
    _write_xlsx(
        path,
        "products",
        [["PRD-001", "Industrial Sensor", "902519", "PCS", "product", "20", ""]],
    )
    batch = import_file(erp_session, "products", path)

    assert batch.valid_rows == 1
    assert batch.invalid_rows == 0
    assert batch.outcome.value == "completed"

    product = erp_session.execute(
        select(models.ProductService).where(models.ProductService.code == "PRD-001")
    ).scalar_one()
    assert product.description == "Industrial Sensor"
    assert product.product_tax_percent == 20.0


def test_import_is_idempotent(erp_session, tmp_path) -> None:
    path = tmp_path / "companies.xlsx"
    _write_xlsx(
        path,
        "companies",
        [["IST", "UNO AgentAI Ltd", "", "company", "", "Istanbul", "TR",
          "", "", "", "TRY", "", "", "", ""]],
    )
    import_file(erp_session, "companies", path)
    import_file(erp_session, "companies", path)  # re-import
    orgs = erp_session.execute(select(models.Organization)).scalars().all()
    assert len(orgs) == 1  # upsert by code, no duplicate
