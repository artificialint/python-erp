"""erp-engine — deterministic ERP execution engine.

See README.md for the locked architectural principle:
  Excel = user-facing import/export surface.
  DB    = runtime source of truth.

Public API surface is module-scoped — import what you need from
`erp_engine.modules.<module_name>`, not from this package root.
"""

__version__ = "0.1.0"
