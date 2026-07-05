# CONTRACT Amendment A5 — Render-Only Document Numbering

**Status:** AMENDMENT SPEC (plan) — approved-in-principle by Codex 2026-07-05 (INV-4 §13.1/§13.2). **No engine code until explicit A5 code-phase GO.**
**Amends:** `template/docs/CONTRACT_v1.md` §10 (document number) — adds a *render-only* path; §7 payload (`numbering.seq`).
**Implements in:** `src/erp_engine/modules/proforma/rules.py` (+ `engine.py` call site) + tests.
**Companion:** `agentai-web/docs/INV_4_DOCUMENT_PERSISTENCE_PLAN.md` (the online ledger that supplies the seq).
**One line:** *Online legal numbers are born atomically in the MySQL ledger transaction; the engine formats the number but does not keep the counter online.*

---

## A5.1 Problem
INV-4 (Option A, locked) moves the **online** legal sequence into **MySQL**, allocated inside the same transaction that inserts the document — so the number and the document are gapless and atomic. But the **token/format logic** (`{CUSTOMER_NO}{YY}{MM}{SEQ:3}`, padding, aliases) must stay **single-sourced in the engine**, not duplicated in PHP. So the engine needs a way to **format a number from a caller-supplied seq without touching any counter**.

## A5.2 Engine responsibility after A5
- **Calculator** (totals, tax) — unchanged.
- **Token renderer** — unchanged logic, now reachable in two ways:
  - **allocate + render** (`generate_document_number`, existing) — desktop/standalone path; owns the SQLite counter.
  - **render only** (`render_document_number`, NEW) — online path; the caller supplies `seq` (already allocated in MySQL); the engine formats, **no counter side effect**.
- The engine is **no longer the online allocator**. Allocation authority for the online ledger lives in MySQL (`document_no_counters`, INV-4).

## A5.3 Existing SQLite counter — retained for desktop/standalone
`generate_document_number` + `_next_seq` + `doc_counter` (SQLite) stay **exactly as A4 shipped**, for the desktop/standalone path where the engine owns the whole flow. A5 is purely **additive** — it does not remove or change the allocate path. Documented divergence (online=MySQL, desktop=SQLite), not drift.

## A5.4 New helper (render-only)
```
def render_document_number(
    template: str,
    *,
    seq: int,                         # caller-supplied (MySQL-allocated)
    seller_code: str = "",
    customer_no: str | int | None = None,
    issue_date: date,
    document_type: str | None = None, # accepted for symmetry; not a render token
) -> str
```
- Renders the SAME tokens as A4 (`{SELLER_CODE} {CUSTOMER_NO} {YEAR} {YY} {MONTH} {MM} {SEQ:N}`) using the supplied `seq`. **No `_next_seq`, no DB, no scope key** — pure string formatting.
- **Refactor to keep tokens single-sourced:** extract A4's token-replace block into an internal `_render_number_tokens(template, seq, seller_code, customer_no, issue_date)`; BOTH `generate_document_number` (after it allocates) AND `render_document_number` call it. One render implementation, two entry points.
- **Validation:** if the template contains `{CUSTOMER_NO}` and `customer_no` is empty → raise `CustomerNoRequiredError` (same A4 error) **before** returning — no silent blank. (Belt-and-suspenders; INV-4 also hard-blocks at validation.)

## A5.5 Backward compatibility
- `generate_document_number` — **unchanged** (signature + behavior). Standalone callers and all A4 tests pass untouched.
- `render_document_number` — new, additive.
- No change to the SQLite counter, scope keys, or existing tokens.
- CONTRACT_v1 §10 gains a "render-only path" note tagged `(A5, 2026-07-xx)`; version bump per amendment convention.

## A5.6 CLI / API exposure — how the online caller reaches render-only
The PHP caller already invokes the engine via `create_proforma` (adapter CLI). Two ways to expose render-only:

- **(Recommended) Reuse `create_proforma` with a caller-supplied seq.** Add optional `payload.numbering.seq` (int). Engine step 4 becomes:
  1. `header.document_no` set (e.g. `"DRAFT"`) → use it, no numbering (existing INV-2C brake).
  2. else `numbering.seq` provided → **`render_document_number(...)` with that seq — no counter** (online issue path).
  3. else → `generate_document_number(...)` — allocate via SQLite (desktop path).
  So the **issue payload tells the engine "render, don't allocate"** simply by carrying the MySQL-allocated `seq`. No new subcommand; the whole calc + number happen in one engine call, keeping totals/tax/number consistent in one result.
- **(Alternative) A dedicated render-only adapter call** (`--render-number`) returning just the string. More surface, and it splits number-render from the calc call (two round-trips). Only worth it if INV-4 wants the number *before* running the calc. *Not recommended* — the seq is cheap to allocate first and pass in.

**Recommendation:** the `payload.numbering.seq` route. The INV-4 transaction allocates the seq in MySQL, passes it in the issue envelope, and the engine renders + calculates in one deterministic call.

## A5.7 Tests (pytest — authored at code phase)
1. `render_document_number("{CUSTOMER_NO}{YY}{MM}{SEQ:3}", seq=1, customer_no=104, issue_date=2026-07-03)` → `1042607001`.
2. SEQ padding: `{SEQ:5}` seq=42 → `00042`; `{SEQ}` seq=42 → `42`.
3. **No counter touched:** call render_document_number N times against an isolated counter db → `doc_counter` has **0 rows** (pure format).
4. `{CUSTOMER_NO}` in template + `customer_no=None` → `CustomerNoRequiredError`.
5. Legacy tokens: `PRF-{SELLER_CODE}-{YEAR}-{SEQ:5}` seq=7, seller=IST, 2026 → `PRF-IST-2026-00007`.
6. `{YY}`/`{MM}` render (2026-07 → 26/07).
7. **Parity:** `render_document_number(template, seq=S, ...)` == the string `generate_document_number` produces when it allocates that same S (same inputs) — proving one render implementation.
8. Envelope path: `create_proforma` with `numbering.seq=5` → result `document_no` uses seq 5, and the SQLite counter is untouched; without seq (desktop) → allocates as A4.
9. Back-compat: full A4/A1 suite still green.

## A5.8 Open decisions
1. **Exposure:** confirm `payload.numbering.seq` (recommended) vs a dedicated render-only adapter call.
2. **`render_document_number` public vs internal:** expose it as a module API (for a possible future direct caller) or keep it engine-internal and only reachable via `numbering.seq`? *Rec: expose it (cheap, testable), but the online path uses `numbering.seq`.*
3. **`document_type` param:** keep it in the signature for symmetry/future even though it isn't a render token? *Rec: keep, unused-but-documented.*

---
**A5 code (rules.py `_render_number_tokens` + `render_document_number` + engine.py `numbering.seq` branch + tests) begins only on Codex GO.** Its §A5.4/§A5.6 text is applied inline to `CONTRACT_v1.md` §10 at code phase.
