# Python ERP

Deterministic ERP engine for AgentAI UNO, with a JSON/CLI boundary, reusable
data/import services and a PySide6 desktop prototype. AI is an optional caller;
the engine calculates the same results for the same business inputs.

**Excel is the import/export surface; the database is the runtime source of truth.**

## Current scope

Implemented: invoice validation/calculation, grouped tax and A7 money rounding,
A4-A6 numbering, SQLAlchemy/SQLite data services, Excel import templates,
seller permissions, product/price lookup and the desktop invoice-form MVP.
`document_type` selects quotation, proforma or commercial invoice under the
existing `proforma_invoice` module discriminator.

The complete online lifecycle, PDF/XLSX output, AI tools, UNO orchestration and
installable desktop distribution remain in the [master plan](docs/ERP_PLATFORM_MASTER_PLAN.md).
Supported currencies are TRY, USD, EUR and GBP. The conservative document amount
bound is exclusive at `1e13`; see the [A7 contract](docs/CONTRACT_A7_MONEY_PRECISION.md).

## Install and invoke

Python 3.11+ is required. In an existing development environment, install the
project and test dependencies with `python -m pip install -e ".[dev]"`.

The installed CLI reads one JSON request from stdin and writes one response to
stdout:

```text
erp-engine --module proforma_invoice
```

Alternatively use `python -m adapters.cli --module proforma_invoice`. For a
source-tree invocation without an installation, explicitly set `PYTHONPATH` to
both `<repo>/src` and `<repo>` using the operating system's path separator (`;`
on Windows, `:` on Linux). The PHP process owner must supply this environment or
install the package; pytest's configured import path is not a CLI installation.

Exit codes: `0` success, `2` validation error, `3` execution/transport error.

## Validation and private data

Run `python -m pytest -q -p no:cacheprovider` and `python -m adapters.desktop.smoke`
with `TEMP`/`TMP` directed to an approved archive path, `PYTHONDONTWRITEBYTECODE=1`,
and `ERP_DATA_DB`/`ERP_ENGINE_COUNTER_DB` directed to disposable archive files.
Test tools may create temporary subdirectories only where explicitly authorized.
Never point pytest `--basetemp` at an existing valuable directory: it is cleared.
Lint without leaving cache: `python -m ruff check --no-cache .`.

`data/` and `var/` hold ignored private/runtime files. Never commit databases,
credentials, customer spreadsheets, caches or generated reports.

Shared request/expected-result cases are in
[`tests/fixtures/a7_contract_cases.json`](tests/fixtures/a7_contract_cases.json),
with [projection/replay instructions](tests/fixtures/A7_FIXTURES.md).

## Architecture and contracts

- [`src/erp_engine`](src/erp_engine): deterministic validation, numbering and calculation.
- [`src/erp_data`](src/erp_data): persistence, permissions, lookup, import and assembly.
- [`adapters/cli.py`](adapters/cli.py): stdin/stdout JSON adapter.
- [`adapters/desktop`](adapters/desktop): local application adapter and UI.
- [Invoice architecture](docs/PYTHON_ERP_INVOICE_ARCHITECTURE_v1.md) and
  [A4](docs/CONTRACT_A4_CUSTOMER_NUMBERING.md),
  [A5](docs/CONTRACT_A5_RENDER_ONLY_NUMBERING.md),
  [A6](docs/CONTRACT_A6_LIFECYCLE_NUMBERING.md),
  [A7](docs/CONTRACT_A7_MONEY_PRECISION.md) amendments.

The baseline CONTRACT_v1/PROFORMA_v1 documents currently live in the sibling
`agentai-web/docs` tree. Web owns authorization, tenant isolation, online
transactions, immutable snapshots and generated files. UNO owns orchestration;
neither caller duplicates engine arithmetic. See the master plan for boundaries.

Proprietary; internal use.
