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

import os
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

# A4 amendment (2026-07-05) — customer-anchored numbering.
# The buyer's customer_no is a human-readable LABEL; the legal SEQ stays
# seller-scoped and gapless. This scope adds document_type + month; every
# scope is tenant-prefixed for multi-tenant isolation (missing tenant_key
# → legacy un-prefixed key). See docs/CONTRACT_A4_CUSTOMER_NUMBERING.md.
SCOPE_PER_SELLER_DOCTYPE_MONTHLY: str = "per_seller_doctype_monthly"

# A6 amendment (2026-07-10) — canonical lifecycle numbering.
# One shared ledger per (tenant | seller | customer | month): the base
# sequence is born when the first Quotation is created and INHERITED by the
# Proforma/Commercial derived from it — document_type is deliberately NOT part
# of this scope key (Q/P/C collapse onto one base; only the rendered leading
# {DOCUMENT_TYPE_CODE} digit differs). Additive: the A4 scopes above keep
# working unchanged. See docs/CONTRACT_A6_LIFECYCLE_NUMBERING.md.
SCOPE_PER_SELLER_CUSTOMER_MONTHLY: str = "per_seller_customer_monthly"

# A6 — the canonical document-family digit rendered by {DOCUMENT_TYPE_CODE}.
DOCUMENT_TYPE_CODES: dict = {
    "quotation": "1",
    "proforma_invoice": "2",
    "commercial_invoice": "3",
}


class CustomerNoRequiredError(Exception):
    """A numbering template references ``{CUSTOMER_NO}`` but the payload
    carries no ``buyer.customer_no``. The engine surfaces this as a
    field-targeted ``customer_no_required`` validation error (A4). Raised
    BEFORE the counter is touched, so a missing label never burns a
    sequence number."""


class DocumentTypeCodeRequiredError(Exception):
    """A numbering template references ``{DOCUMENT_TYPE_CODE}`` but no
    (known) ``document_type`` was supplied (A6). Unreachable from the engine
    envelope path — ``header.document_type`` is a schema Literal with a
    default — so this guards direct library callers only. Raised BEFORE the
    counter is touched."""


def _resolve_counter_db_path() -> Path:
    """Locate the SQLite counter store.

    Resolution order (first match wins):
        1. ``ERP_ENGINE_COUNTER_DB`` env var — explicit absolute path.
           Wired in Packet 3 (2026-06-07) so the prod container can point
           the counter at a named-volume-backed path
           (``/var/erp-engine/counters.db``) and survive image rebuilds.
        2. Default: ``<python-erp repo root>/var/counters.db`` — used by
           local dev (Windows: ``C:\\xampp\\htdocs\\python-erp\\var\\counters.db``).

    The directory is created if missing; the file itself is created on
    first connect by sqlite3.
    """
    env_override = os.environ.get("ERP_ENGINE_COUNTER_DB", "").strip()
    if env_override:
        path = Path(env_override)
        # Create the parent dir if it doesn't already exist. Inside the
        # prod container this is /var/erp-engine — pre-created by the
        # Dockerfile + mounted as a named volume — so this is a no-op
        # there. The mkdir is a courtesy for misconfigured environments.
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    # Repo root is four parents above this file
    # (src/erp_engine/modules/proforma/rules.py → python-erp/).
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
    *,
    document_type: Optional[str] = None,
    customer_no: Optional[object] = None,
    tenant_key: Optional[str] = None,
) -> str:
    """Return the SQLite key used to namespace the counter.

    A4 (2026-07-05): every scope is tenant-prefixed for multi-tenant
    isolation — two tenants that reuse the same ``seller_code`` keep
    independent sequences. A missing ``tenant_key`` falls back to the
    legacy un-prefixed key so existing single-tenant counters are
    undisturbed (backward compatibility). ``document_type`` participates
    only in ``per_seller_doctype_monthly``.

    A6 (2026-07-10): ``per_seller_customer_monthly`` keys on the CUSTOMER
    instead of the document type — Q/P/C share one ledger (the lifecycle
    base). ``customer_no`` is required for that scope (raises
    ``CustomerNoRequiredError`` before any counter is touched).
    """
    scope = counter_scope.strip().lower()
    prefix = f"{tenant_key}|" if tenant_key not in (None, "") else ""
    year = issue_date.year
    month = f"{issue_date.month:02d}"
    if scope == "per_seller_annual":
        return f"{prefix}{seller_code}|{year}"
    if scope == "per_seller_monthly":
        return f"{prefix}{seller_code}|{year}-{month}"
    if scope == SCOPE_PER_SELLER_DOCTYPE_MONTHLY:
        return f"{prefix}{seller_code}|{document_type or ''}|{year}-{month}"
    if scope == SCOPE_PER_SELLER_CUSTOMER_MONTHLY:
        # A6: document_type deliberately NOT in the key — Q/P/C share the base.
        if customer_no in (None, ""):
            raise CustomerNoRequiredError(
                "counter_scope per_seller_customer_monthly requires buyer.customer_no"
            )
        return f"{prefix}{seller_code}|{customer_no}|{year}-{month}"
    if scope == "global_annual":
        return f"{prefix}GLOBAL|{year}"
    # Conservative default: per_seller_annual semantics.
    return f"{prefix}{seller_code}|{year}"


def generate_document_number(
    *,
    seller_code: str,
    issue_date: date,
    template: str = DEFAULT_DOC_NUMBER_TEMPLATE,
    counter_scope: str = DEFAULT_COUNTER_SCOPE,
    customer_no: Optional[object] = None,
    document_type: Optional[str] = None,
    tenant_key: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> str:
    """Render the document number template against the current counter state.

    Supported tokens per CONTRACT_v1.md §10 (A4 adds the first three,
    A6 adds ``{DOCUMENT_TYPE_CODE}``):
        ``{DOCUMENT_TYPE_CODE}``, ``{CUSTOMER_NO}``, ``{YY}``, ``{MM}``,
        ``{SELLER_CODE}``, ``{YEAR}``, ``{MONTH}``, ``{SEQ:N}``

    ``{RANDOM:N}`` is intentionally not implemented yet — the contract
    lists it as "if later enabled".

    A4 (2026-07-05): ``customer_no`` is a human-readable LABEL rendered
    into ``{CUSTOMER_NO}``; the legal ``{SEQ}`` stays seller-scoped and
    gapless (never per-buyer). ``document_type`` + ``tenant_key`` feed the
    counter scope key. If the template uses ``{CUSTOMER_NO}`` but no
    ``customer_no`` is supplied, ``CustomerNoRequiredError`` is raised
    BEFORE the counter is touched (no sequence is burned).
    """
    # A4 guard — refuse to render a blank customer label. Runs before the
    # counter is incremented so a missing label never consumes a sequence.
    if "{CUSTOMER_NO}" in template and customer_no in (None, ""):
        raise CustomerNoRequiredError(
            "template references {CUSTOMER_NO} but buyer.customer_no is missing"
        )
    # A6 guard — same principle: an unrenderable {DOCUMENT_TYPE_CODE} must be
    # rejected BEFORE the counter increments (no sequence is ever burned).
    if "{DOCUMENT_TYPE_CODE}" in template and not DOCUMENT_TYPE_CODES.get(
        (document_type or "").strip().lower()
    ):
        raise DocumentTypeCodeRequiredError(
            "template references {DOCUMENT_TYPE_CODE} but document_type is "
            f"missing or unknown: {document_type!r}"
        )

    scope_key = _build_scope_key(
        counter_scope,
        seller_code,
        issue_date,
        document_type=document_type,
        customer_no=customer_no,
        tenant_key=tenant_key,
    )
    seq = _next_seq(scope_key, db_path=db_path)

    # Token render is shared with render_document_number (A5) — one source.
    return _render_number_tokens(
        template,
        seq,
        seller_code=seller_code,
        customer_no=customer_no,
        issue_date=issue_date,
        document_type=document_type,
    )


def _render_number_tokens(
    template: str,
    seq: int,
    *,
    seller_code: str = "",
    customer_no: Optional[object] = None,
    issue_date: date,
    document_type: Optional[str] = None,
) -> str:
    """Render document-number tokens from a given ``seq``. Pure formatting —
    NO counter, NO DB. Single source of truth for both the allocate path
    (``generate_document_number``) and the render-only path
    (``render_document_number``, A5).

    Supported tokens: ``{DOCUMENT_TYPE_CODE} {SELLER_CODE} {CUSTOMER_NO}
    {YEAR} {YY} {MONTH} {MM} {SEQ:N}``. If the template references
    ``{CUSTOMER_NO}`` but none is supplied → ``CustomerNoRequiredError``;
    ``{DOCUMENT_TYPE_CODE}`` with a missing/unknown ``document_type`` →
    ``DocumentTypeCodeRequiredError`` (A6; no silent blank either way).
    """
    if "{CUSTOMER_NO}" in template and customer_no in (None, ""):
        raise CustomerNoRequiredError(
            "template references {CUSTOMER_NO} but buyer.customer_no is missing"
        )
    rendered = template
    # A6 — canonical document-family digit (1=quotation, 2=proforma, 3=commercial).
    if "{DOCUMENT_TYPE_CODE}" in rendered:
        type_code = DOCUMENT_TYPE_CODES.get((document_type or "").strip().lower())
        if not type_code:
            raise DocumentTypeCodeRequiredError(
                "template references {DOCUMENT_TYPE_CODE} but document_type is "
                f"missing or unknown: {document_type!r}"
            )
        rendered = rendered.replace("{DOCUMENT_TYPE_CODE}", type_code)
    rendered = rendered.replace("{SELLER_CODE}", seller_code)
    if customer_no not in (None, ""):
        rendered = rendered.replace("{CUSTOMER_NO}", str(customer_no))
    rendered = rendered.replace("{YEAR}", str(issue_date.year))
    rendered = rendered.replace("{YY}", f"{issue_date.year % 100:02d}")
    rendered = rendered.replace("{MONTH}", f"{issue_date.month:02d}")
    rendered = rendered.replace("{MM}", f"{issue_date.month:02d}")

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


def render_document_number(
    template: str,
    *,
    seq: int,
    seller_code: str = "",
    customer_no: Optional[object] = None,
    issue_date: date,
    document_type: Optional[str] = None,
) -> str:
    """A5 amendment (2026-07-05) — render a document number from a
    CALLER-SUPPLIED sequence, with NO counter side effect.

    The online issue path (INV-4) allocates the legal sequence in the MySQL
    ledger transaction and passes it here purely for formatting, so numbering
    and document persistence stay atomic (the engine's SQLite counter is not
    used online). Standalone/desktop keeps ``generate_document_number`` (which
    owns the SQLite counter). Token logic is shared via
    ``_render_number_tokens`` — one render implementation, two entry points.

    A6 (2026-07-10): ``document_type`` is now ALSO a render input — it feeds
    the ``{DOCUMENT_TYPE_CODE}`` leading digit (1=quotation, 2=proforma_invoice,
    3=commercial_invoice). For templates without that token it remains inert
    (pre-A6 behavior unchanged).
    """
    return _render_number_tokens(
        template,
        seq,
        seller_code=seller_code,
        customer_no=customer_no,
        issue_date=issue_date,
        document_type=document_type,
    )
