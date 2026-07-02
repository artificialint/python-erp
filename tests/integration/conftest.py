"""Fixtures for the INV-0.5 integration flow — bootstrapped DB + isolated counter."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from erp_data.db.init_db import bootstrap


@pytest.fixture()
def flow_session(tmp_path, monkeypatch) -> Iterator[Session]:
    """Fresh SQLite DB + a per-test engine document-number counter."""
    monkeypatch.setenv("ERP_ENGINE_COUNTER_DB", str(tmp_path / "counters.db"))
    engine, session_factory = bootstrap(tmp_path / "erp.sqlite")
    with session_factory() as session:
        yield session
    engine.dispose()
