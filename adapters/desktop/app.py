"""Desktop entrypoint.

Run:  python -m adapters.desktop.app
Bootstraps the SQLite DB (default data/local/erp.sqlite or ERP_DATA_DB), seeds a
sample dataset on first run, then opens the window.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]  # adapters/desktop/app.py -> repo root
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from adapters.desktop.main_window import MainWindow  # noqa: E402
from adapters.desktop.sample_seed import seed_sample  # noqa: E402
from erp_data.db.init_db import bootstrap  # noqa: E402


def main() -> int:
    _engine, session_factory = bootstrap()
    session = session_factory()
    seed_sample(session)

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(session)
    window.resize(940, 640)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
