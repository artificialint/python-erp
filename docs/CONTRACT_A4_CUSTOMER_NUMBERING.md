# CONTRACT Amendment A4 — Customer-Anchored Document Numbering

**Status:** AMENDMENT SPEC (plan) — approved-in-principle by Codex 2026-07-05. **No engine code until explicit code-phase GO.**
**Amends:** `template/docs/CONTRACT_v1.md` §10 (Document Number Contract), §11.2 (document block), §11.3 (parties/buyer), §11.6 (calculation trace). Convention = inline amendment note in CONTRACT_v1.md, as A1 (2026-07-01) did.
**Implements in:** `src/erp_engine/modules/proforma/rules.py` (numbering) + `engine.py` (call site) + tests.
**Companion (caller/sprint):** `agentai-web/docs/INV_2C_CUSTOMER_NUMBERING_PLAN.md`.
**Principle:** *customer_no = human-readable label; SEQ = seller-scoped legal ledger sequence.* Additive + backward-compatible.

---

## A4.1 What changes (summary)
1. **New tokens** in §10: `{CUSTOMER_NO}`, `{YY}` (2-digit year), `{MM}` (2-digit month, alias of `{MONTH}`).
2. **New `counter_scope`:** `per_seller_doctype_monthly` — scope key = `tenant_key | seller_code | document_type | YYYY-MM`.
3. **`tenant_key` threaded into every scope key** (multi-tenant isolation fix). **`context.customer_id` is the tenant namespace for numbering** — no separate `tenant_key` field is added; the request context already carries the tenant boundary, so a redundant field is deliberately avoided. Absent → legacy key (backward compat).
4. **`buyer.customer_no`** added to the input parties/buyer block; **`document_type`** (A1, existing) becomes a counter-scope dimension.
5. **Validation:** `{CUSTOMER_NO}` in template + no `buyer.customer_no` → field-targeted error `customer_no_required`. Never blank.
6. **Defaults unchanged:** engine default stays `PRF-{SELLER_CODE}-{YEAR}-{SEQ:5}` + `per_seller_annual`. The product default `{CUSTOMER_NO}{YY}{MM}{SEQ:3}` + `per_seller_doctype_monthly` lives in the **caller** config, not the engine.

## A4.2 §10 token table — proposed amended text
```
### Supported token syntax
- {SELLER_CODE}
- {CUSTOMER_NO}   (A4, 2026-07-xx) — buyer master number from buyer.customer_no
- {YEAR}          — 4-digit year
- {YY}            (A4) — 2-digit year
- {MONTH}         — 2-digit month
- {MM}            (A4) — 2-digit month (alias of {MONTH})
- {SEQ:N}         — N-wide zero-padded, seller-scoped ledger sequence
- {RANDOM:N}      if later enabled (still not implemented)

### Counter scopes
- per_seller_annual            {tenant}|{seller}|{year}
- per_seller_monthly           {tenant}|{seller}|{year}-{mm}
- per_seller_doctype_monthly   (A4) {tenant}|{seller}|{document_type}|{year}-{mm}
- global_annual                {tenant}|GLOBAL|{year}
Every scope is tenant-prefixed (A4). Missing tenant_key → legacy un-prefixed key
(backward compatibility for existing single-tenant counters).

### Example (A4 product default — configured caller-side)
{ "template": "{CUSTOMER_NO}{YY}{MM}{SEQ:3}",
  "counter_scope": "per_seller_doctype_monthly" }
→ customer_no 104, 2026-07, seq 1  ⇒  1042607001

Separators are literals in the template: "{CUSTOMER_NO}-{YY}-{MM}-{SEQ:3}" ⇒ 104-26-07-001
```

## A4.3 Engine function-signature changes (`rules.py`)
**`generate_document_number`** — add keyword params (all optional → back-compat):
```
def generate_document_number(*, seller_code, issue_date,
        template=DEFAULT_DOC_NUMBER_TEMPLATE,
        counter_scope=DEFAULT_COUNTER_SCOPE,
        customer_no: str | int | None = None,   # A4 — from buyer.customer_no
        document_type: str | None = None,       # A4 — scope dimension
        tenant_key: str | None = None,          # A4 — counter isolation
        db_path=None) -> str
```
Rendering additions (after existing SELLER_CODE/YEAR/MONTH/SEQ):
- `{CUSTOMER_NO}` → `str(customer_no)`; if token present and `customer_no` is None/"" → raise the contract validation error (do **not** render blank).
- `{YY}` → `f"{issue_date.year % 100:02d}"`.
- `{MM}` → `f"{issue_date.month:02d}"` (same as `{MONTH}`).

**`_build_scope_key`** — accept `tenant_key` + `document_type`; prefix tenant; add the new scope:
```
tp = f"{tenant_key}|" if tenant_key else ""          # legacy fallback when empty
per_seller_annual          -> f"{tp}{seller}|{year}"
per_seller_monthly         -> f"{tp}{seller}|{year}-{mm}"
per_seller_doctype_monthly -> f"{tp}{seller}|{document_type}|{year}-{mm}"   # A4
global_annual              -> f"{tp}GLOBAL|{year}"
```
`_next_seq` / SQLite `doc_counter` / atomic `BEGIN IMMEDIATE` — **unchanged** (only the key string changes). The atomic increment guarantee (§10 persistence rule) is preserved.

## A4.4 Envelope / result contract
- **Input §11.3 buyer:** add `customer_no` (int, nullable). Required only when the resolved `template` uses `{CUSTOMER_NO}`.
- **Input numbering context:** caller passes `tenant_key`, `document_type` (existing), `template`, `counter_scope`.
- **Result §11.6 calculation_trace:** already emits `document_number_template` + `counter_scope`; A4 additionally records the resolved `scope_key` dimensions used (tenant/seller/document_type/period) for auditability — **no PII, just the counter namespace**.
- **Error §12:** `customer_no_required` (field: `buyer.customer_no`) when the template needs it and it's absent.

## A4.5 Backward compatibility guarantees
- No `customer_no`/`tenant_key`/`document_type` passed + PRF template + `per_seller_annual` ⇒ identical output & scope key to pre-A4. Proven by test #1.
- New tokens only activate when present in the template. New scope only when named. Tenant prefix only when `tenant_key` supplied.
- CONTRACT_v1 version bump per amendment convention; §10/§11 inline notes tagged `(A4, 2026-07-xx)`.

## A4.6 Tests (pytest, engine — authored at code phase, mirrors INV-2C §6)
1. Legacy PRF `per_seller_annual` renders byte-identical (no new params).
2. `{CUSTOMER_NO}` renders from `customer_no`.
3. `{YY}`/`{MM}` render (2026-07 → 26/07).
4. **Two buyers, same tenant+seller+doctype+month → shared SEQ 001,002** (no per-buyer reset) — the Q1 legal guarantee.
5. **Two tenants, same seller_code → isolated sequences** (both 001) — the Q4 fix.
6. `{CUSTOMER_NO}` in template + missing `buyer.customer_no` → `customer_no_required`, no blank.
7. Month rollover resets SEQ under `per_seller_doctype_monthly` (…07001 → …08001).
8. `document_type` separates counters (invoice vs proforma independent).
9. (guard) concurrent `_next_seq` stays atomic — no duplicate SEQ.

## A4.7 Non-goals (A4)
Per-seller-entity numbering override; `{RANDOM:N}`; numbering-config admin editor UI; document persistence/`document_no` snapshot (INV-4). Caller wiring (config storage, preview-vs-issue allocation separation) is specified in the INV-2C companion, not here.

---
**Engine code (rules.py/engine.py/tests) begins only on Codex code-phase GO.** This doc is the amendment blueprint; at code phase its §A4.2 text is applied inline to `template/docs/CONTRACT_v1.md` §10.
