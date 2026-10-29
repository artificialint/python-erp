# Shared A7 contract cases

`a7_contract_cases.json` is language-neutral UTF-8 JSON, fixture version 1.
PHP and Python callers can replay each `request` through the CLI and compare the
stable projection below to `expected`, together with the process `exit_code`.
Expectations were derived from the A7 rules, not captured from engine output.

The projection contains:

- `status`;
- `result`: null on error; otherwise all six `totals` fields and an ordered
  `line_items` list containing `line_no`, `discount_amount`, `tax_amount`, `line_total`;
- ordered `errors` containing only `code` and `field`.

Other envelope fields remain governed by the schema and its tests. Error messages,
engine version, timestamps and numbering trace are excluded from this projection.
Every fixture supplies an explicit document number, so replay must never allocate
a sequence. Preserve JSON number types; compare decimal money semantics rather
than requiring a trailing zero or recomputing totals in binary float.

Cases cover HALF_UP, group allocation (two different lines receive the two
outstanding cents), discounts, input-price precision, freight, mixed tax groups,
invalid quantity, unsupported currency and product overflow. The Python replay
test is `tests/integration/test_contract_fixtures.py`. PHP adoption/CI integration
requires a separate change in the web repository; fixture publication alone does
not prove that caller has adopted these cases.
