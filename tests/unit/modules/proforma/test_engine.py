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
from pathlib import Path

import pytest

from erp_engine.modules.proforma import create_proforma
from erp_engine.modules.proforma.rules import (
    _build_scope_key,
    _ensure_counter_schema,
    generate_document_number,
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
