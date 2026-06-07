"""Proforma Invoice — rule evaluation.

Source of truth:
    template/docs/CONTRACT_v1.md §9 (tax precedence), §10 (document number)
    template/docs/modules/PROFORMA_v1.md §8.4 (tax), §9 (document number)

For v1 first implementation sprint these rules are encoded with sensible
defaults inline. The contract is wired so a future revision can load
rules from DB or imported template files without breaking the engine
API. The v1.1 plan is documented as TODOs at the relevant call sites.

Tax precedence order (top wins) per CONTRACT_v1.md §9:
    1. line_override        (caller explicitly set ``tax_percent`` on the line)
    2. product_specific     (Excel product row carries its own tax %)
    3. country_pair         (seller country + buyer country → table lookup)
    4. seller_default       (last-resort fallback per seller)

Document number template syntax per CONTRACT_v1.md §10:
    Supported tokens: {SELLER_CODE}, {YEAR}, {MONTH}, {SEQ:N}, {RANDOM:N}
    Counter persistence: SQLite local file with atomic increments.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────────
# Tax precedence
# ─────────────────────────────────────────────────────────────────────


@dataclass
class TaxDecision:
    """Result of one line's tax resolution."""

    percent: float
    reason: str
    precedence_source: str  # "line_override" | "product_specific" | "country_pair" | "seller_default"


# v1 default country-pair rules — sample seed entries only. In v1.1 these
# load from an imported tax rules template file (see PROFORMA_v1.md §6.2
# item 4). The list is intentionally short; resolve_tax() raises an
# explicit error for any same-country sale missing from the table so a
# silent 0% never happens for an unconfigured domestic case.
_DEFAULT_COUNTRY_PAIR_RULES: dict[str, tuple[float, str]] = {
    # Domestic — Turkey
    "TR-TR": (20.0, "domestic_vat"),
    # Domestic — Germany
    "DE-DE": (19.0, "domestic_vat"),
    # Export from TR to EU (sample DE entry; v1.1 broadens this)
    "TR-DE": (0.0, "export_zero_vat"),
}


class MissingTaxRuleError(Exception):
    """Raised when a same-country sale has no configured VAT rate.

    Contract reference: PROFORMA_v1.md §8.4
    ("If tax data is missing and no valid fallback exists, the engine
    should return a review/error state instead of silently guessing.")

    Same-country sales must apply that country's domestic VAT per the
    spec. If the rate table does not carry an entry for the country,
    that is a data-configuration gap on the admin side — not a fall-
    through to zero.
    """

    def __init__(self, seller_country: str, buyer_country: str) -> None:
        self.seller_country = seller_country
        self.buyer_country = buyer_country
        super().__init__(
            f"No domestic VAT rate configured for {seller_country}-{buyer_country}. "
            "Same-country sales require a domestic rate; load the tax rules "
            "data file or add an explicit country-pair entry."
        )


def resolve_tax(
    *,
    line_override_percent: Optional[float],
    product_specific_percent: Optional[float] = None,
    seller_country: str,
    buyer_country: str,
    country_pair_rules: Optional[dict[str, tuple[float, str]]] = None,
) -> TaxDecision:
    """Apply the locked precedence chain and return the chosen rate + reason.

    Resolution order per CONTRACT_v1.md §9 (top wins):
        1. line_override
        2. product_specific
        3. country_pair
        4. (v1: same-country with no rule raises ``MissingTaxRuleError``;
            cross-country with no rule defaults to 0% export with the reason
            ``export_zero_vat_assumed``. v1.1 introduces a true seller_default
            sourced from the imported sellers data file.)

    Args:
        line_override_percent: Value the caller put on the line (``None`` if absent).
        product_specific_percent: Per-product override loaded from product data
            (``None`` if absent). Will be wired into the engine once data_loader
            exposes product-level tax data.
        seller_country: ISO 3166-1 alpha-2 code of seller.
        buyer_country: ISO 3166-1 alpha-2 code of buyer.
        country_pair_rules: Optional rules mapping
            ``"{seller_country}-{buyer_country}" -> (rate, reason)``.
            Defaults to the v1 hardcoded set.

    Returns:
        ``TaxDecision`` with rate, reason, and the precedence source that won.

    Raises:
        MissingTaxRuleError: Same-country sale with no rule available.
    """
    if line_override_percent is not None:
        return TaxDecision(
            percent=float(line_override_percent),
            reason="line_override",
            precedence_source="line_override",
        )

    if product_specific_percent is not None:
        return TaxDecision(
            percent=float(product_specific_percent),
            reason="product_specific",
            precedence_source="product_specific",
        )

    rules = country_pair_rules or _DEFAULT_COUNTRY_PAIR_RULES
    seller_cc = seller_country.upper()
    buyer_cc = buyer_country.upper()
    key = f"{seller_cc}-{buyer_cc}"
    if key in rules:
        rate, reason = rules[key]
        return TaxDecision(
            percent=float(rate),
            reason=reason,
            precedence_source="country_pair",
        )

    # Same-country sale with no rule = misconfiguration, not a silent zero.
    # Caller (engine.py) translates this into an execution_error response.
    if seller_cc == buyer_cc:
        raise MissingTaxRuleError(seller_cc, buyer_cc)

    # Cross-country sale with no explicit rule = default export 0%,
    # surfaced with a distinct reason so the caller can attach a warning
    # advising the admin to load an explicit rule when nuance matters
    # (intra-EU reverse charge, non-EU export, etc.).
    return TaxDecision(
        percent=0.0,
        reason="export_zero_vat_assumed",
        precedence_source="seller_default",
    )


# ─────────────────────────────────────────────────────────────────────
# Document number generation
# ─────────────────────────────────────────────────────────────────────


# v1 default template. In v1.1 this loads from the doc-numbering template
# file imported by the admin (see PROFORMA_v1.md §6.2 item 6).
DEFAULT_DOC_NUMBER_TEMPLATE: str = "PRF-{SELLER_CODE}-{YEAR}-{SEQ:5}"
DEFAULT_COUNTER_SCOPE: str = "per_seller_annual"


def _resolve_counter_db_path() -> Path:
    """Locate the SQLite counter store.

    Default path: ``./var/counters.db`` relative to the python-erp repo
    root. Callers may override via ``ERP_ENGINE_COUNTER_DB`` env var when
    we wire that in v1.1.
    """
    # Repo root is two parents above this file (src/erp_engine/modules/proforma).
    repo_root = Path(__file__).resolve().parents[4]
    var_dir = repo_root / "var"
    var_dir.mkdir(parents=True, exist_ok=True)
    return var_dir / "counters.db"


def _ensure_counter_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS doc_counter (
            scope_key   TEXT PRIMARY KEY,
            current_seq INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def _next_seq(scope_key: str, db_path: Optional[Path] = None) -> int:
    """Atomically increment the counter for the given scope and return it.

    The contract calls for atomic increments per CONTRACT_v1.md §10.
    """
    path = db_path or _resolve_counter_db_path()
    with sqlite3.connect(path, isolation_level=None) as conn:
        _ensure_counter_schema(conn)
        # BEGIN IMMEDIATE blocks other writers, providing the atomic step.
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT current_seq FROM doc_counter WHERE scope_key = ?",
            (scope_key,),
        ).fetchone()
        if row is None:
            new_seq = 1
            conn.execute(
                "INSERT INTO doc_counter (scope_key, current_seq) VALUES (?, ?)",
                (scope_key, new_seq),
            )
        else:
            new_seq = row[0] + 1
            conn.execute(
                "UPDATE doc_counter SET current_seq = ? WHERE scope_key = ?",
                (new_seq, scope_key),
            )
        conn.execute("COMMIT")
        return new_seq


def _build_scope_key(
    counter_scope: str,
    seller_code: str,
    issue_date: date,
) -> str:
    """Return the SQLite key used to namespace the counter."""
    scope = counter_scope.strip().lower()
    if scope == "per_seller_annual":
        return f"{seller_code}|{issue_date.year}"
    if scope == "per_seller_monthly":
        return f"{seller_code}|{issue_date.year}-{issue_date.month:02d}"
    if scope == "global_annual":
        return f"GLOBAL|{issue_date.year}"
    # Conservative default: per_seller_annual semantics.
    return f"{seller_code}|{issue_date.year}"


def generate_document_number(
    *,
    seller_code: str,
    issue_date: date,
    template: str = DEFAULT_DOC_NUMBER_TEMPLATE,
    counter_scope: str = DEFAULT_COUNTER_SCOPE,
    db_path: Optional[Path] = None,
) -> str:
    """Render the document number template against the current counter state.

    Supported tokens per CONTRACT_v1.md §10:
        ``{SELLER_CODE}``, ``{YEAR}``, ``{MONTH}``, ``{SEQ:N}``

    ``{RANDOM:N}`` is intentionally not implemented yet — the contract
    lists it as "if later enabled".
    """
    scope_key = _build_scope_key(counter_scope, seller_code, issue_date)
    seq = _next_seq(scope_key, db_path=db_path)

    rendered = template
    rendered = rendered.replace("{SELLER_CODE}", seller_code)
    rendered = rendered.replace("{YEAR}", str(issue_date.year))
    rendered = rendered.replace("{MONTH}", f"{issue_date.month:02d}")

    # {SEQ:N} — N-wide zero-padded sequence
    if "{SEQ:" in rendered:
        start = rendered.index("{SEQ:")
        end = rendered.index("}", start)
        token = rendered[start : end + 1]  # e.g. "{SEQ:5}"
        try:
            width = int(token[len("{SEQ:") : -1])
        except ValueError:
            width = 5
        rendered = rendered.replace(token, f"{seq:0{width}d}")
    elif "{SEQ}" in rendered:
        rendered = rendered.replace("{SEQ}", str(seq))

    return rendered
