"""INV-0: DB init creates all tables + seeds defaults."""

from __future__ import annotations

from sqlalchemy import inspect, select

from erp_data.db import models
from erp_data.db.base import Base
from erp_data.db.init_db import bootstrap


def test_bootstrap_creates_all_tables(tmp_path) -> None:
    engine, _ = bootstrap(tmp_path / "erp.sqlite")
    tables = set(inspect(engine).get_table_names())
    assert tables == set(Base.metadata.tables.keys())
    assert len(tables) == 14


def test_bootstrap_is_idempotent(tmp_path) -> None:
    db = tmp_path / "erp.sqlite"
    bootstrap(db)
    engine, _ = bootstrap(db)  # second run must not raise
    assert "organizations" in inspect(engine).get_table_names()


def test_default_payment_term_seeded(erp_session) -> None:
    term = erp_session.execute(
        select(models.PaymentTerm).where(models.PaymentTerm.code == "ADV100")
    ).scalar_one()
    assert term.is_default is True
