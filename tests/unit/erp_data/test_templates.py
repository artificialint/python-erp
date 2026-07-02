"""INV-0: template generator writes all 8 templates with the expected headers."""

from __future__ import annotations

from openpyxl import load_workbook

from erp_data.imports.templates import TEMPLATES, generate_all


def test_generate_all_templates(tmp_path) -> None:
    paths = generate_all(tmp_path)
    assert len(paths) == len(TEMPLATES) == 8
    for template_type, spec in TEMPLATES.items():
        path = tmp_path / f"{template_type}.xlsx"
        assert path.exists(), f"{template_type} not generated"
        worksheet = load_workbook(path).active
        headers = [cell.value for cell in worksheet[1]]
        assert headers == spec.columns, f"{template_type} header mismatch"
