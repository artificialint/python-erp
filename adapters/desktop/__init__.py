"""PySide6 desktop adapter (INV-1).

The ONLY layer that imports both erp_data and erp_engine (via ``service``). Keep Qt
imports out of ``service.py`` so the orchestrator stays headless-testable.
"""
