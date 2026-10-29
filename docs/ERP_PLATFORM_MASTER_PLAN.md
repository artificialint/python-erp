# AgentAI ERP Platform Master Plan

**Owner/technical coordinator:** Codex  
**Implementation/review partner:** Claude  
**Authorized by user:** 2026-08-30  
**Status:** ACTIVE — permanent project plan; updated 2026-10-29 after Owner execution GO

## Current execution checkpoint — 2026-10-29

- Canonical workspace: `C:\project\agentai\python-erp`. Temporary Codex material belongs only
  under `C:\archive\erp-codex`; Claude material only under `C:\archive\erp-claude`.
  New directories require explicit authorization. Never leave caches or scratch databases in source.
- Implemented: engine/CLI, data/import layer, desktop MVP, A4-A6 numbering, PE1/PE2 hardening,
  A7 Decimal arithmetic and desktop four-decimal inputs. Baseline: local `73a74bb`, 150 tests
  last verified before this execution packet; GitHub feature/droplet `b29a0a9`, main `071fe7b`.
- Phase 1 remains open. Execution order: A7-FIX-002 (pre-numbering document bound and actual
  CLI subprocess regression), shared JSON contract cases with Python replay, independent Claude
  review and validation on supported Python versions, then an Owner push/merge decision.
- Local implementation/review completed 2026-10-29: A7-FIX-002 also postpones number allocation
  until tax resolution succeeds; actual CLI regressions and nine shared JSON cases are present.
  Claude's final independent review APPROVE, full Python 3.12 suite 190 passed. Codex verified
  27 boundary/counter cases (old engine 23 failed; new engine all passed), desktop smoke and
  nine real CLI envelopes identical on Python 3.11/3.12 except timestamps. Full pytest on 3.11
  has not run (the existing image lacks the test/data dependencies). No release authorization.
- PHP invocation/import concern closed by source inspection: the actual helper sets
  `PYTHONPATH=src` with the engine root as cwd, including the production copy. Cross-tenant
  staff-session source review is a higher-priority web integration gate: the production entry
  points inspected retain session-only staff identity checks and lack the prepared central guard.
  No production login, data access attempt or mutation was used to inspect this.
- Shared fixtures must be adopted by the PHP caller before claiming the cross-repository exit
  gate passes. Python fixture replay alone does not prove PHP integration.
- Then complete the manual online lifecycle, permissions/transactions and document output before
  adding AI tools, UNO orchestration and desktop distribution. These later phases are not done.
- Production images already include pre-fix A7 from `b29a0a9`; the host legacy `/opt/python-erp`
  checkout is not the canonical build source. Any deployment is separately reviewed/authorized.
- Parallel gates: verified off-machine backup for `data/local/erp.sqlite`, authoritative contract
  location, PHP invocation/import contract, and the four Owner product decisions in section 6.
- This file is the permanent master plan. The archive copy is historical and disposable once
  all other unique archive content and backup gates have been reconciled.

## 1. Product objective

Build one deterministic ERP capability that can be used through two delivery channels:

1. **Online first:** staff can operate it manually in `agentai-web`; an AI Assistant can perform
   the same permitted operations from chat and return a downloadable PDF/XLSX document.
2. **Desktop later:** an installable, offline-capable PySide6 application uses the same Python ERP
   contracts and calculation engine with local SQLite storage.

The first complete business vertical is the canonical commercial document lifecycle:
Quotation → Proforma Invoice → Commercial Invoice, including revisions, numbering, immutable
snapshots, permissions, rendering and download. AI is an optional caller; it never replaces the
deterministic engine, authority checks or user confirmation gates.

## 2. Repository and session decision

Keep three separate repositories, folders and primary coding sessions:

| Repository | Responsibility | Must not own |
|---|---|---|
| `python-erp` | Pure deterministic calculation/validation contracts; reusable Python data and desktop adapters | LLM orchestration, web auth, tenant sessions, production web UI |
| `agentai-uno` | UNO CEO Agent, domain/module-agent coordination, chat intent and tool orchestration | ERP calculations, direct ERP DB writes, document numbering |
| `agentai-web` | Web UI, auth, tenant/permission enforcement, master data, document lifecycle/persistence, file generation/download, internal tool API and deployment integration | Duplicate calculation rules or independent LLM business arithmetic |

Canonical online call path:

```text
Manual staff UI ─┐
                 ├─> agentai-web authorization + data resolution + lifecycle service
AI Assistant ────┘       └─> python-erp deterministic JSON contract
                                └─> immutable snapshot -> PDF/XLSX -> authorized download

UNO Agent -> agentai-web authenticated tool API -> module AI Assistant / ERP workflow
```

`agentai-uno` must not invoke the Python process or shared database directly. `agentai-web` is the
online trust boundary and system-of-record owner. The integration contract is a versioned API/tool
schema with tenant, actor, permission, idempotency and audit context.

## 3. Engineering operating model

1. Codex owns roadmap, scope, task sequencing and technical approval.
2. Claude proposes improvements and implements only the currently approved packet.
3. Every non-trivial packet is double-checked: implementer runs focused/full tests; reviewer
   inspects the diff and independently reruns proportionate tests. Codex gives final technical GO.
4. Large packets may be split: Codex and Claude can implement separate non-overlapping parts and
   review each other's work.
5. A successful local gate is required before commit/push authorization.
6. Push and deploy are separate recorded gates. Deploy only the reviewed commit(s), preserve a
   rollback target, and apply database migrations only with migration-specific checks and backup.
7. After deploy, Codex verifies `https://www.agentai.uno` end to end. Failure reopens the same task;
   the next roadmap item cannot start until the regression is fixed or explicitly deferred.
8. Never commit secrets, customer files, runtime databases, `.env`, generated documents or caches.

## 4. Delivery plan

### Phase 0 — Baseline and decision closure

- Reconcile the current implementation with the locked canonical invoice documents.
- Preserve `python-erp` QA baseline: commit `3439c6a`, 76 tests, desktop smoke PASS.
- Review the active dirty work in `agentai-web` before assigning overlapping work.
- Confirm the remaining product questions in §6. Money precision is now technically decided under
  Amendment A7 and is no longer open.
- Establish versioned cross-repo contracts and a traceable task/message ID convention.
- Decide the disposition of the old local `data/local/erp.sqlite`; do not restore it implicitly.
- Verify whether the production host provides Python 3.12 and permits PHP process spawning. If not,
  promote the HTTP adapter from later work to a Phase 2 prerequisite.
- Settle active `agentai-web` uncommitted work before assigning overlapping Phase 2 changes.

**Exit:** accepted master plan, no unresolved blocker for the first online vertical slice.

### Phase 1 — Python ERP contract hardening

- Treat `python-erp` as the single source for deterministic validation, tax/totals and numbering
  rendering semantics.
- Reconcile schema and tests with the locked Quotation → Proforma → Commercial lifecycle.
- Implement and lock Amendment A7 before any online snapshot is issued: use `Decimal`, serialize
  money at two decimals, apply `ROUND_HALF_UP`, round line results, compute tax per rate group from
  rounded line totals, and reject currencies outside the explicitly supported two-decimal set.
- Define stable, versioned request/response/error contracts for web and future desktop callers.
- Add contract fixtures usable by both PHP integration tests and Python tests.
- Keep document generation and web persistence outside the pure calculation engine.
- Keep one engine module discriminator (`proforma_invoice`) for backward compatibility while
  `document_type` selects quotation/proforma/commercial behavior. Do not build three engines.
- Treat the engine as a calculation boundary, never as an authentication or tenant-security
  boundary; callers must enforce authority before building the payload.

**Exit:** green Python suite, contract fixtures, no duplicated calculation semantics in PHP/UNO.

### Phase 2 — Online manual end-to-end vertical slice

- In `agentai-web`, finish canonical master-data bindings, document permissions and staff workflow.
- Manual flow: select authorized seller/buyer/items → preview → save immutable snapshot → lifecycle
  transition/revision → generate PDF/XLSX → authorized download.
- Allocate online legal sequences atomically in MySQL; pass the sequence to Python render-only
  numbering. Derived lifecycle documents inherit the base sequence as locked.
- Keep allocation, snapshot insertion and lifecycle transition in one caller-owned transaction.
  Engine/render failure must roll back the transaction; never silently reuse or compensate outside
  the documented transaction rule.
- Enforce tenant/actor permissions server-side; UI gating is not sufficient.
- Add idempotency, audit events and safe retry behavior.

**Exit:** local end-to-end tests and browser verification pass for one tenant and cross-tenant denial.

### Phase 3 — AI Assistant ERP tools

- Expose narrow authenticated tools from `agentai-web`, initially:
  `search_customer`, `search_product`, `create_quotation_draft`, `preview_document`,
  `confirm_document`, `generate_document_file`, `get_download_link`.
- AI supplies intent and missing-field dialogue; server resolves authority and canonical data.
- Draft/preview is separate from irreversible issue/approval. Require explicit user confirmation at
  the correct lifecycle gate and use idempotency keys to prevent duplicates.
- Return structured errors and clarification needs instead of allowing the model to invent values.
- A model tool call alone cannot confirm issuance. Confirmation requires server-side evidence of an
  explicit human action bound to actor, tenant, draft and idempotency key.
- Deliver the resulting authorized file through a signed, short-TTL, tenant-and-actor-scoped,
  non-enumerable download link; do not persist a replayable bearer URL in chat history.

**Exit:** “Bana proforma hazırla” succeeds from chat using the same underlying lifecycle service as
manual staff UI, with matching totals and a downloadable artifact.

### Phase 4 — UNO CEO Agent integration

- Keep `agentai-uno` as the orchestration/control plane and separate repository.
- UNO routes work to module/domain assistants through the versioned `agentai-web` tool boundary.
- Add correlation IDs, provenance, audit events, policy gates and bounded retries.
- UNO coordinates but cannot bypass module permissions, confirmation gates or deterministic ERP.
- Validate multi-assistant workflows only after the single Sales/Invoice AI Assistant path is stable.

**Exit:** UNO can coordinate an ERP request across assistants without direct DB/Python coupling.

### Phase 5 — Production delivery loop

- Codex reviews Claude's report and diff, reruns the local delivery gate and authorizes exact commits.
- Claude commits/pushes the approved packet and deploys only after a separate deploy-ready record.
- Codex tests production health, login/tenant isolation, manual ERP flow, AI chat flow, generated
  document/download, audit trail and rollback observability on `www.agentai.uno`.
- Any failure returns to implementation/review; do not advance the roadmap on a red gate.

**Exit:** production evidence recorded and rollback remains available.

### Phase 6 — Downloadable desktop application

- Reuse Python contracts and calculation engine; local caller owns SQLite, permissions, import and
  rendering.
- Complete offline master data, Excel import/export, document archive and PDF/XLSX output.
- Package with PyInstaller first; add installer/signing/update strategy after the functional build.
- Define an explicit optional synchronization protocol; offline desktop must not silently share
  counters or overwrite online state.
- Online and desktop may use different renderer implementations, but must share the same versioned
  XLSX template/token contract and immutable engine snapshot. Visual parity gets golden-file tests.

**Exit:** installable Windows build passes clean-machine acceptance and offline workflow tests.

## 5. Quality and release gates

Every packet records: objective, scope/exclusions, branch/base, changed files, migrations, security
impact, tests, known gaps, commit(s), push state, deploy state and rollback. Minimum gates:

- unit + integration + contract tests;
- cross-tenant and permission denial tests;
- numbering/idempotency/concurrency tests;
- snapshot and generated-file consistency;
- secret/runtime artifact scan;
- local UI or API smoke;
- post-deploy health and end-to-end smoke.

## 6. Product questions requiring user confirmation

1. **Initial AI audience:** only logged-in company staff, or also the customer's external website
   visitors? Recommendation: staff first; external visitors later with a narrower quotation flow.
2. **Issuance authority:** may AI only prepare drafts, or may it issue after an authorized user's
   explicit chat confirmation? Recommendation: draft + preview first, issue only after confirmation.
3. **First-market legal boundary:** which country/company is the first production tenant, and is the
   Commercial Invoice an internal/export document while official e-invoice remains in external
   accounting? This determines mandatory fields and compliance scope.
4. **First document output — DECIDED by Owner, 2026-10-29:** PDF and editable XLSX together.
   Both must render the same immutable snapshot; XLSX output is implementation work, not yet delivered.

## 7. Technical decisions closed after plan review

- **A7 money precision:** `Decimal(str(input))`; monetary results exactly two decimals;
  `ROUND_HALF_UP`; line-result rounding; tax per rate group from rounded line totals; grand total
  equals rounded net plus grouped tax. Rates and quantities are not forcibly two-decimal inputs.
  Initial supported currencies are explicitly limited to two-decimal currencies; nonconforming
  currencies fail validation rather than being silently misrepresented.
- **Module discriminator:** retain legacy `module=proforma_invoice`; use `document_type` for the
  three lifecycle types. Revisit only through a versioned contract migration.
- **Feature base:** the first hardening packet branches from exact
  `feat/qa-fixes@3439c6a6f28172080c8c67eaa97d1f21b6f8f8ad`. No silent merge to `main`.
- **Renderer ownership:** web and desktop rendering stay caller-side. The shared truth is the
  versioned snapshot plus template/token contract, not a language-specific PDF library.
- **Contract location:** current locked baseline remains in `agentai-web/docs` until a dedicated
  contract-home migration packet prevents duplicate authoritative copies.

## 8. First coordination action

Plan review is complete. The first implementation packet is A7 money precision in `python-erp`.
Its exact scope and gates are recorded in `communication.md`; all later phases remain closed.
