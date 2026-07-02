"""Fixed Excel template specs + generator (openpyxl).

Technical column names in English (helper/description text TR/EN can be layered on
later). Templates reference masters by business code (organization_code,
product_code), never numeric ids, so an operator can fill them by hand.

See docs/PYTHON_ERP_INV0_PLAN.md §4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook


@dataclass(frozen=True)
class TemplateSpec:
    template_type: str
    target: str  # target table (documentation)
    columns: list[str]
    required: list[str]
    example: dict[str, object] = field(default_factory=dict)


TEMPLATES: dict[str, TemplateSpec] = {
    "companies": TemplateSpec(
        "companies",
        "organizations",
        ["code", "legal_name", "parent_code", "org_type", "address", "city", "country",
         "phone", "email", "tax_no", "default_currency", "bank_name", "bank_account",
         "iban", "swift_code"],
        ["code", "legal_name"],
        {"code": "IST", "legal_name": "UNO AgentAI Ltd", "org_type": "company",
         "city": "Istanbul", "country": "TR", "default_currency": "TRY"},
    ),
    "customers": TemplateSpec(
        "customers",
        "parties",
        ["company_name", "address", "city", "country", "phone", "email", "tax_no",
         "default_discount_percent", "default_payment_term_code"],
        ["company_name"],
        {"company_name": "Buyer GmbH", "city": "Berlin", "country": "DE"},
    ),
    "products": TemplateSpec(
        "products",
        "products_services",
        ["product_code", "product_description", "hs_code", "unit", "item_type",
         "product_tax_percent", "organization_code"],
        ["product_code"],
        {"product_code": "PRD-001", "product_description": "Industrial Sensor",
         "hs_code": "902519", "unit": "PCS", "item_type": "product"},
    ),
    "price_lists": TemplateSpec(
        "price_lists",
        "price_lists + price_list_items",
        ["price_list_code", "organization_code", "product_code", "currency",
         "unit_price", "min_quantity", "valid_from", "valid_to"],
        ["price_list_code", "product_code", "unit_price", "valid_from"],
        {"price_list_code": "PL-DE-2026", "product_code": "PRD-001", "currency": "EUR",
         "unit_price": 120.0, "valid_from": "2026-01-01"},
    ),
    "tax_rules": TemplateSpec(
        "tax_rules",
        "tax_rules",
        ["rule_type", "seller_country", "buyer_country", "product_code",
         "organization_code", "rate", "reason"],
        ["rule_type", "rate", "reason"],
        {"rule_type": "country_pair", "seller_country": "TR", "buyer_country": "TR",
         "rate": 20, "reason": "domestic_vat"},
    ),
    "payment_terms": TemplateSpec(
        "payment_terms",
        "payment_terms",
        ["code", "label", "is_default"],
        ["code", "label"],
        {"code": "ADV100", "label": "%100 payment in advance", "is_default": True},
    ),
    "docno_rules": TemplateSpec(
        "docno_rules",
        "docno_rules",
        ["organization_code", "document_type", "template", "counter_scope"],
        ["organization_code", "document_type", "template", "counter_scope"],
        {"organization_code": "IST", "document_type": "proforma_invoice",
         "template": "PRF-{SELLER_CODE}-{YEAR}-{SEQ:5}", "counter_scope": "per_seller_annual"},
    ),
    "employees": TemplateSpec(
        "employees",
        "parties (person)",
        ["person_name", "email", "phone", "tax_no", "external_ref"],
        ["person_name"],
        {"person_name": "Murat Demir", "email": "murat@example.com"},
    ),
}


def generate_template(template_type: str, path: Path | str) -> Path:
    """Write a single fixed template .xlsx (header row + one example row)."""
    spec = TEMPLATES[template_type]
    wb = Workbook()
    ws = wb.active
    ws.title = template_type
    ws.append(spec.columns)
    ws.append([spec.example.get(col, "") for col in spec.columns])
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def generate_all(directory: Path | str) -> list[Path]:
    """Write every template into ``directory`` as ``<template_type>.xlsx``."""
    directory = Path(directory)
    return [generate_template(t, directory / f"{t}.xlsx") for t in TEMPLATES]
