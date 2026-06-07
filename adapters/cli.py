"""CLI adapter for the erp-engine.

Read a JSON envelope from stdin, dispatch to the requested module's entry
point, write a JSON response envelope to stdout. Errors not surfaced by
the engine itself go to stderr with a non-zero exit code.

Source of truth:
    template/docs/CONTRACT_v1.md §3 (execution mode), §13 (exit codes).

Usage from the PHP shell:
    echo "$INPUT_JSON" | python -m adapters.cli --module proforma_invoice

Or after ``uv pip install -e .``:
    echo "$INPUT_JSON" | erp-engine --module proforma_invoice

Exit semantics per CONTRACT_v1.md §13:
    0 = success
    2 = validation error
    3 = execution error
"""

from __future__ import annotations

import argparse
import json
import sys


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="erp-engine",
        description="Run an ERP module against a JSON envelope on stdin.",
    )
    p.add_argument(
        "--module",
        required=True,
        choices=["proforma_invoice"],  # extend as new modules land
        help="Module to invoke.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"adapters/cli: stdin is not valid JSON: {exc}", file=sys.stderr)
        return 3  # execution error — request never reached the engine

    if args.module == "proforma_invoice":
        # Import lazily so unrelated module loads stay cheap.
        from erp_engine.modules.proforma import create_proforma

        try:
            response = create_proforma(payload)
        except Exception as exc:  # noqa: BLE001 — top-level boundary
            print(f"adapters/cli: engine error: {exc}", file=sys.stderr)
            return 3
    else:
        # argparse `choices` constrains this; keep the branch for future
        # modules.
        print(f"adapters/cli: unknown module {args.module!r}", file=sys.stderr)
        return 3

    json.dump(response, sys.stdout, ensure_ascii=False, default=str)

    status = response.get("status")
    if status == "ok":
        return 0
    if status == "validation_error":
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
