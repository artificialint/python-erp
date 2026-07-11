"""Behavioral tests for the proforma engine v1.

Source of truth for the contract under test:
    template/docs/CONTRACT_v1.md
    template/docs/modules/PROFORMA_v1.md

Scope per Codex implementation instruction:
    - one minimal valid payload         → status == "ok"
    - one missing-quantity validation   → status == "validation_error"
    - one export zero-VAT case          → tax_reason == "export_zero_vat"

These tests exercise the request → engine → response contract end to end.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from erp_engine.modules.proforma import create_proforma
from erp_engine.modules.proforma.rules import (
    _build_scope_key,
    _ensure_counter_schema,
    CustomerNoRequiredError,
    DocumentTypeCodeRequiredError,
    generate_document_number,
    render_document_number,
)


@pytest.fixture()
def isolated_counter_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the document-number counter to a per-test SQLite file.

    Without this the test would write to the shared ``var/counters.db``
    file at the repo root and leak counter state across runs.
    """
    db_path = tmp_path / "counters.db"
    monkeypatch.setattr(
        "erp_engine.modules.proforma.rules._resolve_counter_db_path",
        lambda: db_path,
    )
    return db_path


def _minimal_valid_payload(*, buyer_country: str = "TR") -> dict:
    """Build a minimal valid request envelope.

    All required fields per the contract are populated with deterministic
    values so the test assertions are stable.
    """
    return {
        "schema_version": "contract_v1",
        "module": "proforma_invoice",
        "request_id": "req_test_0001",
        "context": {
            "source": "test_harness",
            "actor_type": "system",
            "actor_id": 1,
            "customer_id": 1,
            "tenant_slug": "pilot-ltd",
            "locale": "tr-TR",
            "timezone": "Europe/Istanbul",
        },
        "payload": {
            "header": {
                "document_type": "proforma_invoice",
                "issue_date": "2026-06-07",
                "document_no": None,
                "currency": "TRY",
                "valid_until": None,
                "buyer_po_reference": None,
            },
            "seller": {
                "company_code": "IST",
                "company_name": "UNO AgentAI Ltd",
                "address": "Levent Mah.",
                "city": "Istanbul",
                "country": "TR",
                "phone": "+90 212 000 00 00",
                "email": "sales@example.com",
                "tax_no": "1234567890",
            },
            "buyer": {
                "company_name": "Test Buyer Ltd",
                "address": "Atatürk Cad. 1",
                "city": "Ankara" if buyer_country == "TR" else "Berlin",
                "country": buyer_country,
                "phone": "+90 312 000 00 00",
                "email": "buyer@example.com",
                "tax_no": "9876543210",
                "source": "db_lookup",
            },
            "ship_to": {
                "same_as_buyer": True,
                "company_name": None,
                "address": None,
                "city": None,
                "country": None,
                "phone": None,
                "email": None,
                "source": "buyer_copy",
            },
            "line_items": [
                {
                    "line_no": 1,
                    "product_code": "PRD-001",
                    "product_description": "Industrial Sensor",
                    "hs_code": "902519",
                    "quantity": 10,
                    "unit": "PCS",
                    "unit_price": 100.0,
                    "discount_percent": 0.0,
                    "tax_percent": None,
                    "line_notes": "",
                }
            ],
            "terms": {
                "freight_cost": 0.0,
                "delivery_term": "EXW",
                "delivery_location": "Istanbul Warehouse",
                "delivery_date": None,
                "payment_term": "%100 payment in advance",
            },
            "banking": {
                "bank_name": None,
                "bank_account": None,
                "iban": None,
                "swift_code": None,
            },
            "notes": {
                "notes_to_buyer": None,
                "internal_notes": None,
            },
        },
    }


def test_minimal_valid_payload_yields_ok_response(isolated_counter_db: Path) -> None:
    """A complete and valid request returns status == 'ok' with a full result."""
    payload = _minimal_valid_payload()

    response = create_proforma(payload)

    assert response["status"] == "ok"
    assert response["request_id"] == "req_test_0001"
    assert response["module"] == "proforma_invoice"
    assert response["schema_version"] == "contract_v1"
    assert response["errors"] == []
    assert response["result"] is not None

    result = response["result"]
    # Document section was filled by the engine
    assert result["document"]["document_no"].startswith("PRF-IST-2026-")
    assert result["document"]["currency"] == "TRY"
    assert result["document"]["valid_until"] == "2026-07-07"  # issue_date + 30

    # Line totals computed deterministically (10 * 100 = 1000, then 20% VAT)
    assert len(result["line_items"]) == 1
    line = result["line_items"][0]
    assert line["line_total"] == pytest.approx(1200.0)
    assert line["tax_percent"] == pytest.approx(20.0)
    assert line["tax_reason"] == "domestic_vat"

    # Totals block reflects the single line
    totals = result["totals"]
    assert totals["subtotal_amount"] == pytest.approx(1000.0)
    assert totals["tax_amount"] == pytest.approx(200.0)
    assert totals["grand_total"] == pytest.approx(1200.0)

    # Calculation trace reports which precedence layer fired
    trace = result["calculation_trace"]
    assert trace["tax_precedence_applied"] == ["country_pair"]
    assert trace["tax_reason_summary"] == ["domestic_vat"]


def test_missing_quantity_blocks_submission(isolated_counter_db: Path) -> None:
    """A line with zero quantity must produce a validation_error response."""
    payload = _minimal_valid_payload()
    payload["payload"]["line_items"][0]["quantity"] = 0

    response = create_proforma(payload)

    assert response["status"] == "validation_error"
    assert response["result"] is None
    assert response["errors"], "expected at least one validation error"

    # Pydantic field validator carries the field path; we accept either the
    # full `payload.line_items[0].quantity` form or any substring match
    # because the exact error code depends on Pydantic's translation layer.
    quantity_errors = [
        err for err in response["errors"] if "quantity" in (err.get("field") or "")
    ]
    assert quantity_errors, "expected a field-targeted error on line_items.quantity"


def test_export_sale_applies_zero_vat(isolated_counter_db: Path) -> None:
    """TR → DE sale must apply 0% VAT with the export reason."""
    payload = _minimal_valid_payload(buyer_country="DE")

    response = create_proforma(payload)

    assert response["status"] == "ok"
    line = response["result"]["line_items"][0]
    assert line["tax_percent"] == pytest.approx(0.0)
    assert line["tax_reason"] == "export_zero_vat"
    assert line["tax_amount"] == pytest.approx(0.0)
    # Grand total equals the subtotal because tax is zero and no freight/discount
    assert response["result"]["totals"]["grand_total"] == pytest.approx(1000.0)

    trace = response["result"]["calculation_trace"]
    assert "country_pair" in trace["tax_precedence_applied"]
    assert "export_zero_vat" in trace["tax_reason_summary"]


def test_same_country_with_no_rule_returns_execution_error(
    isolated_counter_db: Path,
) -> None:
    """A same-country sale lacking a configured rate must NOT silently zero out.

    Spec: PROFORMA_v1.md §8.4 — "If tax data is missing and no valid
    fallback exists, the engine should return a review/error state
    instead of silently guessing." For v1 the rule table does not
    carry FR-FR, so an FR seller selling to an FR buyer is exactly
    the "domestic but unknown rate" case Codex flagged.
    """
    payload = _minimal_valid_payload(buyer_country="FR")
    # Mutate the seller country to match the buyer so this becomes a
    # same-country sale with no rule in the default table.
    payload["payload"]["seller"]["country"] = "FR"
    payload["payload"]["buyer"]["city"] = "Paris"

    response = create_proforma(payload)

    assert response["status"] == "execution_error"
    assert response["result"] is None
    assert response["errors"], "expected at least one execution error"
    codes = [err.get("code") for err in response["errors"]]
    assert "missing_tax_rule" in codes, codes


def test_unknown_export_pair_returns_zero_with_warning(
    isolated_counter_db: Path,
) -> None:
    """A cross-country sale lacking an explicit rule defaults to 0% + warning.

    The intent: an FR seller selling to a US buyer is an export with no
    configured rule in the default table. The engine must NOT silently
    treat it as domestic; it must apply 0% AND surface a warning so the
    admin sees the implicit assumption.
    """
    payload = _minimal_valid_payload(buyer_country="US")
    payload["payload"]["seller"]["country"] = "FR"
    payload["payload"]["buyer"]["city"] = "New York"

    response = create_proforma(payload)

    assert response["status"] == "ok"
    line = response["result"]["line_items"][0]
    assert line["tax_percent"] == pytest.approx(0.0)
    assert line["tax_reason"] == "export_zero_vat_assumed"

    warning_codes = [w.get("code") for w in response.get("warnings", [])]
    assert "tax_rule_assumed_export_zero" in warning_codes, warning_codes


def test_counter_db_atomic_increment_smoke(isolated_counter_db: Path) -> None:
    """Direct probe: the SQLite counter increments sequentially per scope."""
    # Pre-create the schema so we can call the helper in isolation
    with sqlite3.connect(isolated_counter_db) as conn:
        _ensure_counter_schema(conn)

    from datetime import date

    seller_code = "IST"
    issue_date = date(2026, 6, 7)
    scope_key = _build_scope_key("per_seller_annual", seller_code, issue_date)
    assert scope_key == "IST|2026"

    first = generate_document_number(
        seller_code=seller_code,
        issue_date=issue_date,
        db_path=isolated_counter_db,
    )
    second = generate_document_number(
        seller_code=seller_code,
        issue_date=issue_date,
        db_path=isolated_counter_db,
    )
    assert first == "PRF-IST-2026-00001"
    assert second == "PRF-IST-2026-00002"


def test_counter_db_path_honors_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ERP_ENGINE_COUNTER_DB env var redirects the counter store.

    Wired in Packet 3 (2026-06-07) so the prod container can put the
    counter SQLite file on a named-volume-backed path that survives
    image rebuilds. The default path stays repo-relative; only the env
    override changes the location.
    """
    from erp_engine.modules.proforma.rules import _resolve_counter_db_path

    # Default behaviour — no env var set: falls back to repo-root/var.
    monkeypatch.delenv("ERP_ENGINE_COUNTER_DB", raising=False)
    default_path = _resolve_counter_db_path()
    assert default_path.name == "counters.db"
    assert default_path.parent.name == "var"

    # With env var set — the override path is returned and its parent
    # directory is created on the fly. We point at a nested path inside
    # tmp_path that does not yet exist so we exercise the mkdir branch.
    override = tmp_path / "container" / "erp-engine" / "counters.db"
    assert not override.parent.exists()
    monkeypatch.setenv("ERP_ENGINE_COUNTER_DB", str(override))

    resolved = _resolve_counter_db_path()
    assert resolved == override
    assert override.parent.is_dir(), "parent dir should be created"

    # Empty / whitespace env value must fall back to the default path
    # (defensive — protects against a misconfigured .env with a blank
    # value like `ERP_ENGINE_COUNTER_DB=`).
    monkeypatch.setenv("ERP_ENGINE_COUNTER_DB", "   ")
    blank_resolved = _resolve_counter_db_path()
    assert blank_resolved.name == "counters.db"
    assert blank_resolved.parent.name == "var"


# ─────────────────────────────────────────────────────────────────────
# A1 amendment — document_type variants (quotation / proforma / commercial)
# Contract change: CONTRACT_v1 §7.2/§11.2 + PROFORMA_v1 §5.1.
# module Literal, calculation logic, and numbering are unchanged by A1.
# ─────────────────────────────────────────────────────────────────────


def test_default_document_type_is_proforma_invoice(isolated_counter_db: Path) -> None:
    """The default document_type stays proforma_invoice and is echoed to the result."""
    payload = _minimal_valid_payload()

    response = create_proforma(payload)

    assert response["status"] == "ok"
    assert response["result"]["document"]["document_type"] == "proforma_invoice"


def test_quotation_document_type_accepted(isolated_counter_db: Path) -> None:
    """document_type='quotation' is accepted and propagated into the result."""
    payload = _minimal_valid_payload()
    payload["payload"]["header"]["document_type"] = "quotation"

    response = create_proforma(payload)

    assert response["status"] == "ok"
    assert response["result"]["document"]["document_type"] == "quotation"


def test_commercial_invoice_document_type_accepted(isolated_counter_db: Path) -> None:
    """document_type='commercial_invoice' is accepted and propagated into the result."""
    payload = _minimal_valid_payload()
    payload["payload"]["header"]["document_type"] = "commercial_invoice"

    response = create_proforma(payload)

    assert response["status"] == "ok"
    assert response["result"]["document"]["document_type"] == "commercial_invoice"


def test_invalid_document_type_rejected(isolated_counter_db: Path) -> None:
    """An unknown document_type fails the Literal and yields a validation_error."""
    payload = _minimal_valid_payload()
    payload["payload"]["header"]["document_type"] = "bogus_type"

    response = create_proforma(payload)

    assert response["status"] == "validation_error"
    assert response["result"] is None
    assert response["errors"], "expected a validation error for an unknown document_type"


# ─────────────────────────────────────────────────────────────────────
# A4 amendment — customer-anchored document numbering (2026-07-05)
# Principle: customer_no = human-readable LABEL; SEQ = seller-scoped legal
# ledger sequence (gapless, never per-buyer). Contract change:
# CONTRACT_v1 §10 (tokens {CUSTOMER_NO}/{YY}/{MM}, scope
# per_seller_doctype_monthly, tenant-prefixed keys) + §7.4 buyer.customer_no.
# ─────────────────────────────────────────────────────────────────────

A4_TEMPLATE = "{CUSTOMER_NO}{YY}{MM}{SEQ:3}"
A4_SCOPE = "per_seller_doctype_monthly"


def test_a4_legacy_prf_unchanged(isolated_counter_db: Path) -> None:
    """Legacy PRF template + per_seller_annual renders byte-identical (no new
    params passed) and the legacy scope key stays un-prefixed."""
    n1 = generate_document_number(
        seller_code="IST", issue_date=date(2026, 6, 7), db_path=isolated_counter_db
    )
    n2 = generate_document_number(
        seller_code="IST", issue_date=date(2026, 6, 7), db_path=isolated_counter_db
    )
    assert n1 == "PRF-IST-2026-00001"
    assert n2 == "PRF-IST-2026-00002"
    assert _build_scope_key("per_seller_annual", "IST", date(2026, 6, 7)) == "IST|2026"


def test_a4_customer_no_yy_mm_render(isolated_counter_db: Path) -> None:
    """{CUSTOMER_NO}/{YY}/{MM} render; default format → 1042607001."""
    num = generate_document_number(
        seller_code="IST",
        issue_date=date(2026, 7, 3),
        template=A4_TEMPLATE,
        counter_scope=A4_SCOPE,
        customer_no=104,
        document_type="invoice",
        tenant_key="18",
        db_path=isolated_counter_db,
    )
    assert num == "1042607001"  # 104 + YY 26 + MM 07 + SEQ 001


def test_a4_two_buyers_same_seller_month_share_sequence(
    isolated_counter_db: Path,
) -> None:
    """Q1 legal guarantee: SEQ is seller-scoped — two different buyers in the
    same seller/doctype/month continue the SAME ledger sequence (001, 002),
    never reset per buyer."""
    first = generate_document_number(
        seller_code="IST", issue_date=date(2026, 7, 3), template=A4_TEMPLATE,
        counter_scope=A4_SCOPE, customer_no=104, document_type="invoice",
        tenant_key="18", db_path=isolated_counter_db,
    )
    second = generate_document_number(
        seller_code="IST", issue_date=date(2026, 7, 20), template=A4_TEMPLATE,
        counter_scope=A4_SCOPE, customer_no=250, document_type="invoice",
        tenant_key="18", db_path=isolated_counter_db,
    )
    assert first == "1042607001"
    assert second == "2502607002"  # different buyer, SEQ continues in seller ledger


def test_a4_two_tenants_same_seller_isolated(isolated_counter_db: Path) -> None:
    """Q4 fix: tenant_key isolates counters even with an identical seller_code."""
    a = generate_document_number(
        seller_code="IST", issue_date=date(2026, 7, 3), template=A4_TEMPLATE,
        counter_scope=A4_SCOPE, customer_no=104, document_type="invoice",
        tenant_key="18", db_path=isolated_counter_db,
    )
    b = generate_document_number(
        seller_code="IST", issue_date=date(2026, 7, 3), template=A4_TEMPLATE,
        counter_scope=A4_SCOPE, customer_no=104, document_type="invoice",
        tenant_key="19", db_path=isolated_counter_db,
    )
    assert a == "1042607001"
    assert b == "1042607001"  # tenant 19 starts its own sequence (no collision)


def test_a4_month_rollover_resets_sequence(isolated_counter_db: Path) -> None:
    """Month is in the scope key → SEQ resets when the month rolls over."""
    jul = generate_document_number(
        seller_code="IST", issue_date=date(2026, 7, 31), template=A4_TEMPLATE,
        counter_scope=A4_SCOPE, customer_no=104, document_type="invoice",
        tenant_key="18", db_path=isolated_counter_db,
    )
    aug = generate_document_number(
        seller_code="IST", issue_date=date(2026, 8, 1), template=A4_TEMPLATE,
        counter_scope=A4_SCOPE, customer_no=104, document_type="invoice",
        tenant_key="18", db_path=isolated_counter_db,
    )
    assert jul == "1042607001"
    assert aug == "1042608001"  # SEQ resets in the new month


def test_a4_document_type_separates_counters(isolated_counter_db: Path) -> None:
    """Different document_type → independent counters within the same month."""
    inv = generate_document_number(
        seller_code="IST", issue_date=date(2026, 7, 3), template=A4_TEMPLATE,
        counter_scope=A4_SCOPE, customer_no=104, document_type="invoice",
        tenant_key="18", db_path=isolated_counter_db,
    )
    pro = generate_document_number(
        seller_code="IST", issue_date=date(2026, 7, 3), template=A4_TEMPLATE,
        counter_scope=A4_SCOPE, customer_no=104, document_type="proforma",
        tenant_key="18", db_path=isolated_counter_db,
    )
    assert inv.endswith("001")
    assert pro.endswith("001")  # separate document_type → separate ledger


def test_a4_missing_customer_no_raises_without_burning_sequence(
    isolated_counter_db: Path,
) -> None:
    """{CUSTOMER_NO} in template + no customer_no → CustomerNoRequiredError,
    and the counter is NOT consumed (the next valid call is still 001)."""
    with pytest.raises(CustomerNoRequiredError):
        generate_document_number(
            seller_code="IST", issue_date=date(2026, 7, 3), template=A4_TEMPLATE,
            counter_scope=A4_SCOPE, customer_no=None, document_type="invoice",
            tenant_key="18", db_path=isolated_counter_db,
        )
    ok = generate_document_number(
        seller_code="IST", issue_date=date(2026, 7, 3), template=A4_TEMPLATE,
        counter_scope=A4_SCOPE, customer_no=104, document_type="invoice",
        tenant_key="18", db_path=isolated_counter_db,
    )
    assert ok == "1042607001"  # sequence not burned by the failed attempt


def test_a4_envelope_missing_customer_no_validation_error(
    isolated_counter_db: Path,
) -> None:
    """Full envelope: A4 numbering config but no buyer.customer_no →
    status validation_error with code customer_no_required."""
    payload = _minimal_valid_payload()
    payload["payload"]["numbering"] = {"template": A4_TEMPLATE, "counter_scope": A4_SCOPE}
    response = create_proforma(payload)
    assert response["status"] == "validation_error"
    codes = [e["code"] for e in response["errors"]]
    assert "customer_no_required" in codes, response["errors"]


def test_a4_envelope_full_flow(isolated_counter_db: Path) -> None:
    """Full envelope: A4 numbering config + buyer.customer_no + tenant → the
    engine renders the customer-anchored number and echoes the scope."""
    payload = _minimal_valid_payload()  # issue_date 2026-06-07 → YY 26, MM 06
    payload["payload"]["numbering"] = {"template": A4_TEMPLATE, "counter_scope": A4_SCOPE}
    payload["payload"]["buyer"]["customer_no"] = 104
    payload["context"]["customer_id"] = 18
    response = create_proforma(payload)
    assert response["status"] == "ok", response.get("errors")
    assert response["result"]["document"]["document_no"] == "1042606001"
    assert response["result"]["calculation_trace"]["counter_scope"] == A4_SCOPE
    assert response["result"]["calculation_trace"]["document_number_template"] == A4_TEMPLATE


def test_a4_default_engine_numbering_still_prf(isolated_counter_db: Path) -> None:
    """Back-compat: a payload with no numbering block uses the engine default
    (PRF) — the product default lives caller-side, not in the engine."""
    payload = _minimal_valid_payload()
    response = create_proforma(payload)
    assert response["status"] == "ok"
    assert response["result"]["document"]["document_no"].startswith("PRF-IST-2026-")
    assert response["result"]["calculation_trace"]["counter_scope"] == "per_seller_annual"


# ─────────────────────────────────────────────────────────────────────
# A5 amendment — render-only numbering (2026-07-05)
# The online issue path (INV-4) allocates the legal seq in MySQL and passes it
# via payload.numbering.seq; the engine renders WITHOUT touching its counter.
# Standalone/desktop keeps generate_document_number (SQLite counter).
# ─────────────────────────────────────────────────────────────────────


def _counter_row_count(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    with sqlite3.connect(db_path) as conn:
        _ensure_counter_schema(conn)
        return conn.execute("SELECT COUNT(*) FROM doc_counter").fetchone()[0]


def test_a5_render_basic() -> None:
    """render_document_number formats a caller-supplied seq (no DB needed)."""
    out = render_document_number(
        "PRF-{SELLER_CODE}-{YEAR}-{SEQ:5}", seq=7, seller_code="IST", issue_date=date(2026, 1, 1)
    )
    assert out == "PRF-IST-2026-00007"


def test_a5_render_customer_anchored_seq1() -> None:
    out = render_document_number(
        A4_TEMPLATE, seq=1, customer_no=104, issue_date=date(2026, 7, 3)
    )
    assert out == "1042607001"  # 104 + YY26 + MM07 + SEQ001


def test_a5_render_seq_padding() -> None:
    assert render_document_number("{SEQ:5}", seq=42, issue_date=date(2026, 7, 3)) == "00042"
    assert render_document_number("{SEQ}", seq=42, issue_date=date(2026, 7, 3)) == "42"


def test_a5_render_missing_customer_no_raises() -> None:
    with pytest.raises(CustomerNoRequiredError):
        render_document_number(A4_TEMPLATE, seq=1, customer_no=None, issue_date=date(2026, 7, 3))


def test_a5_render_touches_no_counter(isolated_counter_db: Path) -> None:
    """The render-only path never writes to doc_counter."""
    for _ in range(3):
        render_document_number(A4_TEMPLATE, seq=5, customer_no=104, issue_date=date(2026, 7, 3))
    assert _counter_row_count(isolated_counter_db) == 0


def test_a5_render_parity_with_generate(isolated_counter_db: Path) -> None:
    """render_document_number(seq=S) == generate_document_number when it
    allocates that same S — proving one shared render implementation."""
    allocated = generate_document_number(
        seller_code="IST", issue_date=date(2026, 7, 3), template=A4_TEMPLATE,
        counter_scope=A4_SCOPE, customer_no=104, document_type="invoice",
        tenant_key="18", db_path=isolated_counter_db,
    )  # first alloc → seq 1
    rendered = render_document_number(
        A4_TEMPLATE, seq=1, customer_no=104, issue_date=date(2026, 7, 3)
    )
    assert allocated == rendered == "1042607001"


def test_a5_envelope_seq_renders_and_no_counter(isolated_counter_db: Path) -> None:
    """create_proforma with numbering.seq → renders that seq, counter untouched."""
    payload = _minimal_valid_payload()  # issue_date 2026-06-07 → YY26 MM06
    payload["payload"]["numbering"] = {"template": A4_TEMPLATE, "counter_scope": A4_SCOPE, "seq": 42}
    payload["payload"]["buyer"]["customer_no"] = 104
    response = create_proforma(payload)
    assert response["status"] == "ok", response.get("errors")
    assert response["result"]["document"]["document_no"] == "1042606042"
    assert _counter_row_count(isolated_counter_db) == 0  # render-only, no allocation


def test_a5_draft_still_bypasses_numbering(isolated_counter_db: Path) -> None:
    """The DRAFT brake still wins over numbering.seq — no number, no counter."""
    payload = _minimal_valid_payload()
    payload["payload"]["header"]["document_no"] = "DRAFT"
    payload["payload"]["numbering"] = {"template": A4_TEMPLATE, "seq": 9}
    payload["payload"]["buyer"]["customer_no"] = 104
    response = create_proforma(payload)
    assert response["status"] == "ok"
    assert response["result"]["document"]["document_no"] == "DRAFT"
    assert _counter_row_count(isolated_counter_db) == 0


def test_a5_legacy_generate_unchanged(isolated_counter_db: Path) -> None:
    """No seq → allocate path unchanged (A4/legacy behavior)."""
    n1 = generate_document_number(
        seller_code="IST", issue_date=date(2026, 6, 7), db_path=isolated_counter_db
    )
    assert n1 == "PRF-IST-2026-00001"
    assert _counter_row_count(isolated_counter_db) == 1  # allocation DID write


# ─────────────────────────────────────────────────────────────────────
# A6 amendment — canonical lifecycle numbering (2026-07-10)
# {DOCUMENT_TYPE_CODE}{SELLER_CODE}{CUSTOMER_NO}{YY}{MM}{SEQ:3} — the base
# sequence is born at the first Quotation (scope per_seller_customer_monthly:
# doctype NOT in the key) and inherited by Proforma/Commercial via the A5
# render-only path; only the leading type digit differs. Additive: all A4/A5
# scopes and tests above stay valid. Contract: CONTRACT_v1 §10 (A6).
# ─────────────────────────────────────────────────────────────────────

A6_TEMPLATE = "{DOCUMENT_TYPE_CODE}{SELLER_CODE}{CUSTOMER_NO}{YY}{MM}{SEQ:3}"
A6_SCOPE = "per_seller_customer_monthly"


def test_a6_document_type_code_renders(isolated_counter_db: Path) -> None:
    """Codex's canonical example: seller 02, customer 104, 2026-07, seq 001
    → quotation 1021042607001."""
    num = generate_document_number(
        seller_code="02", issue_date=date(2026, 7, 3), template=A6_TEMPLATE,
        counter_scope=A6_SCOPE, customer_no=104, document_type="quotation",
        tenant_key="19", db_path=isolated_counter_db,
    )
    assert num == "1021042607001"


def test_a6_shared_base_across_lifecycle(isolated_counter_db: Path) -> None:
    """The base born at the Quotation is inherited by Proforma/Commercial via
    the render-only path: same seq, only the leading digit changes."""
    quotation = generate_document_number(
        seller_code="02", issue_date=date(2026, 7, 3), template=A6_TEMPLATE,
        counter_scope=A6_SCOPE, customer_no=104, document_type="quotation",
        tenant_key="19", db_path=isolated_counter_db,
    )
    proforma = render_document_number(
        A6_TEMPLATE, seq=1, seller_code="02", customer_no=104,
        issue_date=date(2026, 7, 3), document_type="proforma_invoice",
    )
    commercial = render_document_number(
        A6_TEMPLATE, seq=1, seller_code="02", customer_no=104,
        issue_date=date(2026, 7, 3), document_type="commercial_invoice",
    )
    assert quotation == "1021042607001"
    assert proforma == "2021042607001"
    assert commercial == "3021042607001"
    assert quotation[1:] == proforma[1:] == commercial[1:]  # shared base


def test_a6_scope_key_ignores_doctype_and_keys_on_customer() -> None:
    """per_seller_customer_monthly: doctype NOT in the key (Q/P/C share one
    ledger); customer IS in the key (each buyer gets its own ledger)."""
    q = _build_scope_key(A6_SCOPE, "02", date(2026, 7, 3),
                         document_type="quotation", customer_no=104, tenant_key="19")
    p = _build_scope_key(A6_SCOPE, "02", date(2026, 7, 3),
                         document_type="proforma_invoice", customer_no=104, tenant_key="19")
    other = _build_scope_key(A6_SCOPE, "02", date(2026, 7, 3),
                             document_type="quotation", customer_no=250, tenant_key="19")
    assert q == p == "19|02|104|2026-07"
    assert other == "19|02|250|2026-07"  # different buyer → different ledger


def test_a6_per_customer_ledgers_and_month_reset(isolated_counter_db: Path) -> None:
    """Inverse of the A4 seller-ledger: under A6 each buyer starts its own
    sequence, and the month rolls the sequence over."""
    a = generate_document_number(
        seller_code="02", issue_date=date(2026, 7, 3), template=A6_TEMPLATE,
        counter_scope=A6_SCOPE, customer_no=104, document_type="quotation",
        tenant_key="19", db_path=isolated_counter_db,
    )
    b = generate_document_number(
        seller_code="02", issue_date=date(2026, 7, 5), template=A6_TEMPLATE,
        counter_scope=A6_SCOPE, customer_no=250, document_type="quotation",
        tenant_key="19", db_path=isolated_counter_db,
    )
    c = generate_document_number(
        seller_code="02", issue_date=date(2026, 8, 1), template=A6_TEMPLATE,
        counter_scope=A6_SCOPE, customer_no=104, document_type="quotation",
        tenant_key="19", db_path=isolated_counter_db,
    )
    assert a == "1021042607001"
    assert b == "1022502607001"  # buyer 250 starts its own ledger at 001
    assert c == "1021042608001"  # new month → seq resets


def test_a6_scope_requires_customer_no(isolated_counter_db: Path) -> None:
    """New scope with no customer_no → CustomerNoRequiredError BEFORE the
    counter is touched (template without {CUSTOMER_NO} still guards)."""
    with pytest.raises(CustomerNoRequiredError):
        generate_document_number(
            seller_code="02", issue_date=date(2026, 7, 3),
            template="{DOCUMENT_TYPE_CODE}{SELLER_CODE}{YY}{MM}{SEQ:3}",
            counter_scope=A6_SCOPE, customer_no=None, document_type="quotation",
            tenant_key="19", db_path=isolated_counter_db,
        )
    assert _counter_row_count(isolated_counter_db) == 0  # nothing burned


def test_a6_unknown_doctype_raises_without_burning_sequence(
    isolated_counter_db: Path,
) -> None:
    """{DOCUMENT_TYPE_CODE} + unknown/missing document_type →
    DocumentTypeCodeRequiredError, counter untouched."""
    with pytest.raises(DocumentTypeCodeRequiredError):
        generate_document_number(
            seller_code="02", issue_date=date(2026, 7, 3), template=A6_TEMPLATE,
            counter_scope=A6_SCOPE, customer_no=104, document_type="invoice",
            tenant_key="19", db_path=isolated_counter_db,
        )
    assert _counter_row_count(isolated_counter_db) == 0


def test_a6_envelope_render_only_with_type_digit(isolated_counter_db: Path) -> None:
    """Full envelope path (A5 render-only) with the A6 template: the engine
    renders the caller-supplied seq with the doctype digit, no counter."""
    payload = _minimal_valid_payload()  # issue_date 2026-06-07 → YY26 MM06
    payload["payload"]["seller"]["company_code"] = "02"
    payload["payload"]["header"]["document_type"] = "proforma_invoice"
    payload["payload"]["numbering"] = {
        "template": A6_TEMPLATE, "counter_scope": A6_SCOPE, "seq": 42,
    }
    payload["payload"]["buyer"]["customer_no"] = 104
    response = create_proforma(payload)
    assert response["status"] == "ok", response.get("errors")
    assert response["result"]["document"]["document_no"] == "2021042606042"
    assert _counter_row_count(isolated_counter_db) == 0
