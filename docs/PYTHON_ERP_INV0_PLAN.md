# Sprint INV-0 — Plan / Schema Gate

Status: PLAN (no code). Approve before INV-0 code. Builds on the LOCKED engine
(`CONTRACT_v1`, `PROFORMA_v1`, A1 committed ebf16a0/b6e2f19). Scope = **caller/data
layer only** — the deterministic engine is NOT reopened.

Pre-approved assumptions (Codex): SQLAlchemy 2.x · SQLite · `.xlsx` · openpyxl · module
upload disabled (manifest scan only) · engine contract untouched · first module = existing
proforma/invoice engine.

Engine boundary reminder (CONTRACT_v1 §8.1): the engine never opens a DB. Everything below is
**caller-side**; it resolves data into a `CONTRACT_v1` payload, calls the engine, and persists
the result.

---

## 1. Directory layout

The engine stays pure; the new data layer is a **separate package** (`erp_data`) so the engine
never imports DB code. `erp_data` is reusable by the desktop caller now and any future Python
caller.

```
python-erp/
  src/
    erp_engine/                 # UNCHANGED deterministic engine (no DB, no runtime Excel)
      core/  modules/proforma/
    erp_data/                   # NEW — caller-side data layer
      db/
        base.py                 # DeclarativeBase + engine/session factory (SQLAlchemy 2.x)
        session.py              # get_session(); SQLite path resolution (env override like the counter)
        models.py               # all ORM models (§2) — or split per domain if it grows
        init_db.py              # create_all() bootstrap + seed lookups (payment_terms, docno_rules)
      imports/
        templates.py            # fixed template column specs (§4) + .xlsx generator (openpyxl)
        importer.py             # read → normalize → validate → upsert pipeline (§5)
        validators.py           # per-template row validators
      repositories/             # data-access + resolution helpers used by callers/UI/AI
        organizations.py parties.py products.py pricing.py
        permissions.py documents.py
      registry/
        loader.py               # scan modules/, read module.json (§7)
  adapters/
    cli.py                      # existing (PHP caller)
    desktop/                    # INV-1 (PySide6) — not in INV-0
  data/local/erp.sqlite         # desktop DB (GITIGNORED)   + existing var/counters.db
  templates/excel/*.xlsx        # generated fixed templates (or generated on demand)
  modules/invoice/module.json   # manifest registry
  docs/  tests/
```
`pyproject.toml` `[tool.hatch...packages]` adds `src/erp_data`. `data/` + `*.sqlite` gitignored.

## 2. SQLAlchemy model schema (SQLite; portable to Postgres/MySQL later)

Conventions: every table has `id` INTEGER PK (autoincrement), `status` ENUM(`active`,`archived`)
default `active` (soft-delete = archive; **no hard delete** for masters/documents, aligned with
the platform's Master-Data-First), `created_at`/`updated_at` timestamps. Money = `float` (v1,
per contract; Decimal = A3 later). Countries = ISO-3166 alpha-2, currency = ISO-4217.

| Table | PK | Key columns | FKs | Unique | Notes |
|---|---|---|---|---|---|
| **organizations** | id | `code`, `legal_name`, `org_type`(group\|company\|branch\|department), address, city, country, phone, email, tax_no, `default_currency`, bank_name, bank_account, iban, swift_code | `parent_id`→organizations.id (holding tree, nullable) | `code` | OUR seller companies (the `seller` side / `SELLER_CODE`). Bank fields denormalized for MVP (banks-as-parties richer model later). |
| **parties** | id | `party_type`(customer\|supplier\|bank\|consultant\|person\|carrier), `legal_name`, address, city, country, phone, email, tax_no, `default_discount_percent`(cust), `default_payment_term_code` | — | (party_type, tax_no) soft-unique* | Counterparties + persons (the `buyer` side + people). *tax_no may repeat/null → app-level dedupe, not a hard DB unique in v1. |
| **employees** | id | `username`, `password_hash`, `title`, status | `person_party_id`→parties.id (party_type=person) | `username`, `person_party_id` | Login users = a person promoted with credentials (matches the "select person → add title+password" flow). Naming (`employees` vs `users`) = open §9. |
| **employee_company_permissions** | id | `module_code`, `role`(admin\|user) | `employee_id`→employees.id, `organization_id`→organizations.id | (employee_id, organization_id, module_code) | THE permission model (§3). `organization_id` = the seller company the user may act FOR. |
| **products_services** | id | `code`, `description`, `hs_code`, `unit`, `item_type`(product\|service), `product_tax_percent`(nullable) | `organization_id`→organizations.id (nullable = shared) | `code` (per org scope — see §9) | Product/service master. |
| **price_lists** | id | `code`, `name`, `currency`, `effective_from`, `effective_to`(nullable) | `organization_id`→organizations.id (nullable=shared) | `code` | Effective-dated (§9 decision). |
| **price_list_items** | id | `unit_price`, `min_quantity`(nullable, for future tiers) | `price_list_id`→price_lists.id, `product_id`→products_services.id | (price_list_id, product_id, min_quantity) | Resolved unit price source. |
| **tax_rules** | id | `rule_type`(country_pair\|product_specific\|seller_default), `seller_country`(nullable), `buyer_country`(nullable), `rate`, `reason`(domestic_vat\|export_zero_vat\|reverse_charge\|seller_default_vat) | `product_id`(nullable), `organization_id`(nullable) | — | Caller-side tax data; the caller resolves a line's rate from these and passes it (or leaves null for the engine's built-in country_pair table). |
| **payment_terms** | id | `code`, `label`, `is_default`(bool) | — | `code` | Seed: `ADV100 / "%100 payment in advance"`. |
| **docno_rules** | id | `document_type`(quotation\|proforma_invoice\|commercial_invoice), `template`, `counter_scope` | `organization_id`→organizations.id | (organization_id, document_type) | **Per-type prefixes (QTN-/PRF-/INV-) live here.** Wiring them into the engine (which currently defaults to `PRF-`) is a later step — see §6/§9. |
| **documents** | id | `document_no`, `document_type`, `issue_date`, `valid_until`, `currency`, totals(subtotal/discount/freight/net/tax/grand), `snapshot_json` | `organization_id`→organizations.id, `buyer_party_id`→parties.id(nullable=manual), `created_by_employee_id`→employees.id | `document_no` | **IMMUTABLE snapshot** — `snapshot_json` stores the full engine result (parties+lines+totals+trace) at issue time. Corrections = new document, never edit. |
| **document_lines** | id | line_no, product_code, product_description, hs_code, quantity, unit, unit_price, discount_percent, discount_amount, tax_percent, tax_reason, tax_amount, line_total | `document_id`→documents.id | (document_id, line_no) | Mirror of engine `ResultLineItem` (queryable copy of the snapshot). |
| **import_batches** | id | `template_type`, `file_name`, total_rows, valid_rows, invalid_rows, `outcome`(completed\|completed_with_errors\|failed) | `created_by_employee_id`→employees.id (nullable) | — | One row per Upload run. |
| **import_errors** | id | `row_number`, `column_name`(nullable), `error_code`, `error_message` | `import_batch_id`→import_batches.id | — | Invalid rows are NOT imported; they land here. |

## 3. Permission model

`employee_company_permissions(employee_id, organization_id, module_code, role admin|user)` —
one person can hold different roles across companies:
```
Murat → Expertechnik GmbH / invoice.admin
        Kazakhstan Ltd    / invoice.user
        Dubai FZE         / (no row = no access)
```
Enforcement (caller/UI, INV-1 — INV-0 provides the queries):
- **Seller autocomplete** = `SELECT organizations WHERE id IN (permitted org_ids for this user + module='invoice')`. Only authorized companies appear.
- **Save gate** = re-check the permission on submit; unauthorized seller → Save disabled + red field. The engine never sees this (it gets an already-authorized, resolved payload).
- **admin vs user**: `user` can create documents for the company; `admin` can also manage that company's data (import, employees, price lists) — exact admin extras finalized in INV-1.

## 4. Excel template set (fixed columns; technical EN names; TR/EN helper text later)

| Template | Target | Columns |
|---|---|---|
| `companies.xlsx` | organizations | code, legal_name, parent_code, org_type, address, city, country, phone, email, tax_no, default_currency, bank_name, bank_account, iban, swift_code |
| `customers.xlsx` | parties(customer) | company_name, address, city, country, phone, email, tax_no, default_discount_percent, default_payment_term_code |
| `products.xlsx` | products_services | product_code, product_description, hs_code, unit, item_type, product_tax_percent, organization_code(optional) |
| `price_lists.xlsx` | price_lists + items | price_list_code, organization_code, product_code, currency, unit_price, min_quantity, effective_from, effective_to |
| `tax_rules.xlsx` | tax_rules | rule_type, seller_country, buyer_country, product_code, organization_code, rate, reason |
| `payment_terms.xlsx` | payment_terms | code, label, is_default |
| `docno_rules.xlsx` | docno_rules | organization_code, document_type, template, counter_scope |
| `employees.xlsx` | parties(person) | person_name, email, phone, tax_no, external_ref |

Notes: templates reference masters by **business code** (organization_code, product_code) not
numeric id, so an operator can fill them without knowing DB ids. Employee credentials
(username/password) + permissions are set in the **UI**, not bulk Excel (per the user's flow).

## 5. Import pipeline

```
1. read .xlsx (openpyxl)  [.csv auto-detect optional; column semantics fixed]
2. header check: columns must match the template spec exactly (no flexible mapping UI in v1)
3. per-row: normalize (trim, type-coerce, code lookups) → validate (required, enum, FK-by-code)
4. collect invalid rows → import_errors (row_number, column, code, message); INVALID ROWS NOT IMPORTED
5. valid rows → upsert into DB (by business code; insert or update the master)
6. write import_batches summary (total / valid / invalid / outcome)
7. runtime lookups (autocomplete/resolution) read the DB, never the raw Excel
```
Idempotent: re-uploading the same file upserts by code (no duplicate masters).

## 6. Engine integration boundary (explicit)

```
engine knows NOTHING about the DB.
caller (desktop/PHP):
  1. resolves seller (organizations) + buyer (parties) + products (products_services + price_list_items)
     + payment term + (optionally) line tax_percent from tax_rules
  2. builds a CONTRACT_v1 request payload (header/seller/buyer/ship_to/line_items/terms/banking/notes)
  3. calls the engine (in-process import in desktop, or the CLI adapter)
  4. receives the JSON ResponseEnvelope (result: document/parties/line_items/totals/trace)
  5. persists → documents (+ snapshot_json) + document_lines
```
Numbering: the engine generates the number with its built-in default (`PRF-…`) in INV-0. Making
it honor per-type `docno_rules` templates needs a small mechanism to pass the template/scope in
the payload or context — deferred (candidate amendment **A4**). INV-0 only STORES docno_rules.

## 7. Manifest loader

`modules/invoice/module.json`:
```json
{ "code": "invoice", "name": "Invoice", "version": "0.1.0",
  "engine_module": "proforma_invoice",
  "permissions": ["invoice.admin", "invoice.user"] }
```
Loader scans `modules/*/module.json` → an in-memory registry (code/name/version/permissions).
**Real upload DISABLED / "coming soon"** — a developer drops a folder + manifest; no arbitrary
code execution. Signed/versioned packages come much later.

## 8. Acceptance criteria (INV-0 done when…)

- `init_db` creates all tables in a fresh `data/local/erp.sqlite` (idempotent).
- All 8 templates generate as valid `.xlsx`.
- A sample `companies.xlsx` + `products.xlsx` import: valid rows land in DB, one deliberately
  bad row is reported in `import_errors` and NOT imported; `import_batches` summary correct.
- A permission query returns the authorized seller companies for a test user (+empty for an
  unauthorized one).
- The manifest loader lists the `invoice` module.
- `erp_engine` is byte-for-byte unchanged; all existing engine tests still pass (11).
- New `erp_data` unit tests (models init, one import happy-path, one import error-path, one
  permission query) pass.

## 9. Open decisions (pick during plan review)

1. **SQLite path**: `data/local/erp.sqlite` (repo-relative) + env override `ERP_DATA_DB` (mirror
   the existing `ERP_ENGINE_COUNTER_DB` pattern). Recommend yes.
2. **organizations vs parties**: kept separate (orgs = our seller companies; parties =
   counterparties/persons). **A company that is BOTH ours and a counterparty** (long-term) →
   note now, keep simple in MVP: it is two rows (an organization + a party) linked later by a
   nullable `parties.linked_organization_id`; NOT modeled in INV-0. Confirm.
3. **employees table name**: `employees` (vs `users`). Recommend `employees` (links a person +
   credentials + title).
4. **document snapshot strategy**: `documents.snapshot_json` (full engine result) + denormalized
   totals + `document_lines` rows. Recommend this (immutable JSON = legal truth; lines = query).
5. **price list effective dates**: `effective_from` required, `effective_to` nullable (open =
   current); resolution picks the row valid at issue_date. Recommend yes.
6. **products scope**: `products_services.organization_id` nullable (null = shared across the
   group) vs mandatory per-org. Recommend nullable/shared default. Confirm.
7. **per-type numbering (docno_rules → engine)**: store in INV-0; wire to engine later (A4).
   Confirm deferral.

---

**This doc: plan only. No code.** On approval (+ §9 picks) → INV-0 code, then a diff/test report.
