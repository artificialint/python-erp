"""INV-0: manifest loader finds the invoice module (scan-only, upload disabled)."""

from __future__ import annotations

import pytest

from erp_data.registry.loader import UPLOAD_ENABLED, find_module, load_manifests, upload_module


def test_manifest_loader_finds_invoice() -> None:
    codes = {m.code for m in load_manifests()}
    assert "invoice" in codes


def test_invoice_manifest_fields() -> None:
    invoice = find_module("invoice")
    assert invoice is not None
    assert invoice.name == "Invoice"
    assert invoice.engine_module == "proforma_invoice"
    assert "invoice.admin" in invoice.permissions
    assert "invoice.user" in invoice.permissions


def test_upload_is_disabled() -> None:
    assert UPLOAD_ENABLED is False
    with pytest.raises(NotImplementedError):
        upload_module()
