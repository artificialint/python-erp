"""Counter-store failure must return an envelope, not an exception (QA PE2).

The engine's contract is that every call returns a response envelope. Before this,
only ``CustomerNoRequiredError`` was caught around the number-allocation path, so a
locked, missing or read-only counter store escaped as a raw
``sqlite3.OperationalError`` through the contract boundary — the caller asked for a
document and got a stack trace.

The translation now happens in ``rules.py``, the module that owns the storage, as
``CounterStoreError``. That is deliberate: catching ``sqlite3.Error`` in the engine
would mean importing ``sqlite3`` there, deepening the impurity QA H1/PE1 reports,
while catching bare ``Exception`` would report a genuine programming bug as an
infrastructure failure. This test pins both halves of that behaviour.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from erp_engine.modules.proforma import create_proforma
from erp_engine.modules.proforma.rules import CounterStoreError

from .test_money_contract import _line, _payload


def test_counter_store_failure_returns_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A storage failure is an execution_error — the request was fine, we could not serve it."""

    def _boom(*_args, **_kwargs):
        raise CounterStoreError("database is locked")

    monkeypatch.setattr(
        "erp_engine.modules.proforma.engine.generate_document_number", _boom
    )

    response = create_proforma(_payload("req_counter_down", [_line(1, 10, 100.0)]))

    assert response["status"] == "execution_error"
    assert response["result"] is None
    assert response["errors"], "an execution_error must say what failed"
    assert response["errors"][0]["code"] == "counter_store_unavailable"
    # The envelope must still identify the request it answers.
    assert response["request_id"] == "req_counter_down"


def test_a_programming_bug_is_not_disguised_as_infrastructure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real bug must surface as itself, not as `counter_store_unavailable`.

    This is the half that the original broad `except Exception` got wrong: it would
    have swallowed a TypeError and reported the counter store as unavailable, sending
    whoever debugged it to look at the disk instead of the code.
    """

    def _bug(*_args, **_kwargs):
        raise TypeError("unsupported operand type(s)")

    monkeypatch.setattr(
        "erp_engine.modules.proforma.engine.generate_document_number", _bug
    )

    with pytest.raises(TypeError):
        create_proforma(_payload("req_real_bug", [_line(1, 10, 100.0)]))


def test_counter_store_error_is_raised_by_the_storage_layer(tmp_path: Path) -> None:
    """`_next_seq` translates a storage failure at the layer that owns the storage."""
    from erp_engine.modules.proforma import rules

    unusable = tmp_path / "not-a-directory" / "counters.db"
    with pytest.raises(CounterStoreError):
        rules._next_seq("scope:test", db_path=unusable)
