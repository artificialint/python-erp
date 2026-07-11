# CONTRACT Amendment A6 — Canonical Lifecycle Numbering (2026-07-10)

**Status:** implemented (additive). Engine stays pure calc (CONTRACT_v1 §8.1 untouched).
**Companion:** `agentai-web/docs/CANONICAL_INVOICE_PRODUCT_ALGORITHM.md` §9 (numbering LOCKED).

## What A6 adds
1. **`{DOCUMENT_TYPE_CODE}` render token** — the canonical document-family digit:
   `quotation → 1 · proforma_invoice → 2 · commercial_invoice → 3` (`DOCUMENT_TYPE_CODES`).
   Unknown/missing `document_type` with the token present → **`DocumentTypeCodeRequiredError`**,
   raised **before** the counter is touched (no sequence burned) — same principle as the A4
   `{CUSTOMER_NO}` guard.
2. **`per_seller_customer_monthly` counter scope** (`SCOPE_PER_SELLER_CUSTOMER_MONTHLY`) —
   key = `{tenant}|{seller}|{customer_no}|{YYYY-MM}`. **`document_type` is deliberately NOT
   in the key**: Quotation/Proforma/Commercial share ONE ledger (the lifecycle base).
   `customer_no` is **required** for this scope (`CustomerNoRequiredError` pre-counter).
3. **`render_document_number` now uses `document_type`** — previously accepted-but-unused
   (A5 symmetry); it now feeds the leading digit. Templates without the token are
   byte-identical to pre-A6 (inert).

## Canonical template + lifecycle rule
```
{DOCUMENT_TYPE_CODE}{SELLER_CODE}{CUSTOMER_NO}{YY}{MM}{SEQ:3}
Quotation:  1021042607001      (seller 02 · customer 104 · 2026-07 · seq 001)
Proforma:   2021042607001      (SAME base, digit swapped)
Commercial: 3021042607001
Revision:   1021042607001.rev1 (revision_no is caller-side; never burns a seq)
```
- **The base is born only at the first Quotation** (allocate path). Proforma/Commercial
  **inherit** it via the **A5 render-only path** (caller passes the same seq / or performs a
  caller-side digit swap) — they never allocate.
- Online (INV-4): the MySQL ledger owns allocation; engine renders only. Desktop/standalone:
  `generate_document_number` + SQLite, same rules.

## Backward compatibility
Fully additive: A4 scopes (`per_seller_doctype_monthly`, …), the legacy PRF default, and all
existing tests remain valid and untouched (57/57 suite green, 7 new A6 tests).

## Files
- `src/erp_engine/modules/proforma/rules.py` — token map + scope + guards + render threading.
- `tests/unit/modules/proforma/test_engine.py` — A6 block (7 tests).
- `template/docs/CONTRACT_v1.md` §10 — inline A6 note (companion commit).
