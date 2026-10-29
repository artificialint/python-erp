"""Exercise the real CLI outside pytest's sys.path and the repository cwd."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.modules.proforma.test_money_precision import _line, _payload


ROOT = Path(__file__).resolve().parents[2]


def run_cli(request, workdir, counter):
    env = os.environ.copy()
    # This is the explicit source-tree invocation contract. A subprocess does
    # not inherit pytest's pythonpath; do not rely on the editable installation.
    env["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["ERP_ENGINE_COUNTER_DB"] = str(counter)
    return subprocess.run(
        [sys.executable, "-m", "adapters.cli", "--module", "proforma_invoice"],
        input=json.dumps(request), capture_output=True, text=True,
        cwd=workdir, env=env, timeout=30, check=False,
    )


@pytest.mark.parametrize("case,exit_code,status,error", [
    ("valid", 0, "ok", None),
    ("empty", 2, "validation_error", "missing"),
    ("currency", 2, "validation_error", "unsupported_currency"),
    ("overflow", 2, "validation_error", "amount_out_of_range"),
])
def test_real_cli_envelope(case, exit_code, status, error, tmp_path):
    request = _payload("cli-subprocess", [_line(1, 3, 33.33, tax=18)])
    if case == "empty":
        request = {}
    elif case == "currency":
        request["payload"]["header"]["currency"] = "JPY"
    elif case == "overflow":
        request["payload"]["line_items"][0].update(quantity=1e15, unit_price=1e15)
    counter = tmp_path / "cli-counters.db"
    process = run_cli(request, tmp_path, counter)
    assert process.returncode == exit_code, process.stderr
    assert process.stderr == ""
    response = json.loads(process.stdout)
    assert response["status"] == status
    if error:
        assert response["result"] is None
        assert error in {item["code"] for item in response["errors"]}
        assert not counter.exists()
    else:
        assert response["result"]["totals"]["grand_total"] == 117.99
        assert counter.exists()
