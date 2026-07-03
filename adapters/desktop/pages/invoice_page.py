"""Invoice form page (PySide6).

Permission-scoped: the Seller dropdown only lists the current employee's authorized
organizations. Save is disabled until seller + buyer + >=1 line are valid, and it
calls the headless ``service.create_document`` orchestrator. Programmatic hooks
(``set_seller`` / ``set_buyer_by_id`` / ``add_line`` / ``save``) make the page
driveable headlessly (offscreen smoke).
"""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session

from adapters.desktop import service
from adapters.desktop.widgets.autocomplete import make_completer
from erp_data import assembly
from erp_data.repositories import lookups, permissions

DOCUMENT_TYPES = ["quotation", "proforma_invoice", "commercial_invoice"]


class InvoicePage(QWidget):
    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        self._employee_id: int | None = None
        self._buyer_id: int | None = None
        self._buyer_by_name: dict[str, int] = {}
        self._product_desc: dict[str, str] = {}
        self._lines: list[service.InvoiceLineInput] = []
        self.last_outcome: service.InvoiceOutcome | None = None
        self.last_error: str | None = None
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        header = QGroupBox("Document")
        form = QFormLayout(header)
        self.doc_type = QComboBox()
        self.doc_type.addItems(DOCUMENT_TYPES)
        self.doc_type.setCurrentText("proforma_invoice")
        self.issue_date = QDateEdit()
        self.issue_date.setDate(QDate.currentDate())
        self.issue_date.setCalendarPopup(True)
        self.seller = QComboBox()
        self.buyer = QLineEdit()
        self.buyer.setPlaceholderText("customer name")
        form.addRow("Document type", self.doc_type)
        form.addRow("Issue date", self.issue_date)
        form.addRow("Seller", self.seller)
        form.addRow("Buyer", self.buyer)
        root.addWidget(header)

        entry = QGroupBox("Add line")
        row = QHBoxLayout(entry)
        self.product = QLineEdit()
        self.product.setPlaceholderText("product code")
        self.product_desc = QLabel("")
        self.qty = QDoubleSpinBox()
        self.qty.setMaximum(1e9)
        self.qty.setValue(1)
        self.unit_price = QDoubleSpinBox()
        self.unit_price.setMaximum(1e12)
        self.unit_price.setDecimals(2)
        self.add_btn = QPushButton("Add line")
        row.addWidget(QLabel("Product"))
        row.addWidget(self.product)
        row.addWidget(self.product_desc)
        row.addWidget(QLabel("Qty"))
        row.addWidget(self.qty)
        row.addWidget(QLabel("Unit price"))
        row.addWidget(self.unit_price)
        row.addWidget(self.add_btn)
        root.addWidget(entry)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Product", "Description", "Qty", "Unit price"])
        root.addWidget(self.table)

        self.save_btn = QPushButton("Save")
        self.save_btn.setEnabled(False)
        root.addWidget(self.save_btn)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        root.addWidget(self.result)

        self.add_btn.clicked.connect(self._on_add_clicked)
        self.save_btn.clicked.connect(self.save)
        self.buyer.textChanged.connect(self._on_buyer_changed)
        self.product.editingFinished.connect(self._on_product_selected)
        self.seller.currentIndexChanged.connect(self._on_seller_changed)

    # ── population ────────────────────────────────────────────────────
    def set_employee(self, employee_id: int) -> None:
        self._employee_id = employee_id
        self.seller.clear()
        for org in permissions.permitted_organizations(self._session, employee_id, "invoice"):
            self.seller.addItem(f"{org.code} - {org.legal_name}", org.code)

        customers = lookups.search_parties(self._session, "")
        self._buyer_by_name = {c.legal_name: c.id for c in customers}
        self.buyer.setCompleter(make_completer(list(self._buyer_by_name)))

        products = lookups.search_products(self._session, "")
        self._product_desc = {p.code: (p.description or "") for p in products}
        self.product.setCompleter(make_completer([p.code for p in products]))

        self._buyer_id = None
        self.buyer.clear()
        self._lines.clear()
        self.table.setRowCount(0)
        self.result.setText("")
        self._update_save_enabled()

    def current_seller_code(self) -> str | None:
        return self.seller.currentData() if self.seller.count() else None

    # ── programmatic hooks (used by the offscreen smoke) ──────────────
    def set_seller(self, code: str) -> bool:
        for i in range(self.seller.count()):
            if self.seller.itemData(i) == code:
                self.seller.setCurrentIndex(i)
                return True
        return False

    def set_buyer_by_id(self, party_id: int) -> None:
        name = next((n for n, pid in self._buyer_by_name.items() if pid == party_id), None)
        self._buyer_id = party_id
        if name:
            self.buyer.setText(name)
        self._update_save_enabled()

    def add_line(self, product_code: str, quantity: float, unit_price: float | None = None) -> None:
        line = service.InvoiceLineInput(
            product_code=product_code, quantity=quantity, unit_price=unit_price
        )
        self._lines.append(line)
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(product_code))
        self.table.setItem(r, 1, QTableWidgetItem(self._product_desc.get(product_code, "")))
        self.table.setItem(r, 2, QTableWidgetItem(str(quantity)))
        self.table.setItem(r, 3, QTableWidgetItem("" if unit_price is None else str(unit_price)))
        self._update_save_enabled()

    # ── slots ─────────────────────────────────────────────────────────
    def _on_seller_changed(self, *_: object) -> None:
        self._update_save_enabled()

    def _on_buyer_changed(self, text: str) -> None:
        self._buyer_id = self._buyer_by_name.get(text.strip())
        self._update_save_enabled()

    def _on_product_selected(self) -> None:
        code = self.product.text().strip()
        self.product_desc.setText(self._product_desc.get(code, ""))
        seller_code = self.current_seller_code()
        if code and seller_code:
            price = lookups.resolve_unit_price(
                self._session, product_code=code, seller_code=seller_code
            )
            if price is not None:
                self.unit_price.setValue(float(price))

    def _on_add_clicked(self) -> None:
        code = self.product.text().strip()
        if not code:
            return
        price = self.unit_price.value()
        self.add_line(code, self.qty.value(), price if price > 0 else None)
        self.product.clear()
        self.product_desc.setText("")
        self.qty.setValue(1)
        self.unit_price.setValue(0)

    def _update_save_enabled(self) -> None:
        ok = bool(self.current_seller_code()) and self._buyer_id is not None and bool(self._lines)
        self.save_btn.setEnabled(ok)

    # ── save ──────────────────────────────────────────────────────────
    def save(self) -> service.InvoiceOutcome | None:
        self.last_error = None
        seller_code = self.current_seller_code()
        if not seller_code or self._buyer_id is None or not self._lines:
            self.last_error = "seller, buyer and at least one line are required"
            self.result.setText(self.last_error)
            return None
        form = service.InvoiceFormInput(
            seller_code=seller_code,
            buyer={"party_id": self._buyer_id},
            lines=list(self._lines),
            document_type=self.doc_type.currentText(),
            issue_date=self.issue_date.date().toString("yyyy-MM-dd"),
        )
        try:
            outcome = service.create_document(
                self._session, employee_id=self._employee_id, form=form
            )
        except (assembly.AssemblyError, service.ServiceError) as exc:
            self.last_error = str(exc)
            self.result.setText(f"Error: {exc}")
            return None
        self.last_outcome = outcome
        self.result.setText(
            f"Saved {outcome.document_no} ({outcome.document_type}) — "
            f"grand total {outcome.grand_total} {outcome.currency or ''}"
        )
        # reset lines for the next document
        self._lines.clear()
        self.table.setRowCount(0)
        self._update_save_enabled()
        return outcome
