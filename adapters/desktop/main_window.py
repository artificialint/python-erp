"""Main window: employee selector (top) + permission-scoped sidebar + invoice page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from adapters.desktop.pages.invoice_page import InvoicePage
from erp_data.db import models

_MODULE_LABELS = {"invoice": "Invoice"}


class MainWindow(QMainWindow):
    def __init__(self, session: Session) -> None:
        super().__init__()
        self._session = session
        self.setWindowTitle("UNO ERP - Desktop (MVP)")

        central = QWidget()
        outer = QVBoxLayout(central)

        top = QHBoxLayout()
        top.addWidget(QLabel("Employee:"))
        self.employee = QComboBox()
        rows = session.execute(
            select(models.Employee, models.Party.legal_name).join(
                models.Party, models.Party.id == models.Employee.person_party_id
            )
        ).all()
        for employee, person_name in rows:
            self.employee.addItem(f"{person_name} ({employee.username})", employee.id)
        top.addWidget(self.employee)
        top.addStretch(1)
        outer.addLayout(top)

        body = QHBoxLayout()
        self.sidebar = QListWidget()
        self.sidebar.setMaximumWidth(200)
        self.stack = QStackedWidget()
        self.invoice_page = InvoicePage(session)
        self.stack.addWidget(self.invoice_page)
        body.addWidget(self.sidebar)
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        self.setCentralWidget(central)

        self.employee.currentIndexChanged.connect(self._on_employee_changed)
        self.sidebar.currentTextChanged.connect(self._on_sidebar_changed)

        if self.employee.count():
            self._on_employee_changed()

    def _on_employee_changed(self, *_: object) -> None:
        employee_id = self.employee.currentData()
        if employee_id is None:
            return
        module_codes = self._session.execute(
            select(models.EmployeeCompanyPermission.module_code)
            .where(models.EmployeeCompanyPermission.employee_id == employee_id)
            .distinct()
        ).scalars().all()
        self.sidebar.clear()
        for code in sorted(set(module_codes)):
            self.sidebar.addItem(_MODULE_LABELS.get(code, code.title()))
        self.invoice_page.set_employee(employee_id)
        if self.sidebar.count():
            self.sidebar.setCurrentRow(0)

    def _on_sidebar_changed(self, text: str) -> None:
        if text == "Invoice":
            self.stack.setCurrentWidget(self.invoice_page)
