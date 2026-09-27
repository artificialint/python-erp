"""Proforma engine entry point.

Source of truth:
    template/docs/CONTRACT_v1.md §8 (engine responsibilities)
    template/docs/CONTRACT_v1.md §11 (result payload contract)
    template/docs/modules/PROFORMA_v1.md §3.2 (data flow), §5-§11 (form, rules)

This module orchestrates: validate → resolve → compute → assemble.
It does not read DB or files in v1 — the PHP shell pre-resolves seller,
buyer, and product data and submits a complete payload. The engine
focuses on deterministic calculation and rule application.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal

from pydantic import ValidationError as PydanticValidationError

from .rules import (
    CounterStoreError,
    DEFAULT_COUNTER_SCOPE,
    DEFAULT_DOC_NUMBER_TEMPLATE,
    CustomerNoRequiredError,
    MissingTaxRuleError,
    MONEY_SCALE,
    UnsupportedCurrencyError,
    generate_document_number,
    money_out,
    render_document_number,
    resolve_tax,
    round_money,
    to_money,
    validate_currency,
)
from .schema import (
    CalculationTrace,
    ExecutionError,
    ProformaPayload,
    ProformaResult,
    RequestEnvelope,
    ResponseEnvelope,
    ResultDocument,
    ResultLineItem,
    ResultParties,
    ResultTotals,
    ShipTo,
    ValidationError,
    Warning,
)


ENGINE_VERSION = "0.1.0"

_HUNDRED = Decimal(100)


@dataclass
class _ResolvedLine:
    """One line after pass 1 of the A7 money computation.

    Holds the exact two-decimal amounts plus the resolved tax rate, so pass 2
    can group by rate without recomputing anything.
    """

    line: object          # the inbound LineItem
    gross: Decimal        # round2(quantity * unit_price)
    discount_amount: Decimal
    taxable: Decimal      # gross - discount_amount, exact by construction
    tax_percent: Decimal
    tax_reason: str


def create_proforma(payload: dict) -> dict:
    """Create a proforma invoice from a request envelope.

    Args:
        payload: Request envelope as a plain dict (JSON-decoded).
            Shape per CONTRACT_v1.md §5.1.

    Returns:
        Response envelope as a plain dict. Shape per CONTRACT_v1.md §5.2.
        On validation failure ``status`` is ``"validation_error"`` and
        ``result`` is ``None``. On execution failure ``status`` is
        ``"execution_error"``.
    """
    # ── 1. Envelope parse ────────────────────────────────────────────
    try:
        envelope = RequestEnvelope.model_validate(payload)
    except PydanticValidationError as exc:
        request_id = str(payload.get("request_id", ""))
        return _validation_error_response(request_id, exc).model_dump()

    proforma = envelope.payload

    # ── 2. Form-level validation (PROFORMA_v1.md §10.1) ─────────────
    form_errors = _validate_form_level(proforma)
    if form_errors:
        return ResponseEnvelope(
            request_id=envelope.request_id,
            status="validation_error",
            errors=list(form_errors),
            meta={"engine_version": ENGINE_VERSION},
        ).model_dump()

    # ── 3. Header derivations ───────────────────────────────────────
    issue_date = _parse_iso_date(proforma.header.issue_date)
    if issue_date is None:
        return _single_validation_error_response(
            envelope.request_id,
            code="invalid_date_format",
            field="header.issue_date",
            message="issue_date must be ISO-formatted YYYY-MM-DD.",
        ).model_dump()

    valid_until = proforma.header.valid_until or (
        issue_date + timedelta(days=30)
    ).isoformat()

    # ── 3b. Currency scope (A7 §8) ──────────────────────────────────
    # Checked BEFORE the numbering step so an out-of-scope currency can never
    # burn a document sequence — the same pre-counter guard principle as A4's
    # {CUSTOMER_NO} and A6's {DOCUMENT_TYPE_CODE} checks.
    try:
        currency = validate_currency(proforma.header.currency)
    except UnsupportedCurrencyError as exc:
        return _single_validation_error_response(
            envelope.request_id,
            code="unsupported_currency",
            field="header.currency",
            message=str(exc),
        ).model_dump()

    # ── 4. Document number (A4: customer-anchored, tenant-isolated) ──
    # Numbering config is caller-supplied (tenant settings_json.numbering);
    # absent → engine defaults (legacy PRF / per_seller_annual). tenant_key
    # namespaces the counter per tenant and is sourced from the existing
    # context.customer_id — absent → legacy un-prefixed key (back-compat).
    number_template = proforma.numbering.template or DEFAULT_DOC_NUMBER_TEMPLATE
    counter_scope = proforma.numbering.counter_scope or DEFAULT_COUNTER_SCOPE
    tenant_key = (
        str(envelope.context.customer_id)
        if envelope.context.customer_id is not None
        else None
    )
    # Resolution order: explicit document_no (e.g. DRAFT brake) > A5 render-only
    # (caller supplied numbering.seq — online issue, MySQL-allocated, NO engine
    # counter) > allocate via the SQLite counter (standalone/desktop).
    if proforma.header.document_no:
        document_no = proforma.header.document_no
    else:
        try:
            if proforma.numbering.seq is not None:
                document_no = render_document_number(
                    number_template,
                    seq=proforma.numbering.seq,
                    seller_code=proforma.seller.company_code,
                    customer_no=proforma.buyer.customer_no,
                    issue_date=issue_date,
                    document_type=proforma.header.document_type,
                )
            else:
                document_no = generate_document_number(
                    seller_code=proforma.seller.company_code,
                    issue_date=issue_date,
                    template=number_template,
                    counter_scope=counter_scope,
                    customer_no=proforma.buyer.customer_no,
                    document_type=proforma.header.document_type,
                    tenant_key=tenant_key,
                )
        except CustomerNoRequiredError as exc:
            return _single_validation_error_response(
                envelope.request_id,
                code="customer_no_required",
                field="buyer.customer_no",
                message=str(exc),
            ).model_dump()
        except CounterStoreError as exc:
            # QA PE2 (revised after A's review): the number-allocation path touches a
            # counter store, and only CustomerNoRequiredError was caught, so a locked,
            # missing or read-only store escaped as a raw sqlite3.OperationalError
            # straight through the contract boundary. Infrastructure failure is an
            # execution_error — the request was fine, we could not serve it.
            #
            # This catch used to be `except Exception`, which would also have reported
            # a genuine programming bug as an infrastructure failure. It is now a
            # domain error raised by rules.py, the module that actually owns the
            # storage. That keeps the engine storage-agnostic — narrowing to
            # `sqlite3.Error` here would have meant importing sqlite3 into the engine
            # and deepening the impurity H1/PE1 reports — while letting a real bug
            # surface as itself.
            return _single_execution_error_response(
                envelope.request_id,
                code="counter_store_unavailable",
                message=f"document number could not be allocated: {exc}",
            ).model_dump()

    # ── 5. Ship-to resolution ───────────────────────────────────────
    ship_to_resolved = _resolve_ship_to(proforma)

    # ── 6. Line-item computation (A7: exact Decimal money) ──────────
    #
    # Two passes, because A7 computes tax per tax-rate group rather than per
    # line. Pass 1 resolves each line's rate and its two-decimal taxable
    # amount; pass 2 computes one rounded tax figure per rate and allocates it
    # back to the lines, so the printed per-line tax column still sums to the
    # printed tax total.
    #
    # Pre-A7 this was float arithmetic rounded to 4 places, which is why a TRY
    # invoice could return grand_total 117.9882 — unprintable, and impossible
    # to reconcile a PDF against a stored snapshot. Every amount below goes
    # through to_money()/round_money(); see docs/CONTRACT_A7_MONEY_PRECISION.md.
    resolved: list[_ResolvedLine] = []
    precedence_sources: list[str] = []
    tax_reasons: list[str] = []
    warnings: list[Warning] = []

    for line in proforma.line_items:
        gross = round_money(to_money(line.quantity) * to_money(line.unit_price))
        discount_amount = round_money(
            gross * to_money(line.discount_percent) / _HUNDRED
        )
        # gross and discount_amount are both already quantized to two places,
        # so their difference is exact and needs no further rounding. This is
        # what makes subtotal - discount == sum(taxable) hold exactly.
        taxable = gross - discount_amount

        # Tax resolution: same-country sales without a configured rate
        # surface as execution_error (no silent zero); cross-country
        # default-to-zero cases attach a warning so the admin sees the
        # implicit assumption.
        try:
            decision = resolve_tax(
                line_override_percent=line.tax_percent,
                seller_country=proforma.seller.country,
                buyer_country=proforma.buyer.country,
            )
        except MissingTaxRuleError as exc:
            return ResponseEnvelope(
                request_id=envelope.request_id,
                status="execution_error",
                errors=[
                    ExecutionError(
                        code="missing_tax_rule",
                        field=f"line_items[{line.line_no}].tax_percent",
                        message=str(exc),
                    )
                ],
                meta={"engine_version": ENGINE_VERSION},
            ).model_dump()

        if decision.precedence_source not in precedence_sources:
            precedence_sources.append(decision.precedence_source)
        if decision.reason not in tax_reasons:
            tax_reasons.append(decision.reason)

        if decision.reason == "export_zero_vat_assumed":
            warnings.append(
                Warning(
                    code="tax_rule_assumed_export_zero",
                    field=f"line_items[{line.line_no}].tax_percent",
                    message=(
                        f"No explicit rule for {proforma.seller.country}-"
                        f"{proforma.buyer.country}; treated as export at 0%. "
                        "Load an explicit tax rule for this pair to remove "
                        "this warning."
                    ),
                )
            )

        resolved.append(
            _ResolvedLine(
                line=line,
                gross=gross,
                discount_amount=discount_amount,
                taxable=taxable,
                tax_percent=to_money(decision.percent),
                tax_reason=decision.reason,
            )
        )

    # Pass 2 — one rounded tax figure per rate group (A7 §5).
    #
    # Rounding tax per line and summing it drifts by up to half a cent per
    # line, which shows up on a long invoice. Rounding only the document total
    # makes the printed lines fail to add up to the printed total. Grouping by
    # rate is both standard UBL-TR / EU practice and the only variant where the
    # document reconciles exactly against itself.
    group_tax: dict[Decimal, Decimal] = {}
    for rate in {item.tax_percent for item in resolved}:
        base = sum(
            (item.taxable for item in resolved if item.tax_percent == rate),
            Decimal(0),
        )
        group_tax[rate] = round_money(base * rate / _HUNDRED)

    # Allocate each group's tax back to its lines by LARGEST REMAINDER, so that
    # the per-line column sums to the group figure without any single line
    # absorbing the whole discrepancy.
    #
    # The first implementation of this rounded each line independently and gave
    # the entire residual to the largest line, on the assumption the residual
    # was "a cent or two". It is not: each per-line rounding can be off by up
    # to half a cent, so the residual grows with the line count. Measured on
    # n lines of taxable 0.07 at 18% — group tax n*0.0126 rounded, per line
    # 0.01 — the residual is 0.01 at n=2 but 0.26 at n=100, which made one
    # line's tax 0.27 against a correct 0.01. Twenty-seven times over, on a
    # document a customer reads, while every reconciliation identity still
    # held — so no totals-based test could see it.
    #
    # Largest remainder instead: floor every line to the cent, then hand out
    # the remaining cents one at a time to the lines with the largest discarded
    # fraction. That bounds any single line's adjustment to one cent regardless
    # of line count, and keeps the result independent of iteration order
    # (ordering is by descending fraction, ties by line_no).
    line_tax: dict[int, Decimal] = {}
    for rate, rate_total in group_tax.items():
        members = [item for item in resolved if item.tax_percent == rate]
        exact = {
            item.line.line_no: item.taxable * rate / _HUNDRED for item in members
        }
        floored = {
            line_no: value.quantize(MONEY_SCALE, rounding=ROUND_DOWN)
            for line_no, value in exact.items()
        }
        line_tax.update(floored)

        # Flooring never overshoots, so this count is always >= 0, and because
        # each discarded fraction is under one cent it can never exceed the
        # number of lines in the group. The modulo is defensive only.
        shortfall = rate_total - sum(floored.values(), Decimal(0))
        cents = int((shortfall / MONEY_SCALE).to_integral_value())
        order = sorted(
            members,
            key=lambda item: (
                -(exact[item.line.line_no] - floored[item.line.line_no]),
                item.line.line_no,
            ),
        )
        for index in range(cents):
            line_tax[order[index % len(order)].line.line_no] += MONEY_SCALE

    result_lines: list[ResultLineItem] = []
    for item in resolved:
        tax_amount = line_tax[item.line.line_no]
        result_lines.append(
            ResultLineItem(
                line_no=item.line.line_no,
                product_code=item.line.product_code,
                product_description=item.line.product_description,
                hs_code=item.line.hs_code,
                quantity=item.line.quantity,
                unit=item.line.unit,
                unit_price=item.line.unit_price,
                discount_percent=item.line.discount_percent,
                discount_amount=money_out(item.discount_amount),
                tax_percent=float(item.tax_percent),
                tax_reason=item.tax_reason,
                tax_amount=money_out(tax_amount),
                # line_total stays tax-inclusive, as pre-A7 — A7 changes the
                # precision of the contract's fields, never their meaning.
                line_total=money_out(item.taxable + tax_amount),
            )
        )

    # ── 7. Totals (PROFORMA_v1.md §5.7, CONTRACT_v1.md §11.5) ──────
    #
    # Every operand below is already quantized to two places, so these are
    # exact Decimal sums and differences — no rounding step is applied here,
    # and none is needed. That is what guarantees the document adds up as
    # printed:
    #     subtotal - discount + freight            == net_amount
    #     net_amount + tax_amount                  == grand_total
    #     sum(line_total) + freight                == grand_total
    subtotal_amount = sum((item.gross for item in resolved), Decimal(0))
    discount_total = sum((item.discount_amount for item in resolved), Decimal(0))
    freight_amount = round_money(to_money(proforma.terms.freight_cost))
    tax_total = sum(group_tax.values(), Decimal(0))
    net_amount = subtotal_amount - discount_total + freight_amount
    grand_total = net_amount + tax_total

    totals = ResultTotals(
        subtotal_amount=money_out(subtotal_amount),
        discount_amount=money_out(discount_total),
        freight_amount=money_out(freight_amount),
        net_amount=money_out(net_amount),
        tax_amount=money_out(tax_total),
        grand_total=money_out(grand_total),
    )

    # ── 8. Assemble response ────────────────────────────────────────
    result = ProformaResult(
        document=ResultDocument(
            document_no=document_no,
            document_type=proforma.header.document_type,
            issue_date=proforma.header.issue_date,
            valid_until=valid_until,
            currency=currency,
        ),
        parties=ResultParties(
            seller=proforma.seller,
            buyer=proforma.buyer,
            ship_to=ship_to_resolved,
        ),
        line_items=result_lines,
        totals=totals,
        calculation_trace=CalculationTrace(
            tax_precedence_applied=precedence_sources,
            tax_reason_summary=tax_reasons,
            document_number_template=number_template,
            counter_scope=counter_scope,
        ),
    )

    # NOTE on currency check (CONTRACT §7.2 — "currency must match
    # seller-supported currency in v1"): cross-check is deferred until
    # the sellers data file is wired into the engine. v1 trusts the
    # PHP shell to have validated currency against the seller record
    # before submitting. This is tracked as a v1.1 hardening item.

    response = ResponseEnvelope(
        request_id=envelope.request_id,
        status="ok",
        result=result,
        warnings=warnings,
        meta={
            "engine_version": ENGINE_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return response.model_dump()


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _validate_form_level(proforma: ProformaPayload) -> list[ValidationError]:
    """Form-level checks beyond what Pydantic enforces structurally.

    Pydantic already enforces field presence and ``quantity > 0`` via
    the schema's ``field_validator``. This function captures any
    additional cross-field requirements from PROFORMA_v1.md §10.1.
    """
    errors: list[ValidationError] = []

    if not proforma.header.issue_date.strip():
        errors.append(
            ValidationError(
                code="required_field_missing",
                field="header.issue_date",
                message="issue_date is required.",
            )
        )
    if not proforma.seller.company_code.strip():
        errors.append(
            ValidationError(
                code="required_field_missing",
                field="seller.company_code",
                message="seller_company_code is required.",
            )
        )
    if not proforma.buyer.company_name.strip():
        errors.append(
            ValidationError(
                code="required_field_missing",
                field="buyer.company_name",
                message="buyer_company_name is required.",
            )
        )
    if not proforma.buyer.country.strip():
        errors.append(
            ValidationError(
                code="required_field_missing",
                field="buyer.country",
                message="buyer_country is required.",
            )
        )
    if not proforma.terms.delivery_term.strip():
        errors.append(
            ValidationError(
                code="required_field_missing",
                field="terms.delivery_term",
                message="delivery_term is required.",
            )
        )

    return errors


def _resolve_ship_to(proforma: ProformaPayload) -> ShipTo:
    """If ``same_as_buyer`` is true, mirror the buyer into the ship_to block."""
    ship_to = proforma.ship_to
    if not ship_to.same_as_buyer:
        return ship_to
    return ShipTo(
        same_as_buyer=True,
        company_name=proforma.buyer.company_name,
        address=proforma.buyer.address,
        city=proforma.buyer.city,
        country=proforma.buyer.country,
        phone=proforma.buyer.phone,
        email=proforma.buyer.email,
        source="buyer_copy",
    )


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _validation_error_response(
    request_id: str,
    exc: PydanticValidationError,
) -> ResponseEnvelope:
    """Translate Pydantic validation errors into the contract shape."""
    errors: list[ValidationError] = []
    for err in exc.errors():
        loc_parts: list[str] = []
        for part in err.get("loc", ()):
            if isinstance(part, int):
                loc_parts[-1] = f"{loc_parts[-1]}[{part}]"
            else:
                loc_parts.append(str(part))
        field = ".".join(loc_parts) if loc_parts else None
        errors.append(
            ValidationError(
                code=err.get("type", "validation_error"),
                field=field,
                message=str(err.get("msg", "")),
            )
        )
    return ResponseEnvelope(
        request_id=request_id,
        status="validation_error",
        errors=list(errors),
        meta={"engine_version": ENGINE_VERSION},
    )


def _single_validation_error_response(
    request_id: str, *, code: str, field: str, message: str
) -> ResponseEnvelope:
    return ResponseEnvelope(
        request_id=request_id,
        status="validation_error",
        errors=[ValidationError(code=code, field=field, message=message)],
        meta={"engine_version": ENGINE_VERSION},
    )


def _single_execution_error_response(
    request_id: str, *, code: str, message: str
) -> ResponseEnvelope:
    """QA PE2: an engine-side failure that is NOT the caller's fault.

    Kept separate from the validation helper because the distinction is the whole
    point: `validation_error` means "fix your request", `execution_error` means
    "the request was fine, we could not serve it". A caller retries one and not the
    other.
    """
    return ResponseEnvelope(
        request_id=request_id,
        status="execution_error",
        errors=[ExecutionError(code=code, message=message)],
        meta={"engine_version": ENGINE_VERSION},
    )
