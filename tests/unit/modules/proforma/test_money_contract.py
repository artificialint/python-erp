"""Money-arithmetic contract tests (QA repo-3 H3).

WHY THIS FILE EXISTS
--------------------
Before it, every monetary assertion in the suite looked like::

    assert line["line_total"] == pytest.approx(1200.0)

`pytest.approx` passes for any implementation whose answer is *close enough* —
which is exactly the class of change a money test is supposed to catch. A grep of
the whole suite for ``round`` / ``quantize`` / ``Decimal`` / cent-boundary cases
returned nothing: the rounding policy had no test at all. Someone could switch
``round(x, 4)`` to ``round(x, 2)``, or half-even to half-up, or float to Decimal,
and 57 tests would stay green.

These tests assert values computed **independently** with ``Decimal`` — not the
engine's own output pasted back in — and they concentrate on the boundaries where
an arithmetic change actually shows up.

WHAT IS DELIBERATELY *NOT* ASSERTED HERE
----------------------------------------
The rounding CONVENTION itself is an open product decision (QA H2: the engine
emits unquantized money such as ``10.458``, and nothing documents whether the
convention is half-up, half-even, per-step or end-of-calc). Pinning a convention
in a test would silently *make* that decision. So these tests assert the
properties that must hold under ANY convention:

* internal consistency — the totals must reconcile against the lines;
* determinism — identical input, identical money out;
* exactness where no rounding is involved at all.

When the convention is ruled on, add the cent-level expectations here; the
boundary payloads are already set up for it.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from erp_engine.modules.proforma import create_proforma


@pytest.fixture()
def isolated_counter_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the document-number counter to a per-test SQLite file.

    Duplicated from ``test_engine.py`` because it is defined there rather than in
    ``conftest.py``. Every test module that touches the engine needs it — which is
    itself a symptom of QA H1/PE1: a genuinely pure engine would need no such
    fixture at all. Left duplicated rather than moved, because relocating a shared
    fixture is a change to the existing suite's structure and this branch is meant
    to be reviewable as QA fixes only.
    """
    db_path = tmp_path / "counters.db"
    monkeypatch.setattr(
        "erp_engine.modules.proforma.rules._resolve_counter_db_path",
        lambda: db_path,
    )
    return db_path


def _payload(request_id: str, lines: list[dict]) -> dict:
    return {
        "request_id": request_id,
        "schema_version": "contract_v1",
        "module": "proforma_invoice",
        "context": {
            "source": "money_contract_tests", "actor_type": "system", "actor_id": 1,
            "customer_id": 1, "tenant_slug": "pilot-ltd",
            "locale": "tr-TR", "timezone": "Europe/Istanbul",
        },
        "payload": {
            "header": {"document_type": "proforma_invoice", "issue_date": "2026-06-07",
                       "document_no": None, "currency": "TRY", "valid_until": None,
                       "buyer_po_reference": None},
            "seller": {"company_code": "IST", "company_name": "UNO AgentAI Ltd",
                       "address": "Levent Mah.", "city": "Istanbul", "country": "TR",
                       "phone": "+90 212 000 00 00", "email": "sales@example.com",
                       "tax_no": "1234567890"},
            "buyer": {"company_name": "Test Buyer Ltd", "address": "Ataturk Cad. 1",
                      "city": "Ankara", "country": "TR", "phone": "+90 312 000 00 00",
                      "email": "buyer@example.com", "tax_no": "9876543210",
                      "source": "db_lookup"},
            "ship_to": {"same_as_buyer": True, "company_name": None, "address": None,
                        "city": None, "country": None, "phone": None, "email": None,
                        "source": "buyer_copy"},
            "line_items": lines,
            "terms": {"freight_cost": 0.0, "delivery_term": "EXW",
                      "delivery_location": "Istanbul Warehouse", "delivery_date": None,
                      "payment_term": "%100 payment in advance"},
            "banking": {"bank_name": None, "bank_account": None, "iban": None,
                        "swift_code": None},
            "notes": {"notes_to_buyer": None, "internal_notes": None},
        },
    }


def _line(no: int, qty: float, price: float, discount: float = 0.0) -> dict:
    return {"line_no": no, "product_code": f"PRD-{no:03d}",
            "product_description": "Widget", "hs_code": "902519",
            "quantity": qty, "unit": "PCS", "unit_price": price,
            "discount_percent": discount, "tax_percent": None, "line_notes": ""}


def _d(value) -> Decimal:
    """Exact decimal view of a value the engine returned."""
    return Decimal(str(value))


# ── exactness where no rounding can be involved ──────────────────────────────

def test_exact_arithmetic_needs_no_tolerance(isolated_counter_db: Path) -> None:
    """10 x 100.00 at 20% VAT is 1200 exactly — assert it exactly, not approximately.

    An `approx` here would also accept 1199.9999, which is precisely the kind of
    drift this suite should refuse to normalise.
    """
    response = create_proforma(_payload("req_money_exact", [_line(1, 10, 100.0)]))
    assert response["status"] == "ok"
    line = response["result"]["line_items"][0]
    assert _d(line["line_total"]) == Decimal("1200")
    assert _d(response["result"]["totals"]["grand_total"]) == Decimal("1200")


# ── internal consistency: the document must add up ───────────────────────────

@pytest.mark.parametrize(
    "label, qty, price, discount",
    [
        ("half-cent tax boundary", 1, 0.05, 0.0),
        ("classic 1.005 float artefact", 1, 5.025, 0.0),
        ("three-way split", 3, 0.1, 0.0),
        ("discount lands on a half cent", 7, 1.115, 5.0),
        ("large quantity, tiny price", 100000, 0.0001, 0.0),
        ("odd price with odd discount", 13, 19.99, 7.5),
        ("free-of-charge line (100% off)", 4, 250.0, 100.0),
    ],
)
def test_totals_reconcile_against_lines(
    isolated_counter_db: Path, label: str, qty: float, price: float, discount: float
) -> None:
    """Whatever the rounding convention, the invoice must agree with itself.

    subtotal - discount + freight + tax == grand_total, and the sum of the line
    totals must equal the grand total. A rounding change that breaks either of
    these produces a document a customer can dispute.
    """
    response = create_proforma(
        _payload(f"req_recon_{abs(hash(label)) % 10**6:06d}", [_line(1, qty, price, discount)])
    )
    assert response["status"] == "ok", f"{label}: {response['errors']}"
    result = response["result"]
    totals = result["totals"]

    line_sum = sum(_d(li["line_total"]) for li in result["line_items"])
    assert line_sum == _d(totals["grand_total"]), (
        f"{label}: line totals sum to {line_sum} but grand_total is {totals['grand_total']}"
    )

    rebuilt = (
        _d(totals["subtotal_amount"])
        - _d(totals["discount_amount"])
        + _d(totals["freight_amount"])
        + _d(totals["tax_amount"])
    )
    assert rebuilt == _d(totals["grand_total"]), (
        f"{label}: components rebuild to {rebuilt} but grand_total is {totals['grand_total']}"
    )


def test_multi_line_totals_reconcile(isolated_counter_db: Path) -> None:
    """Seven identical awkward lines — where per-line rounding drift would show up."""
    lines = [_line(i, 3, 0.415) for i in range(1, 8)]
    response = create_proforma(_payload("req_recon_multi", lines))
    assert response["status"] == "ok"
    result = response["result"]
    line_sum = sum(_d(li["line_total"]) for li in result["line_items"])
    assert line_sum == _d(result["totals"]["grand_total"])


# ── determinism of the money itself ──────────────────────────────────────────

def test_money_is_deterministic_across_calls(isolated_counter_db: Path) -> None:
    """Identical input must produce identical money.

    Note this asserts the MONEY only. The document NUMBER is deliberately not
    compared: the engine allocates it from a stateful counter, so it changes on
    every call — that is QA finding H1/PE1 and is a separate, ruled-on decision.
    """
    seen = set()
    for i in range(3):
        response = create_proforma(_payload(f"req_det_{i}", [_line(1, 3, 19.99, 7.5)]))
        assert response["status"] == "ok"
        totals = response["result"]["totals"]
        seen.add((str(totals["grand_total"]), str(totals["tax_amount"])))
    assert len(seen) == 1, f"money varied across identical calls: {seen}"


# ── range validation (QA PE3) ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "label, discount, price, tax",
    [
        ("discount above 100%", 150.0, 100.0, None),
        ("negative discount is a hidden surcharge", -10.0, 100.0, None),
        ("negative unit price", 0.0, -100.0, None),
        ("absurd tax rate", 0.0, 100.0, 9999.0),
        ("negative tax rate", 0.0, 100.0, -5.0),
    ],
)
def test_out_of_range_money_inputs_are_refused(
    isolated_counter_db: Path, label: str, discount: float, price: float, tax
) -> None:
    """These used to return `status: ok` and a wrong-signed or inflated invoice.

    Measured before the fix: a 150% discount produced grand_total -600.0, a -10%
    discount produced 1320.0 (a silent surcharge), a negative unit price produced
    -1200.0, and a 9999% tax produced 100990.0. The engine is the last component
    that can still refuse a malformed request — it must not turn one into a
    plausible-looking document.
    """
    line = _line(1, 10, price, discount)
    line["tax_percent"] = tax
    response = create_proforma(_payload("req_range", [line]))
    assert response["status"] == "validation_error", f"{label} was accepted"
    assert response["result"] is None
    assert response["errors"], f"{label}: refused without saying why"


def test_full_discount_is_still_valid(isolated_counter_db: Path) -> None:
    """100% off is a real commercial case (free-of-charge line) — it must NOT be refused.

    Guards the range fix against being tightened into a false positive.
    """
    response = create_proforma(_payload("req_foc", [_line(1, 4, 250.0, 100.0)]))
    assert response["status"] == "ok"
    line = response["result"]["line_items"][0]
    assert _d(line["line_total"]) == Decimal("0")
