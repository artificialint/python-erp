"""Language-neutral A7 cases replayed over the real JSON/CLI boundary."""

import json
from pathlib import Path

import pytest

from tests.integration.test_cli_subprocess import run_cli


CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "a7_contract_cases.json")
    .read_text(encoding="utf-8")
)["cases"]


def stable_response(response):
    """Select exactly the shared fixture schema, excluding volatile metadata."""
    result = response["result"]
    if result is not None:
        result = {
            "totals": result["totals"],
            "line_items": [
                {key: line[key] for key in
                 ("line_no", "discount_amount", "tax_amount", "line_total")}
                for line in result["line_items"]
            ],
        }
    return {
        "status": response["status"],
        "result": result,
        "errors": [{key: error[key] for key in ("code", "field")}
                   for error in response["errors"]],
    }


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_shared_contract_case(case, tmp_path):
    counter = tmp_path / "fixture-counters.db"
    process = run_cli(case["request"], tmp_path, counter)
    assert process.returncode == case["exit_code"], process.stderr
    assert process.stderr == ""
    response = json.loads(process.stdout)
    assert stable_response(response) == case["expected"]
    assert not counter.exists()  # explicit numbers: no allocation on replay
