# Python ERP — Invoice Architecture v1

Status: ARCHITECTURE PLAN (no code yet). Approved decisions locked by Codex 2026-07-01.
Baseline specs (LOCKED, not overridden here): `template/docs/CONTRACT_v1.md`,
`template/docs/modules/PROFORMA_v1.md`. This doc adds the caller/data/UI layers around the
locked engine and records the sprint plan. Contract changes are proposed in §13, never made
silently (per CONTRACT_v1 §16 change discipline).

Product vision: one ERP core, three surfaces (desktop, online, chatbot). Manual first,
deterministic engine, AI later. Holding-scale flexibility (one person can invoice for many
companies; one module used by many companies).

---

## 1. CONTRACT_v1 as locked baseline

`CONTRACT_v1` is the portability artifact between the PHP web shell and the Python engine. We
treat it as **immutable baseline**. Key locked facts we build ON, never around:

- **Envelope**: request `{schema_version, module, request_id, context, payload}` → response
  `{status(ok|validation_error|execution_error), result, errors, warnings, meta}`.
- **Execution mode**: CLI-first (stdin JSON → stdout JSON, exit 0/2/3). HTTP deferred.
- **§8.1 caller-resolution boundary (THE pivotal rule)**: the engine does **not** open a DB,
  read Excel, call an LLM, or check permissions at request time. The **caller** (PHP shell or
  desktop) resolves seller/buyer/ship-to/product from its own DB and submits a *pre-resolved*
  payload. The engine only does deterministic validation, numbering, tax precedence, totals,
  and response shaping. → **Everything the user described (DB, org/permission model, Excel
  import, autocomplete, PDF) is CALLER-layer work, not engine work.**
- **Tax precedence** (locked): `line_override → product_specific → country_pair → seller_default`;
  missing domestic rule = execution error (never silent 0%), missing export rule = 0% + warning.
- **Document numbering** (locked): declarative templates (`{SELLER_CODE}{YEAR}{MONTH}{SEQ:N}`),
  `counter_scope` (e.g. `per_seller_annual`), atomic SQLite counters (`var/counters.db`).
- **Persistence split** (locked): runtime data = DB, counter = SQLite, Excel = import/export
  only (no live write-back).

## 2. Existing `proforma_invoice` engine = the invoice core

`python-erp` is NOT greenfield. `src/erp_engine/` already has the contract-mirroring skeleton:
- `modules/proforma/schema.py` — full Pydantic contract (Header/Seller/Buyer/ShipTo/LineItem/
  Terms/Banking/Notes → payload; Result with totals + `calculation_trace`). Currently the shape;
  `engine.py`/`rules.py` raise `NotImplementedError`.
- `core/data_loader.py` — the fixed Excel/CSV column contracts (sellers, customers, products,
  tax_rules, payment_terms, docno_rules), also stubbed.
- `adapters/cli.py` — the stdin/stdout JSON adapter the PHP shell calls.

**We extend this, we do not fork it.** The "invoice module" the user wants = this engine. The
engine's remaining work is filling the stubs per the locked contract (calc/tax/numbering).

## 3. document_type expansion (needs a contract amendment — see §13)

Codex decision: `quotation`, `proforma_invoice`, `commercial_invoice` are handled in one domain
as a `document_type`. **But** `schema.py` locks `document_type: Literal["proforma_invoice"]` and
the envelope locks `module: Literal["proforma_invoice"]`. Expanding them touches the locked
contract → filed as **Amendment Proposal A1 (§13)**. Until A1 is approved, v1 code ships
`proforma_invoice` only; quotation/commercial_invoice land the moment A1 is accepted. The three
share the same calc (totals/tax); they differ in label, numbering template, and a few legal
fields — so they are one engine, parameterized by `document_type`, not three modules.

## 4. Online decision — Option A (PHP staff panel remains the online UI)

- **Online invoice = the existing PHP platform** (`agentai.uno/{slug}/staff`), reusing the
  existing auth / tenant / staff / i18n / master registries. PHP builds the payload (resolving
  parties/products from the agentai MySQL master registries) and calls the engine via the CLI
  adapter (HTTP adapter later).
- **No new standalone Python/FastAPI web admin UI in v1.** FastAPI (`adapters/http`) arrives
  later purely for API / AI / third-party access — never to re-implement the web UI that PHP
  already provides.
- This matches CONTRACT_v1 (PHP = the reference caller) and avoids duplicating auth/tenant.

## 5. Desktop decision — PySide6 + SQLite

- **Desktop = native PySide6 app**, offline-capable, calling the *same* engine.
- **Desktop DB = SQLite** (`data/local/erp.sqlite`) via SQLAlchemy (proposed ORM — §12).
- The desktop is a **caller** (like PHP): it owns its DB, auth, permission model, Excel import,
  autocomplete resolution, and PDF. It resolves the payload, then calls the engine (in-process
  import, or via the CLI adapter) and renders the JSON result.

## 6. Data layer (CALLER-side; the engine stays DB-agnostic)

Because of §8.1, the DB schema lives in the callers, not the engine. Desktop implements it in
SQLite/SQLAlchemy; PHP maps the same concepts onto the existing agentai master registries. The
shared conceptual model (holding-ready):

```
organizations   group / company (holding tree; branch/department later)
parties          company · person · bank · consultant · customer · supplier (unified registry)
employees_users  linked person + login credentials (per-caller auth)
permissions      (user_id, company_id, module_code, role: admin|user)   -- §8
products         product/service master + attributes (hs_code, unit, tax metadata)
price_lists      per product/company/currency price entries
tax_rules        country_pair + product_specific + seller_default rows
payment_terms    code + label + default
docno_rules      seller_code + template + counter_scope
documents        issued quotation/proforma/commercial-invoice, IMMUTABLE snapshot
```

**Immutability principle (aligned with the platform's Master-Data-First):** an issued document
stores a **snapshot** of the resolved parties + line items + totals at issue time (the engine's
`result.parties` + `result.line_items` already are that snapshot). Master records may change
later; the document does not. Master records are archive-only (no hard delete).

## 7. Excel import strategy (fixed-template → validate → DB; runtime reads DB)

Per PROFORMA_v1 §7 + CONTRACT_v1 §14. Per data-admin section: **Download Template · Upload
Excel · Export Current Data**.

```
Download fixed-template .xlsx  (technical column names EN; helper text TR/EN)
User fills / paste-in their list
Upload .xlsx (or .csv; auto-detect format, fixed column semantics — no flexible mapping UI in v1)
Parser validates columns against the fixed template
Rows normalized; INVALID rows reported row-by-row
Valid rows written into the DB
Runtime lookups (autocomplete) read the DB, never the raw Excel
```

Templates (from the locked column contracts in `data_loader.py`): `sellers`, `customers`,
`products`, `tax_rules`, `payment_terms`, `docno_rules` (+ the user's Products&Services groups:
price lists, packing rules, technical data as later template families).

## 8. Permission model (CALLER-side; holding-ready)

```
PermissionAssignment
  user_id
  company_id       (an organization/company the user may act for)
  module_code      (e.g. "invoice")
  role             admin | user
```

One person → many companies → per-company, per-module role. Example:
```
Murat  →  Expertechnik GmbH / invoice.admin
          Kazakhstan Ltd    / invoice.user
          Dubai FZE         / (no access)
```
**Invoice UX enforcement (caller-side):** the "seller company" autocomplete only offers
companies the logged-in user is authorized for; an unauthorized seller keeps **Save disabled**
and marks the field with a red rectangle. The engine never sees this — it receives an
already-authorized, resolved payload.

## 9. Invoice MVP (end-to-end, desktop-first)

1. Add company (organization) + import customers + import products/price list (Excel).
2. Create employee/user → assign company + `invoice` role (admin/user).
3. Login (desktop, local credentials).
4. Open the full-page invoice form (PROFORMA_v1 §4 layout: header/seller/buyer/ship-to/lines/
   terms/banking/totals/notes/actions).
5. Seller autocomplete (permission-gated) · Buyer autocomplete · Product autocomplete →
   unit_price + description + hs_code + unit auto-fill from DB.
6. Enter quantities → engine computes totals + tax (deterministic).
7. Save → document persisted (immutable snapshot) with an engine-generated document number.
8. Open the document from the Documents list or the customer view.
9. Export/PDF (adapter-level — see §13 A2).

## 10. Adapter plan (one core, thin adapters)

```
adapters/cli.py     EXISTING — PHP shell calls it (stdin/stdout JSON). Stays the v1 online path.
adapters/desktop/   NEW      — PySide6 UI; resolves via SQLite; calls engine in-process.
adapters/http/      LATER    — FastAPI; API/AI/third-party only (NOT a web-UI rewrite).
adapters/ai/        LATER    — AI tools (search_company, search_product, create_quotation,
                               validate_invoice, generate_pdf) — thin wrappers over the engine.
modules/invoice/module.json  manifest registry (Codex's "+Upload module" idea, safe form):
                             the app scans modules/, reads manifests. Real upload = DISABLED /
                             "coming soon" in MVP (a dev drops a folder + manifest; no arbitrary
                             code execution). Signed/versioned packages come much later.
```
Proposed folder shape:
```
python-erp/
  src/erp_engine/{core, modules/invoice(=proforma)}   # locked engine + fills
  adapters/{cli.py, desktop/, http/(later), ai/(later)}
  data/local/erp.sqlite                                # desktop DB (+ var/counters.db)
  templates/excel/*.xlsx                               # fixed import templates
  modules/invoice/module.json                          # manifest registry
  docs/  tests/
```

## 11. Sprint plan

- **INV-0 — data + import foundation.** SQLite schema (SQLAlchemy models for §6), Excel template
  generation (§7 domains), import + row-level validation, `modules/` manifest loader. Engine:
  implement the locked calc (schema is done) — `engine.py`/`rules.py`/`data_loader.py` per
  CONTRACT_v1 + behavioral tests (the contract's §17 / PROFORMA §13 Step 2 targets).
- **INV-1 — desktop shell + invoice form.** PySide6 top-bar (Products&Services · Modules ·
  People&Companies · Employees&Access) + context sidebar; the full-page invoice form;
  seller/buyer/product autocomplete; permission-gated seller; totals live; **save quotation/
  proforma**; documents list.
- **INV-2 — PHP staff-panel wrapper.** Wire the existing staff panel form to the engine via the
  CLI adapter (Option A); reuse the agentai master registries for resolution.
- **INV-3 — AI tools.** `adapters/ai` tools over the same engine; chatbot "Create invoice /
  Continue manually" — never bypassing the deterministic core.

## 12. Open decisions (need a pick before / during INV-0)

1. **ORM**: SQLAlchemy (recommended — desktop SQLite ↔ future Postgres/MySQL with one model)
   vs raw sqlite3 + repository. Recommend **SQLAlchemy 2.x**.
2. **PDF renderer** (adapter-level, see §13 A2): WeasyPrint (HTML/CSS → PDF, reuses jinja2
   templates) vs ReportLab (programmatic). Recommend **WeasyPrint** for template reuse.
3. **Template language**: technical column names EN, helper/description text TR + EN. (Confirmed
   direction; lock the exact columns in INV-0.)
4. **Document numbering scope default**: `per_seller_annual` (per CONTRACT_v1 example) vs
   `per_company_per_doctype_annual`. Recommend **per_seller_annual** for v1, config-driven.
5. **Desktop packaging**: PyInstaller (single .exe) vs Briefcase vs MSI. Recommend **PyInstaller**
   for the first downloadable build; revisit for auto-update later.
6. **Money type**: contract uses `float` in v1 (documented); ERP correctness wants `Decimal`.
   CONTRACT_v1 §schema note anticipates a future switch. Flag as **A3** if we want Decimal now.

## 13. CONTRACT_v1 amendment proposals (NOT applied — await approval)

Per Codex: contract is locked; gaps become proposals, not edits.

- **A1 — expand `document_type` / module to cover quotation + commercial_invoice.** Change
  `Header.document_type` and `ResultDocument.document_type` from `Literal["proforma_invoice"]`
  to `Literal["quotation","proforma_invoice","commercial_invoice"]`; decide whether `module`
  stays `proforma_invoice` (calc identical) or becomes `invoice`. Per-type numbering templates
  (`QTN-…`, `PRF-…`, `INV-…`). Requires updating CONTRACT_v1 §4/§7.2/§11.2 + `schema.py` +
  tests together (CONTRACT_v1 §16). Codex already signalled intent to accept this.
- **A2 — PDF at the adapter layer.** PROFORMA_v1 lists PDF out of scope for the *engine* v1.
  Rendering the engine's JSON result to PDF in the **desktop/PHP adapter** does not touch the
  engine contract. Proposal: allow adapter-level PDF (WeasyPrint) in INV-1 without a contract
  change. (Confirm this reading is acceptable.)
- **A3 (optional) — money precision.** Switch `float` → `Decimal` for monetary fields. Bigger
  change; only if we want it before real invoicing. Default: keep `float` for v1 per contract.

## 14. Non-negotiables carried from the locked specs
Deterministic execution first · no LLM dependency for a successful invoice · Excel-friendly
onboarding · DB-backed runtime · fixed templates before flexible mapping · narrow scope before
automation · contract-first (no implementation drift).

---

**This doc: plan only. No code.** Next: on approval (+ picks for §12 and the A1/A2 proposals),
start **Sprint INV-0**.
