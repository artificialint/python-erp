"""Data file loaders — Excel (XLSX) and CSV.

Source of truth:
    template/docs/modules/PROFORMA_v1.md §6 (data sources, file-format rule)
    template/docs/CONTRACT_v1.md §14 (template/data contracts)

Responsibility boundary (v1):
    The runtime engine ``create_proforma`` accepts a payload whose
    party (seller, buyer, ship_to) and product line fields are already
    resolved by the caller (PHP shell or other adapter). The engine
    does not open a DB connection or read Excel files at request time
    in v1 — it focuses on validation, rule application, calculation,
    and result assembly.

    The loaders in this file serve the *bulk import* path:
    Excel/CSV → row validation → DB write. That path activates once
    the PHP admin panel wires the "Upload Excel" action. In v2 the
    engine may grow an alternative DB-backed resolution mode for
    callers that prefer to delegate the lookup; the entry-point
    signature and contract stay stable across that transition.

This module therefore exposes stubs that document the column contracts
each fixed-template file is expected to honour. Real loaders land in a
follow-up packet alongside the PHP admin form.

Fixed-template columns (v1):

    sellers.xlsx / sellers.csv
        company_code, company_name, address, city, country,
        phone, email, tax_no, currency, bank_name, bank_account,
        iban, swift_code

    customers.xlsx / customers.csv
        company_name, address, city, country, phone, email, tax_no,
        default_discount_percent, default_payment_term

    products.xlsx / products.csv
        product_code, product_description, hs_code, unit, unit_price,
        currency, product_tax_percent

    tax_rules.xlsx / tax_rules.csv
        seller_country, buyer_country, rate, reason

    payment_terms.xlsx / payment_terms.csv
        code, label, default

    docno_rules.xlsx / docno_rules.csv
        seller_code, template, counter_scope
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_sellers(path: Path) -> list[dict[str, Any]]:
    """Load seller entities from a fixed-template file. Not implemented in v1."""
    raise NotImplementedError(
        "load_sellers stub — landed alongside the PHP 'Upload Excel' wiring."
    )


def load_customers(path: Path) -> list[dict[str, Any]]:
    """Load customer entities from a fixed-template file. Not implemented in v1."""
    raise NotImplementedError(
        "load_customers stub — landed alongside the PHP 'Upload Excel' wiring."
    )


def load_products(path: Path) -> list[dict[str, Any]]:
    """Load products from a fixed-template file. Not implemented in v1."""
    raise NotImplementedError(
        "load_products stub — landed alongside the PHP 'Upload Excel' wiring."
    )


def load_tax_rules(path: Path) -> dict[str, tuple[float, str]]:
    """Load tax rules keyed by ``"seller-buyer"``. Not implemented in v1."""
    raise NotImplementedError(
        "load_tax_rules stub — landed alongside the PHP 'Upload Excel' wiring."
    )


def load_payment_terms(path: Path) -> list[dict[str, Any]]:
    """Load payment terms from a fixed-template file. Not implemented in v1."""
    raise NotImplementedError(
        "load_payment_terms stub — landed alongside the PHP 'Upload Excel' wiring."
    )


def load_docno_rules(path: Path) -> list[dict[str, Any]]:
    """Load document numbering rules. Not implemented in v1."""
    raise NotImplementedError(
        "load_docno_rules stub — landed alongside the PHP 'Upload Excel' wiring."
    )
