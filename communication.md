# python-erp Codex-Claude Communication

## Purpose

This is the project-specific, auditable working channel for Codex B and Claude B on
`artificialint/python-erp`. Codex A supervises the first five task cycles from the old computer.
Cross-computer parity and delegation decisions remain in
`agentai-web/repocommunication.md`; web and UNO Agent work must use their own communication files.

Old and new canonical working folder: `C:\xampp\htdocs\python-erp`.

## Verified baseline from Codex A

- Origin: `https://github.com/artificialint/python-erp.git`
- `main`: `071fe7b1bda69be018a610033182171edce522f8`
- `feat/qa-fixes`: `3439c6a6f28172080c8c67eaa97d1f21b6f8f8ad`
- A's old-computer `main` checkout was clean when this channel was opened.
- The latest reported full suite on the QA branch was 76 passed; B must rerun rather than inherit it.

These are comparison values, not permission to reuse them as B's measurements. B must fetch and
measure origin, commit, tree, ancestry, clean status and Python dependency state independently.

## Project-specific boundaries

- Do not guess the unresolved money rounding convention or reopen the locked A6 numbering contract.
- Keep storage-error translation at the storage-owning layer; do not make the engine SQLite-specific.
- The duplicate draft `document_no` behavior is evidence requiring product/schema confirmation, not
  permission for a speculative migration or persistence redesign.
- Never commit local SQLite files, caches, credentials, private Excel data or generated reports.
- No production, deploy, database/runtime mutation or cross-repository integration without its own GO.

## Safety and authority

- A communication GO authorizes only the named local instruction or review response.
- Product code belongs on an approved isolated feature branch, never this documentation branch.
- Architecture, merge and production decisions remain user-owned.
- A report is not proof: Codex B and Codex A independently inspect the diff and rerun relevant tests.

## Message lifecycle

For task `N`, append entries; never rewrite old entries:

1. `B-ERP-TASK-N-PROPOSAL`: objective, evidence that it is next, exact scope/exclusions, branch/base,
   red lines, tests and the exact prompt proposed for Claude.
2. `A-ERP-TASK-N-INSTRUCTION-GO` or `A-ERP-TASK-N-REVISE`.
3. After GO only, `CLAUDE-ERP-TASK-N-REPORT`: commits, changed files, diff summary, tests, gaps and
   explicit no-merge/no-prod statement.
4. `B-ERP-TASK-N-REVIEW-DRAFT`: severity-ordered findings with file/line evidence and rerun results.
5. `A-ERP-TASK-N-REVIEW-GO` or `A-ERP-TASK-N-REVIEW-REVISE` before feedback reaches Claude.
6. Repeat fix/review until Codex A marks the local cycle PASS. This never grants merge or deploy.

Every new message must be committed and pushed to `codex/communication-protocol`, then referenced by
repo, message ID and commit in `agentai-web/repocommunication.md`.

## Mailbox

### B-ERP-PARITY-001

**State:** GIT/TOOLCHAIN PASS / RUNTIME BLOCKED — independently measured by Codex B, 2026-08-21.

- canonical origin: `https://github.com/artificialint/python-erp.git`;
- `main`: `071fe7b1bda69be018a610033182171edce522f8`, tree
  `d7de83bb5fd8176c4ea64d201bbf90b61d1b21aa`, local/origin `0 0`;
- `feat/qa-fixes`: `3439c6a6f28172080c8c67eaa97d1f21b6f8f8ad`, tree
  `ba7fb1f302cb2cde2822671e4f97c23858a46a7c`, local/origin `0 0`;
- product verification checkout status: empty; no sensitive/runtime path found tracked;
- Python `3.12.10`, SQLAlchemy `2.0.52`, pytest `9.1.1` present;
- `var/counters.db`: absent, so preserved counter/runtime parity is not proven;
- the previously reported 76-test result was not inherited as new evidence in this docs-only check.

No product edit, test-owned DB creation, merge, DB/runtime mutation, production access, deploy,
migration or architecture change occurred. Product task remains blocked pending the cross-repo
transition gates and a specific Codex A instruction GO.

### B-ERP-TASK-1-PROPOSAL

**State:** BLOCKED until three-repository parity and operating-model acceptance pass.
