"""A7-FIX-002: protect Decimal computation, wire cents and counter custody."""

import json
from decimal import Decimal

import pytest

from erp_engine.modules.proforma.engine import create_proforma
from tests.unit.modules.proforma.test_money_precision import (
    _line,
    _payload,
    isolated_counter_db,  # noqa: F401 - pytest fixture shared with precision tests
)


@pytest.mark.parametrize("lines,freight", [
    ([_line(1, 1e15, 1e15, tax=18)], 0),  # legal factors, quantize overflow
    ([_line(1, 3, 333333333333333.33, tax=20)], 0),  # original wire loss
    ([_line(1, 1, 5e12, tax=0)], 0),  # exact bound, even with zero tax
    ([_line(1, 1, 5e12, discount=100, tax=0)], 0),  # discount cannot bypass
    ([_line(1, 1, 3e12, tax=18), _line(2, 1, 2e12, tax=8)], 0),
    ([_line(1, 1, 4999999999999.99, tax=100)], 0.02),  # freight reaches bound
    ([_line(1, 1, 0, tax=0)], 1e13),  # freight alone reaches bound
])
@pytest.mark.parametrize("numbering_path", ["allocate", "explicit", "render"])
def test_unsafe_document_refused_before_any_numbering(
    lines, freight, numbering_path, isolated_counter_db,
):
    request = _payload("unsafe-document", lines, freight=freight)
    if numbering_path == "explicit":
        request["payload"]["header"]["document_no"] = "DRAFT"
    elif numbering_path == "render":
        request["payload"]["numbering"] = {"seq": 7}
    response = create_proforma(request)
    assert response["status"] == "validation_error"
    assert response["result"] is None
    assert response["errors"][0]["code"] == "amount_out_of_range"
    assert not isolated_counter_db.exists()


def test_refusal_preserves_existing_counter(isolated_counter_db):
    good = _payload("first", [_line(1, 1, 1, tax=20)])
    first = create_proforma(good)
    assert first["status"] == "ok"
    before = isolated_counter_db.read_bytes()
    bad = _payload("bad", [_line(1, 1e15, 1e15, tax=20)])
    assert create_proforma(bad)["status"] == "validation_error"
    assert isolated_counter_db.read_bytes() == before
    second = create_proforma(good)
    assert first["result"]["document"]["document_no"].endswith("00001")
    assert second["result"]["document"]["document_no"].endswith("00002")


def test_last_cent_below_bound_reconciles_after_json(isolated_counter_db):
    # Conservative upper bound = 9,999,999,999,999.99 exactly.
    request = _payload("last-cent", [
        _line(1, 1, 2499999999999.99, discount=33.333, tax=18),
        _line(2, 1, 2500000000000, tax=100),
    ], freight=0.01)
    response = create_proforma(request)
    assert response["status"] == "ok"
    result = json.loads(json.dumps(response))["result"]
    totals = {key: Decimal(str(value)) for key, value in result["totals"].items()}
    assert totals["subtotal_amount"] == Decimal("4999999999999.99")
    assert totals["discount_amount"] == Decimal("833325000000.00")
    assert (
        totals["subtotal_amount"] - totals["discount_amount"] + totals["freight_amount"]
        == totals["net_amount"]
    )
    assert totals["net_amount"] + totals["tax_amount"] == totals["grand_total"]
    line_tax = sum(Decimal(str(line["tax_amount"])) for line in result["line_items"])
    line_total = sum(Decimal(str(line["line_total"])) for line in result["line_items"])
    assert line_tax == totals["tax_amount"]
    assert line_total + totals["freight_amount"] == totals["grand_total"]
    for value in [*totals.values(), *(Decimal(str(line[key]))
                  for line in result["line_items"]
                  for key in ("discount_amount", "tax_amount", "line_total"))]:
        assert value.as_tuple().exponent >= -2


def test_input_at_1e15_with_small_product_is_still_supported(isolated_counter_db):
    response = create_proforma(_payload("large-quantity", [
        _line(1, 1e15, 0.000001, tax=20),
    ]))
    assert response["status"] == "ok"
    assert response["result"]["totals"]["grand_total"] == 1200000000.0


@pytest.mark.parametrize("numbering_path", ["allocate", "explicit", "render"])
def test_missing_tax_rule_does_not_burn_a_number(numbering_path, isolated_counter_db):
    good = _payload("seed-counter", [_line(1, 1, 1, tax=20)])
    assert create_proforma(good)["status"] == "ok"
    before = isolated_counter_db.read_bytes()
    bad = _payload("missing-tax", [_line(1, 1, 100)])
    bad["payload"]["seller"]["country"] = "US"
    bad["payload"]["buyer"]["country"] = "US"
    if numbering_path == "explicit":
        bad["payload"]["header"]["document_no"] = "DRAFT"
    elif numbering_path == "render":
        bad["payload"]["numbering"] = {"seq": 7}
    response = create_proforma(bad)
    assert response["status"] == "execution_error"
    assert response["errors"][0]["code"] == "missing_tax_rule"
    assert response["result"] is None
    assert isolated_counter_db.read_bytes() == before
    next_good = create_proforma(good)
    assert next_good["result"]["document"]["document_no"].endswith("00002")
