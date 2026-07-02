"""SQLite engine + session factory.

Default DB path: ``<repo-root>/data/local/erp.sqlite``.
Override with the ``ERP_DATA_DB`` env var (mirrors the engine's
``ERP_ENGINE_COUNTER_DB`` pattern) — useful for tests and packaged desktop builds.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

_DEFAULT_REL = Path("data") / "local" / "erp.sqlite"


def resolve_db_path() -> Path:
    """Return the SQLite file path, honoring ``ERP_DATA_DB`` and creating its dir."""
    override = os.environ.get("ERP_DATA_DB", "").strip()
    if override:
        path = Path(override)
    else:
        # src/erp_data/db/session.py -> parents[3] == repo root
        repo_root = Path(__file__).resolve().parents[3]
        path = repo_root / _DEFAULT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def make_engine(db_path: Path | str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLite engine at ``db_path`` (or the resolved default)."""
    path = Path(db_path) if db_path is not None else resolve_db_path()
    return create_engine(f"sqlite:///{path}", echo=echo, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a configured Session factory bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
