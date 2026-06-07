# erp-engine

Deterministic ERP execution engine for the AgentAI UNO platform.

> **Mimari prensip (locked 2026-06-06):**
> **Excel = user-facing import/export surface.**
> **DB = runtime source of truth.**
> AI is an optional orchestration layer that calls this engine; the engine
> itself runs without AI and produces identical output for identical input.

## Status

**v0.1.0 — skeleton phase.**

This repo currently contains only the project scaffold. The first module
(Proforma Invoice) lands once the spec stabilises:

- Specs: see `docs/PROFORMA_v1.md` and `docs/CONTRACT_v1.md` once Codex
  publishes them.
- Implementation: lands in `src/erp_engine/modules/proforma/` after spec
  review.

Do not call any function in this package yet — every public entry point
raises `NotImplementedError` and exists only to define the import shape
that the spec will fill.

## Sibling projects

This repo is one of three layers in the AgentAI UNO platform:

| Layer | Repo | Role |
|---|---|---|
| Web shell | `agentai` (a.k.a. template) | PHP admin/auth/customer panel, form rendering, session, embed widget |
| **ERP engine** | **this repo** | Deterministic business logic (Excel readers, rule evaluation, document generation) |
| AI layer | Hosted inside the web shell for now | LLM-driven orchestration (chat signup, AI Assistant chat). Logical boundary documented; physical extraction is a later sprint. |

The web shell invokes the engine via a CLI adapter (stdin/stdout JSON).
A future HTTP adapter (FastAPI) is planned but not in v1 scope.

## Local quick-start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# Clone
git clone <repo-url> python-erp
cd python-erp

# Install with uv
uv venv
uv pip install -e ".[dev]"

# Run tests (currently only smoke imports)
uv run pytest

# Lint
uv run ruff check .
```

## Architecture (high level)

```
┌─────────────────────────────────┐
│ Adapter layer                   │
│ - adapters/cli.py  (stdin/JSON) │
│ - adapters/http.py (later)      │
└──────────────┬──────────────────┘
               │
               ▼  Pydantic-validated input
┌─────────────────────────────────┐
│ Engine layer (the library)      │
│ src/erp_engine/                 │
│ ├── modules/proforma/           │
│ │   ├── engine.py    business   │
│ │   ├── schema.py    contracts  │
│ │   └── rules.py     evaluation │
│ └── core/                       │
│     └── data_loader.py  Excel I/O│
└──────────────┬──────────────────┘
               │
               ▼  JSON result + preview HTML
┌─────────────────────────────────┐
│ Caller (PHP shell, desktop UI,  │
│ test harness)                   │
└─────────────────────────────────┘
```

## License

Proprietary. Internal use only at this stage.
