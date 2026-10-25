"""Desktop input precision — A7 rule 9 at the widget boundary.

CONTRACT_A7_MONEY_PRECISION.md rule 9: ``quantity`` and ``unit_price`` are inputs,
not money, and are not forced to scale 2. The engine honours that, but the
desktop form fed it through ``QDoubleSpinBox`` widgets left at two decimals, so a
valid unit price of ``0.105`` became ``0.11`` before the engine ever saw it —
silently, because ``setValue`` rounds to the widget's ``decimals()``.

These tests drive the real widgets through ``_on_add_clicked`` and assert what
reaches ``InvoiceLineInput``, which is the value the engine will price.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from adapters.desktop.pages import invoice_page  # noqa: E402
from adapters.desktop.pages.invoice_page import InvoicePage  # noqa: E402


@pytest.fixture()
def page(flow_session):
    QApplication.instance() or QApplication([])
    widget = InvoicePage(flow_session)
    yield widget
    widget.deleteLater()


def _add(page: InvoicePage, quantity: float, unit_price: float):
    page.product.setText("PRD-PREC")
    page.qty.setValue(quantity)
    page.unit_price.setValue(unit_price)
    page._on_add_clicked()
    return page._lines[-1]


def test_unit_price_beyond_two_decimals_reaches_the_engine_input(page) -> None:
    line = _add(page, 1, 0.105)
    assert line.unit_price == 0.105


def test_fractional_quantity_beyond_two_decimals_survives(page) -> None:
    # The schema accepts any finite quantity > 0; three decimals is the usual
    # scale for kg / m / l measures.
    line = _add(page, 2.125, 10)
    assert line.quantity == 2.125


def test_input_scale_is_explicit_and_documented(page) -> None:
    # The digit counts are a deliberate choice, not the QDoubleSpinBox default.
    assert page.unit_price.decimals() == invoice_page.UNIT_PRICE_DECIMALS == 4
    assert page.qty.decimals() == invoice_page.QUANTITY_DECIMALS == 4


def test_input_beyond_the_chosen_scale_is_rounded_to_it(page) -> None:
    # Pins the boundary of the choice: a fifth decimal is rounded by the widget,
    # so the limit is visible in the suite rather than discovered on an invoice.
    # (0.12346 / 1.00006, not ...45: a binary float tie would make the
    # rounding direction ambiguous.)
    line = _add(page, 1.00006, 0.12346)
    assert line.unit_price == 0.1235
    assert line.quantity == 1.0001
