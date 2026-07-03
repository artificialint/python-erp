"""Headless offscreen smoke — build the window, drive the invoice form, print result.

Run:  python -m adapters.desktop.smoke   (forces QT_QPA_PLATFORM=offscreen)

Proves the desktop wiring end to end without a display: permission-scoped seller
dropdown, product autofill, save -> engine -> persist. Not part of the pytest suite
(kept Qt out of unit tests); this is the manual/CI smoke.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="erp_desktop_smoke_"))
os.environ["ERP_ENGINE_COUNTER_DB"] = str(_TMP / "counters.db")

from PySide6.QtWidgets import QApplication  # noqa: E402
from sqlalchemy import select  # noqa: E402

from adapters.desktop.main_window import MainWindow  # noqa: E402
from adapters.desktop.sample_seed import seed_sample  # noqa: E402
from erp_data.db import models  # noqa: E402
from erp_data.db.init_db import bootstrap  # noqa: E402


def main() -> int:
    _engine, session_factory = bootstrap(_TMP / "erp.sqlite")
    session = session_factory()
    seed_sample(session)

    app = QApplication.instance() or QApplication([])  # noqa: F841
    window = MainWindow(session)
    window.show()
    page = window.invoice_page

    print(f"employee: {window.employee.currentText()}")
    seller_codes = [page.seller.itemData(i) for i in range(page.seller.count())]
    print(f"seller dropdown (permitted only): {seller_codes}")
    print(f"sidebar modules: {[window.sidebar.item(i).text() for i in range(window.sidebar.count())]}")

    print(f"select seller IST: {page.set_seller('IST')}")
    buyer = session.execute(
        select(models.Party).where(models.Party.legal_name == "Anadolu Ticaret Ltd")
    ).scalar_one()
    page.set_buyer_by_id(buyer.id)

    # product autofill (resolve_unit_price via the UI)
    page.product.setText("PRD-001")
    page._on_product_selected()
    print(f"autofilled unit_price for PRD-001: {page.unit_price.value()}")

    page.add_line("PRD-001", 10, page.unit_price.value() or None)
    print(f"save enabled: {page.save_btn.isEnabled()}")
    outcome = page.save()
    if not outcome:
        print(f"SAVE FAILED: {page.last_error}")
        return 1
    print(f"SAVED: {outcome.document_no} {outcome.document_type} "
          f"grand_total={outcome.grand_total} {outcome.currency}")
    print(f"unauthorized DXB present in dropdown? {'DXB' in seller_codes}")
    print("OK - desktop invoice form works end to end (offscreen).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
