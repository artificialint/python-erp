"""Proforma Invoice module.

Public entry point: `create_proforma(payload)`.

Spec references (filled by Codex during P1):
  - docs/PROFORMA_v1.md   — field list, data sources, import/export flow
  - docs/CONTRACT_v1.md   — JSON input/output shape, error codes

Until those land, the engine stub raises NotImplementedError on every call.
"""

from .engine import create_proforma

__all__ = ["create_proforma"]
