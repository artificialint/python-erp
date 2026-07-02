"""Fixtures for erp_data tests — an isolated bootstrapped SQLite session."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from erp_data.db.init_db import bootstrap


@pytest.fixture()
def erp_session(tmp_path) -> Iterator[Session]:
    """A fresh bootstrapped SQLite DB (all tables + seed) per test."""
    db_path = tmp_path / "erp.sqlite"
    engine, session_factory = bootstrap(db_path)
    with session_factory() as session:
        yield session
    engine.dispose()
