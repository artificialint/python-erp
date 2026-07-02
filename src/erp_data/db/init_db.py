"""Create all tables + seed constant lookups + a one-call bootstrap helper."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from erp_data.db import models  # noqa: F401 — register all models on Base.metadata
from erp_data.db.base import Base
from erp_data.db.session import make_engine, make_session_factory


def init_db(engine: Engine) -> None:
    """Create every erp_data table (idempotent)."""
    Base.metadata.create_all(engine)


def seed_defaults(session: Session) -> None:
    """Seed constant lookup rows (idempotent)."""
    existing = session.execute(
        select(models.PaymentTerm).where(models.PaymentTerm.code == "ADV100")
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            models.PaymentTerm(code="ADV100", label="%100 payment in advance", is_default=True)
        )
        session.commit()


def bootstrap(db_path: Path | str | None = None) -> tuple[Engine, sessionmaker[Session]]:
    """Create the engine, all tables, seed defaults; return (engine, session_factory)."""
    engine = make_engine(db_path)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        seed_defaults(session)
    return engine, session_factory
