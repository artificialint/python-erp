"""Money-precision contract tests (Amendment A7).

These differ from ``test_money_contract.py`` in one deliberate way: that module
is convention-agnostic on purpose ("whatever the rounding convention, the
invoice must agree with itself") and therefore passed on the pre-A7 output
``117.9882``. This module asserts *the convention itself*.

Every expectation here is derived by hand from
``docs/CONTRACT_A7_MONEY_PRECISION.md`` §A7.2 and written as a literal. None is
taken from engine output, and none is computed with the same quantization the
engine uses — a test whose oracle shares the implementation's rounding only
proves the code agrees with itself.

Each test in this file must FAIL on pre-A7 code. Where that is not obvious the
test says why in its docstring.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from erp_engine.modules.proforma.engine import create_proforma
from erp_engine.modules.proforma.rules import (
    MAX_AMOUNT_MAGNITUDE,
    MONEY_SCALE,
    SUPPORTED_CURRENCIES,
    round_money,
    to_money,
)
from erp_engine.modules.proforma.schema import _MAX_INPUT_MAGNITUDE


@pytest.fixture()
def isolated_counter_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the document-number counter to a per-test SQLite file.

    Keeps the repo's real ``var/counters.db`` untouched and stops sequence
    allocation from leaking between tests.
    """
    db_path = tmp_path / "counters.db"
    monkeypatch.setattr(
        "erp_engine.modules.proforma.rules._resolve_counter_db_path",
        lambda: db_path,
    )
    return db_path


# ── payload helpers ──────────────────────────────────────────────────


def _payload(
    request_id: str,
    lines: list[dict],
    *,
    currency: str = "TRY",
    freight: float = 0.0,
) -> dict:
    return {
        "request_id": request_id,
        "schema_version": "contract_v1",
        "module": "proforma_invoice",
        "context": {
            "source": "a7_precision_tests", "actor_type": "system", "actor_id": 1,
            "customer_id": 1, "tenant_slug": "pilot-ltd",
            "locale": "tr-TR", "timezone": "Europe/Istanbul",
        },
        "payload": {
            "header": {"document_type": "proforma_invoice", "issue_date": "2026-06-07",
                       "document_no": None, "currency": currency, "valid_until": None,
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
            "terms": {"freight_cost": freight, "delivery_term": "EXW",
                      "delivery_location": "Istanbul Warehouse", "delivery_date": None,
                      "payment_term": "%100 payment in advance"},
            "banking": {"bank_name": None, "bank_account": None, "iban": None,
                        "swift_code": None},
            "notes": {"notes_to_buyer": None, "internal_notes": None},
        },
    }


def _line(no: int, qty: float, price: float, discount: float = 0.0,
          tax: float | None = None) -> dict:
    return {"line_no": no, "product_code": f"PRD-{no:03d}",
            "product_description": "Widget", "hs_code": "902519",
            "quantity": qty, "unit": "PCS", "unit_price": price,
            "discount_percent": discount, "tax_percent": tax, "line_notes": ""}


def _ok(payload: dict) -> dict:
    response = create_proforma(payload)
    assert response["status"] == "ok", response.get("errors")
    return response["result"]


def _d(value) -> Decimal:
    """Exact decimal view of a value the engine returned."""
    return Decimal(str(value))


MONEY_FIELDS = (
    "subtotal_amount", "discount_amount", "freight_amount",
    "net_amount", "tax_amount", "grand_total",
)
LINE_MONEY_FIELDS = ("discount_amount", "tax_amount", "line_total")


# ── A7.5 worked examples — hand-derived, normative ───────────────────


@pytest.mark.parametrize(
    "case_id, lines, expected_grand",
    [
        # 3 x 33.33 = 99.99 taxable; group tax round2(99.99 * 0.18)
        # = round2(17.9982) = 18.00; 99.99 + 18.00 = 117.99.
        # Pre-A7 returned 117.9882.
        ("three_awkward", [_line(1, 3, 33.33, tax=18.0)], "117.99"),
        # seven lines of 0.07: taxable 0.49; group round2(0.0882) = 0.09.
        # Pre-A7 returned 0.5782.
        ("seven_cents", [_line(i, 1, 0.07, tax=18.0) for i in range(1, 8)], "0.58"),
        # 100 less 33.333% -> discount round2(33.333) = 33.33, taxable 66.67;
        # tax round2(13.334) = 13.33. Pre-A7 returned 80.0004.
        ("awkward_discount", [_line(1, 1, 100.0, discount=33.333, tax=20.0)], "80.00"),
        # gross round2(1.005) = 1.01 under HALF_UP -- and only because the
        # engine converts via Decimal(str(x)); Decimal(1.005) would give 1.00.
        # tax round2(0.202) = 0.20. Pre-A7 returned 1.206.
        ("half_up_boundary", [_line(1, 1, 1.005, tax=20.0)], "1.21"),
        # exact case: no rounding needed anywhere. Passes pre-A7 too, kept as
        # the control -- it proves the change did not disturb clean arithmetic.
        ("already_exact", [_line(1, 3, 0.10, tax=20.0)], "0.36"),
    ],
)
def test_approved_examples_match_the_decided_convention(
    case_id: str, lines: list[dict], expected_grand: str,
    isolated_counter_db: Path,
) -> None:
    """The Owner's approved figures, asserted exactly."""
    result = _ok(_payload(f"a7-{case_id}", lines))
    assert _d(result["totals"]["grand_total"]) == Decimal(expected_grand)


def test_mixed_tax_rates_group_independently(isolated_counter_db: Path) -> None:
    """Two rates in one document; each group rounds on its own base.

    The inputs are chosen so that grouping actually changes the answer, in BOTH
    directions. An earlier version of this test used 33.33/10.005/50.00, which
    happens to be exact at four decimals -- so it passed on pre-A7 code and
    proved nothing. These numbers do not.

    Hand-derived under largest-remainder allocation. Three lines of 1 x 0.07 at
    18%: exact share 0.0126 each, floored 0.01 each summing to 0.03; group tax
    round2(0.21 x 0.18) = 0.04, so one cent is outstanding and the discarded
    fractions tie at 0.0026, giving it to the lowest line_no. Two lines of
    1 x 0.19 at 8%: exact 0.0152 each, floored 0.01 each summing to 0.02; group
    tax round2(0.38 x 0.08) = 0.03, one cent outstanding, fractions tie at
    0.0052, again to the lowest line_no.

    subtotal 0.59, tax 0.04 + 0.03 = 0.07, grand 0.66.
    Pre-A7 returned 0.6582.
    """
    result = _ok(_payload("a7-mixed", [
        _line(1, 1, 0.07, tax=18.0),
        _line(2, 1, 0.07, tax=18.0),
        _line(3, 1, 0.07, tax=18.0),
        _line(4, 1, 0.19, tax=8.0),
        _line(5, 1, 0.19, tax=8.0),
    ]))
    totals = result["totals"]
    assert _d(totals["subtotal_amount"]) == Decimal("0.59")
    assert _d(totals["tax_amount"]) == Decimal("0.07")
    assert _d(totals["grand_total"]) == Decimal("0.66")

    # One cent outstanding in each group; the discarded fractions tie within a
    # group, so the lowest line_no takes it.
    by_no = {line["line_no"]: _d(line["tax_amount"]) for line in result["line_items"]}
    assert by_no == {
        1: Decimal("0.02"), 2: Decimal("0.01"), 3: Decimal("0.01"),
        4: Decimal("0.02"), 5: Decimal("0.01"),
    }


@pytest.mark.parametrize("n", [2, 10, 50, 100])
def test_no_line_absorbs_the_whole_group_residual(
    n: int, isolated_counter_db: Path,
) -> None:
    """Regression: the residual grows with line count and must not pile onto one line.

    The first A7 implementation rounded each line independently and assigned the
    entire group residual to the largest line, on the stated assumption that the
    residual was "a cent or two". It is not — each per-line rounding can be off
    by up to half a cent, so the residual scales with n. Measured independently
    of the engine for n lines of taxable 0.07 at 18%:

        n=2   group 0.03  per-line 0.01  sum 0.02  residual 0.01
        n=10  group 0.13  per-line 0.01  sum 0.10  residual 0.03
        n=50  group 0.63  per-line 0.01  sum 0.50  residual 0.13
        n=100 group 1.26  per-line 0.01  sum 1.00  residual 0.26

    At n=100 one line's tax became 0.27 against a correct 0.01 — twenty-seven
    times over, on a document a customer reads. Every reconciliation identity
    still held throughout, which is why no totals-based test could see it: found
    by review, not by the suite.

    Largest-remainder bounds each line's adjustment to one cent regardless of n.
    """
    lines = [_line(i, 1, 0.07, tax=18.0) for i in range(1, n + 1)]
    result = _ok(_payload(f"a7-resid-{n}", lines))

    # Independently derived: the exact share of a 0.07 taxable at 18%.
    exact_share = Decimal("0.07") * Decimal(18) / Decimal(100)
    one_cent = Decimal("0.01")
    for line in result["line_items"]:
        deviation = abs(_d(line["tax_amount"]) - exact_share)
        assert deviation <= one_cent, (
            f"line {line['line_no']} tax {line['tax_amount']!r} deviates "
            f"{deviation} from its exact share {exact_share}"
        )

    # and the column still sums to the group figure
    line_tax = sum((_d(line["tax_amount"]) for line in result["line_items"]), Decimal(0))
    assert line_tax == _d(result["totals"]["tax_amount"])


def test_group_residual_is_allocated_to_the_largest_line(
    isolated_counter_db: Path,
) -> None:
    """Per-line tax must sum to the group figure, so the residual lands somewhere.

    Hand-derived: three lines of 0.07 at 18%. Per line round2(0.0126) = 0.01,
    summing to 0.03. The group base is 0.21 and round2(0.0378) = 0.04, so there
    is a 0.01 residual. All three taxables are equal, so the tie breaks on the
    lowest line_no and line 1 carries it: 0.02, 0.01, 0.01.
    """
    result = _ok(_payload("a7-residual", [_line(i, 1, 0.07, tax=18.0) for i in (1, 2, 3)]))
    by_no = {line["line_no"]: _d(line["tax_amount"]) for line in result["line_items"]}
    assert by_no == {1: Decimal("0.02"), 2: Decimal("0.01"), 3: Decimal("0.01")}
    assert _d(result["totals"]["tax_amount"]) == Decimal("0.04")
    assert _d(result["totals"]["grand_total"]) == Decimal("0.25")


def test_freight_is_rounded_added_and_not_taxed(isolated_counter_db: Path) -> None:
    """Hand-derived: freight 5.005 -> 5.01 HALF_UP, untaxed.

    1 x 100 at 20% gives taxable 100.00 and tax 20.00. net = 100.00 + 5.01 =
    105.01, grand = 125.01. Because freight is not a line, the document identity
    is sum(line_total) + freight == grand_total, i.e. 120.00 + 5.01.
    """
    result = _ok(_payload("a7-freight", [_line(1, 1, 100.0, tax=20.0)], freight=5.005))
    totals = result["totals"]
    assert _d(totals["freight_amount"]) == Decimal("5.01")
    assert _d(totals["tax_amount"]) == Decimal("20.00")
    assert _d(totals["net_amount"]) == Decimal("105.01")
    assert _d(totals["grand_total"]) == Decimal("125.01")
    line_sum = sum((_d(line["line_total"]) for line in result["line_items"]), Decimal(0))
    assert line_sum + _d(totals["freight_amount"]) == _d(totals["grand_total"])


# ── A7.6 invariants ──────────────────────────────────────────────────

_INVARIANT_CASES = [
    ("single", [_line(1, 3, 33.33, tax=18.0)], 0.0),
    ("seven", [_line(i, 1, 0.07, tax=18.0) for i in range(1, 8)], 0.0),
    ("mixed", [_line(1, 3, 33.33, tax=18.0), _line(2, 1, 50.0, tax=8.0)], 0.0),
    ("discount", [_line(1, 7, 12.345, discount=13.7, tax=20.0)], 3.333),
    ("zero_tax", [_line(1, 2, 19.99, tax=0.0)], 1.005),
    ("full_discount", [_line(1, 1, 250.0, discount=100.0, tax=20.0)], 0.0),
    ("many_awkward", [_line(i, 3, 1.115 * i, discount=1.5 * i, tax=18.0)
                      for i in range(1, 10)], 9.999),
]


@pytest.mark.parametrize("case_id, lines, freight", _INVARIANT_CASES)
def test_every_money_field_has_at_most_two_decimals(
    case_id: str, lines: list[dict], freight: float, isolated_counter_db: Path,
) -> None:
    """A7.6 invariant 1. This is the test that fails hardest on pre-A7 code."""
    result = _ok(_payload(f"a7-scale-{case_id}", lines, freight=freight))
    for field in MONEY_FIELDS:
        exponent = _d(result["totals"][field]).as_tuple().exponent
        assert exponent >= -2, f"totals.{field} = {result['totals'][field]!r}"
    for line in result["line_items"]:
        for field in LINE_MONEY_FIELDS:
            exponent = _d(line[field]).as_tuple().exponent
            assert exponent >= -2, f"line {line['line_no']}.{field} = {line[field]!r}"


@pytest.mark.parametrize("case_id, lines, freight", _INVARIANT_CASES)
def test_document_reconciles_exactly(
    case_id: str, lines: list[dict], freight: float, isolated_counter_db: Path,
) -> None:
    """A7.6 invariants 2-5, as exact Decimal equalities rather than tolerances.

    Honest scope note: these four identities also held on pre-A7 code, which
    reconciled consistently at four decimals. So this test is a regression guard
    that A7 did not break self-consistency -- it is NOT evidence that A7 works.
    The A7-discriminating assertions are the scale test above and the worked
    examples; this one would pass on either implementation and is kept because
    it would catch a future change that broke the identities.
    """
    result = _ok(_payload(f"a7-recon-{case_id}", lines, freight=freight))
    totals = result["totals"]
    subtotal, discount = _d(totals["subtotal_amount"]), _d(totals["discount_amount"])
    freight_amount, net = _d(totals["freight_amount"]), _d(totals["net_amount"])
    tax, grand = _d(totals["tax_amount"]), _d(totals["grand_total"])

    assert subtotal - discount + freight_amount == net
    assert net + tax == grand

    line_tax = sum((_d(line["tax_amount"]) for line in result["line_items"]), Decimal(0))
    assert line_tax == tax

    line_totals = sum((_d(line["line_total"]) for line in result["line_items"]), Decimal(0))
    assert line_totals + freight_amount == grand


def test_money_is_deterministic_across_calls(isolated_counter_db: Path) -> None:
    """A7.6 invariant 6 — same input, byte-identical money output."""
    lines = [_line(i, 3, 1.115 * i, discount=1.5 * i, tax=18.0) for i in range(1, 6)]
    first = _ok(_payload("a7-det-1", lines, freight=2.225))
    second = _ok(_payload("a7-det-2", lines, freight=2.225))
    assert first["totals"] == second["totals"]
    assert [line["tax_amount"] for line in first["line_items"]] == \
           [line["tax_amount"] for line in second["line_items"]]


# ── A7.3 JSON representation ─────────────────────────────────────────


def test_money_round_trips_through_json_unchanged(isolated_counter_db: Path) -> None:
    """A7.3 — the wire format stays a JSON number and survives a round trip."""
    result = _ok(_payload("a7-json", [
        _line(1, 3, 33.33, tax=18.0),
        _line(2, 7, 12.345, discount=13.7, tax=20.0),
    ], freight=4.005))
    restored = json.loads(json.dumps(result))
    assert restored["totals"] == result["totals"]
    for field in MONEY_FIELDS:
        rendered = json.dumps(result["totals"][field])
        assert _d(json.loads(rendered)) == _d(result["totals"][field])
        # at most two decimals in the shortest round-tripping repr
        if "." in rendered:
            assert len(rendered.split(".")[1]) <= 2, f"{field} -> {rendered}"


# ── A7.2 §1 the Decimal(str()) requirement ───────────────────────────


def test_decimal_str_conversion_is_what_makes_half_up_correct() -> None:
    """The conversion is load-bearing, not stylistic.

    ``Decimal(1.005)`` is 1.00499999999999989... so HALF_UP rounds it DOWN.
    ``Decimal(str(1.005))`` is exactly 1.005 and rounds UP. If someone
    "simplifies" ``to_money`` to ``Decimal(value)``, this fails.
    """
    assert round_money(to_money(1.005)) == Decimal("1.01")
    assert round_money(Decimal(1.005)) == Decimal("1.00")
    assert round_money(to_money(2.675)) == Decimal("2.68")
    assert round_money(Decimal(2.675)) == Decimal("2.67")


def test_half_up_is_not_banker_s_rounding() -> None:
    """HALF_EVEN would send 0.125 to 0.12 and 2.5 to 2; HALF_UP must not."""
    assert round_money(to_money("0.125")) == Decimal("0.13")
    assert round_money(to_money("0.135")) == Decimal("0.14")
    assert round_money(to_money("0.145")) == Decimal("0.15")


# ── A7.2 §10 currency scope ──────────────────────────────────────────


@pytest.mark.parametrize("currency", sorted(SUPPORTED_CURRENCIES))
def test_supported_currencies_are_accepted(
    currency: str, isolated_counter_db: Path,
) -> None:
    result = _ok(_payload(f"a7-cur-{currency}", [_line(1, 1, 10.0, tax=20.0)],
                          currency=currency))
    assert result["document"]["currency"] == currency


@pytest.mark.parametrize("currency", ["JPY", "KRW", "CHF", "", "try ", "xyz"])
def test_out_of_scope_currency_is_a_validation_error(
    currency: str, isolated_counter_db: Path,
) -> None:
    """Zero-decimal and unknown currencies must be refused, not silently rounded.

    ``"try "`` is included because the engine normalizes case and whitespace
    before comparing, so a padded lowercase code must still succeed rather than
    be rejected -- see the separate normalization test below.
    """
    payload = _payload("a7-badcur", [_line(1, 1, 10.0, tax=20.0)], currency=currency)
    response = create_proforma(payload)
    if currency.strip().upper() in SUPPORTED_CURRENCIES:
        assert response["status"] == "ok"
        return
    assert response["status"] == "validation_error"
    assert response["errors"][0]["code"] == "unsupported_currency"
    assert response["errors"][0]["field"] == "header.currency"


def test_currency_is_normalized_in_the_result(isolated_counter_db: Path) -> None:
    result = _ok(_payload("a7-norm", [_line(1, 1, 10.0, tax=20.0)], currency=" try "))
    assert result["document"]["currency"] == "TRY"


def test_unsupported_currency_does_not_burn_a_sequence(
    isolated_counter_db: Path,
) -> None:
    """A7.2 §10 — the currency guard runs before the counter is touched.

    Same principle as A4's {CUSTOMER_NO} and A6's {DOCUMENT_TYPE_CODE} guards:
    a rejected request must not consume a document number.
    """
    import sqlite3

    rejected = create_proforma(
        _payload("a7-noburn", [_line(1, 1, 10.0, tax=20.0)], currency="JPY")
    )
    assert rejected["status"] == "validation_error"
    if isolated_counter_db.exists():
        with sqlite3.connect(isolated_counter_db) as conn:
            rows = conn.execute("SELECT COUNT(*) FROM doc_counter").fetchone()[0]
        assert rows == 0


# ── A7.4 input guards ────────────────────────────────────────────────


@pytest.mark.parametrize("field", ["quantity", "unit_price", "discount_percent",
                                   "tax_percent"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_line_inputs_are_refused(
    field: str, bad: float, isolated_counter_db: Path,
) -> None:
    """Every comparison against NaN is False, so pre-A7 all four accepted it.

    A ``nan`` unit_price produced ``status: "ok"`` with ``grand_total: nan``.
    """
    line = _line(1, 2.0, 10.0, discount=5.0, tax=20.0)
    line[field] = bad
    response = create_proforma(_payload(f"a7-nf-{field}", [line]))
    assert response["status"] == "validation_error"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_bad_freight_is_refused(bad: float, isolated_counter_db: Path) -> None:
    """freight_cost had no validator at all before A7."""
    response = create_proforma(
        _payload("a7-freight-bad", [_line(1, 1, 10.0, tax=20.0)], freight=bad)
    )
    assert response["status"] == "validation_error"


def test_full_discount_still_produces_a_zero_document(
    isolated_counter_db: Path,
) -> None:
    """100% off is a real free-of-charge line and must survive A7 at scale 2."""
    result = _ok(_payload("a7-free", [_line(1, 1, 250.0, discount=100.0, tax=20.0)]))
    totals = result["totals"]
    assert _d(totals["discount_amount"]) == Decimal("250.00")
    assert _d(totals["net_amount"]) == Decimal("0.00")
    assert _d(totals["tax_amount"]) == Decimal("0.00")
    assert _d(totals["grand_total"]) == Decimal("0.00")


# ── A7.7 numbering non-regression ────────────────────────────────────


def test_a4_a5_a6_numbering_is_untouched_by_a7(isolated_counter_db: Path) -> None:
    """A7 changes money only. The A5 render-only path must still not allocate.

    Uses the canonical A6 template so the {DOCUMENT_TYPE_CODE} digit, seller
    code, customer number and caller-supplied seq all have to render exactly as
    A6 specifies: proforma_invoice -> 2, seller 02, customer 104, 2026-07,
    seq 001 -> "2021042607001".
    """
    import sqlite3

    payload = _payload("a7-numbering", [_line(1, 1, 10.0, tax=20.0)])
    payload["payload"]["header"]["issue_date"] = "2026-07-03"
    payload["payload"]["seller"]["company_code"] = "02"
    payload["payload"]["buyer"]["customer_no"] = 104
    payload["payload"]["numbering"] = {
        "template": "{DOCUMENT_TYPE_CODE}{SELLER_CODE}{CUSTOMER_NO}{YY}{MM}{SEQ:3}",
        "seq": 1,
    }
    result = _ok(payload)
    assert result["document"]["document_no"] == "2021042607001"

    # A5: a caller-supplied seq renders without touching the counter.
    if isolated_counter_db.exists():
        with sqlite3.connect(isolated_counter_db) as conn:
            rows = conn.execute("SELECT COUNT(*) FROM doc_counter").fetchone()[0]
        assert rows == 0


# ── allocation properties (review follow-up) ─────────────────────────


@pytest.mark.parametrize("n, taxable, rate", [
    (3, 0.07, 18.0),      # 1 cent outstanding
    (10, 0.07, 18.0),     # 3 cents
    (50, 0.07, 18.0),     # 13 cents
    (7, 0.19, 8.0),       # different rate and fraction
])
def test_exactly_the_outstanding_cents_are_distributed_one_each(
    n: int, taxable: float, rate: float, isolated_counter_db: Path,
) -> None:
    """The property largest-remainder actually guarantees.

    Invariant 7 (each line within one cent of its exact share) is satisfied *by
    construction* once largest-remainder is in place, so on its own it cannot
    distinguish a correct implementation from a subtly wrong one -- it only
    catches the old "all residual to one line" rule. What discriminates is the
    distribution shape: exactly as many lines are lifted above their floor as
    there are outstanding cents, and each is lifted by exactly one cent.

    A naive reimplementation that dumped the remainder on one line, or handed
    out two cents to some lines, or skipped the sort, would break this while
    still reconciling.
    """
    from decimal import ROUND_DOWN

    lines = [_line(i, 1, taxable, tax=rate) for i in range(1, n + 1)]
    result = _ok(_payload(f"a7-alloc-{n}-{rate}", lines))

    # Independently derived floor and outstanding-cent count.
    exact_share = to_money(taxable) * to_money(rate) / Decimal(100)
    floor_share = exact_share.quantize(MONEY_SCALE, rounding=ROUND_DOWN)
    group_tax = _d(result["totals"]["tax_amount"])
    outstanding = int(((group_tax - floor_share * n) / MONEY_SCALE).to_integral_value())

    lifted = [
        _d(line["tax_amount"]) - floor_share
        for line in result["line_items"]
    ]
    assert sum(1 for delta in lifted if delta != 0) == outstanding
    assert all(delta in (Decimal(0), MONEY_SCALE) for delta in lifted), lifted


def test_residual_is_never_negative_by_construction(isolated_counter_db: Path) -> None:
    """No line is ever adjusted downward -- see CONTRACT_A7 §A7.2.6.

    Flooring never overshoots, so the sum of floors is a multiple of a cent that
    is at most the exact group total, hence at most round2(exact total). There is
    therefore no input for which the outstanding count is negative, which is why
    this is asserted as a property over awkward inputs rather than demonstrated
    with a single crafted case that cannot exist.
    """
    from decimal import ROUND_DOWN

    for index, (qty, price, rate) in enumerate([
        (3, 0.07, 18.0), (7, 0.19, 8.0), (11, 1.003, 20.0),
        (2, 99.995, 18.0), (5, 0.01, 1.0), (13, 7.777, 18.0),
    ]):
        lines = [_line(i, qty, price, tax=rate) for i in range(1, 5)]
        result = _ok(_payload(f"a7-nonneg-{index}", lines))
        exact = to_money(qty) * to_money(price)
        taxable = round_money(exact)
        floor_share = (taxable * to_money(rate) / Decimal(100)).quantize(
            MONEY_SCALE, rounding=ROUND_DOWN
        )
        for line in result["line_items"]:
            assert _d(line["tax_amount"]) >= floor_share, (
                f"line {line['line_no']} was adjusted DOWN from its floor"
            )


# ── crash-path regression (review follow-up) ─────────────────────────


@pytest.mark.parametrize("field, value", [
    ("unit_price", 1e26),
    ("unit_price", 1e30),
    ("quantity", 1e26),
])
def test_absurd_amounts_are_refused_not_crashed(
    field: str, value: float, isolated_counter_db: Path,
) -> None:
    """A7 regression: Decimal.quantize raises on context overflow.

    The first A7 implementation had no magnitude bound, so unit_price = 1e26 made
    ``quantize`` raise ``decimal.InvalidOperation`` straight out of
    ``create_proforma`` -- a crash through the contract boundary rather than an
    error envelope. Pre-A7 float arithmetic did not crash here, so A7 introduced
    this path and must close it. The engine's promise is that every response is a
    well-formed envelope.
    """
    line = _line(1, 2.0, 10.0, tax=18.0)
    line[field] = value
    response = create_proforma(_payload("a7-absurd", [line]))
    assert response["status"] == "validation_error"


def test_large_freight_is_refused_not_crashed(isolated_counter_db: Path) -> None:
    """Same path, reached through the totals rather than the line loop."""
    response = create_proforma(
        _payload("a7-absurd-freight", [_line(1, 1, 10.0, tax=18.0)], freight=1e30)
    )
    assert response["status"] == "validation_error"


def test_schema_and_rules_magnitude_bounds_agree() -> None:
    """The bound is declared twice -- as float in schema, Decimal in rules.

    They must not drift, or an input the schema accepts could still raise inside
    the engine.
    """
    assert Decimal(str(_MAX_INPUT_MAGNITUDE)) == MAX_AMOUNT_MAGNITUDE


def test_a_document_at_the_magnitude_bound_still_computes(
    isolated_counter_db: Path,
) -> None:
    """The bound must sit inside the safe region, not on its edge.

    §A7.3b claims the bound leaves the arithmetic comfortable. Measured, the
    first magnitude that makes quantize raise is 1e26, and 1e25 already uses all
    28 context digits — so the bound at 1e15 is eleven orders below the wall.
    This pins the property that claim rests on: a multi-line document whose
    lines sit exactly at the bound must return a normal result rather than an
    exception, with every A7 invariant intact.

    Without this test the headroom is a sentence in a document. Two of the three
    digit counts in the first version of that sentence were wrong by one, which
    is the argument for measuring the property rather than restating the
    reasoning.
    """
    at_bound = float(MAX_AMOUNT_MAGNITUDE)
    lines = [_line(i, 1, at_bound, tax=18.0) for i in range(1, 6)]
    result = _ok(_payload("a7-at-bound", lines))

    totals = result["totals"]
    # invariants still hold at the extreme
    assert _d(totals["subtotal_amount"]) - _d(totals["discount_amount"])         + _d(totals["freight_amount"]) == _d(totals["net_amount"])
    assert _d(totals["net_amount"]) + _d(totals["tax_amount"]) == _d(totals["grand_total"])
    line_tax = sum((_d(line["tax_amount"]) for line in result["line_items"]), Decimal(0))
    assert line_tax == _d(totals["tax_amount"])

    # and one step above the bound is refused rather than crashed
    over = _line(1, 1, at_bound * 10, tax=18.0)
    assert create_proforma(_payload("a7-over-bound", [over]))["status"] == "validation_error"
