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

from datetime import date, datetime, timedelta, timezone

from pydantic import ValidationError as PydanticValidationError

from .rules import (
    DEFAULT_COUNTER_SCOPE,
    DEFAULT_DOC_NUMBER_TEMPLATE,
    MissingTaxRuleError,
    generate_document_number,
    resolve_tax,
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

    # ── 4. Document number ──────────────────────────────────────────
    if proforma.header.document_no:
        document_no = proforma.header.document_no
    else:
        document_no = generate_document_number(
            seller_code=proforma.seller.company_code,
            issue_date=issue_date,
            template=DEFAULT_DOC_NUMBER_TEMPLATE,
            counter_scope=DEFAULT_COUNTER_SCOPE,
        )

    # ── 5. Ship-to resolution ───────────────────────────────────────
    ship_to_resolved = _resolve_ship_to(proforma)

    # ── 6. Line-item computation ────────────────────────────────────
    result_lines: list[ResultLineItem] = []
    precedence_sources: list[str] = []
    tax_reasons: list[str] = []
    warnings: list[Warning] = []

    for line in proforma.line_items:
        gross = round(line.quantity * line.unit_price, 4)
        discount_amount = round(gross * (line.discount_percent / 100.0), 4)
        taxable = round(gross - discount_amount, 4)

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

        tax_amount = round(taxable * (decision.percent / 100.0), 4)
        line_total = round(taxable + tax_amount, 4)

        result_lines.append(
            ResultLineItem(
                line_no=line.line_no,
                product_code=line.product_code,
                product_description=line.product_description,
                hs_code=line.hs_code,
                quantity=line.quantity,
                unit=line.unit,
                unit_price=line.unit_price,
                discount_percent=line.discount_percent,
                discount_amount=discount_amount,
                tax_percent=decision.percent,
                tax_reason=decision.reason,
                tax_amount=tax_amount,
                line_total=line_total,
            )
        )

    # ── 7. Totals (PROFORMA_v1.md §5.7, CONTRACT_v1.md §11.5) ──────
    subtotal_amount = round(
        sum(line.quantity * line.unit_price for line in proforma.line_items),
        4,
    )
    discount_amount = round(
        sum(item.discount_amount for item in result_lines),
        4,
    )
    freight_amount = round(proforma.terms.freight_cost, 4)
    tax_amount = round(sum(item.tax_amount for item in result_lines), 4)
    net_amount = round(subtotal_amount - discount_amount + freight_amount, 4)
    grand_total = round(net_amount + tax_amount, 4)

    totals = ResultTotals(
        subtotal_amount=subtotal_amount,
        discount_amount=discount_amount,
        freight_amount=freight_amount,
        net_amount=net_amount,
        tax_amount=tax_amount,
        grand_total=grand_total,
    )

    # ── 8. Assemble response ────────────────────────────────────────
    result = ProformaResult(
        document=ResultDocument(
            document_no=document_no,
            document_type=proforma.header.document_type,
            issue_date=proforma.header.issue_date,
            valid_until=valid_until,
            currency=proforma.header.currency,
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
            document_number_template=DEFAULT_DOC_NUMBER_TEMPLATE,
            counter_scope=DEFAULT_COUNTER_SCOPE,
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
