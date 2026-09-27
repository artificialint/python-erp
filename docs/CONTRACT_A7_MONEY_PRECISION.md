# CONTRACT Amendment A7 — Money Precision (2026-09-27)

**Status:** implemented. Engine stays pure calc (CONTRACT_v1 §8.1 untouched).
**Amends:** `CONTRACT_v1.md` §11.4/§11.5 (result money fields) — fixes the precision and rounding
convention that v1 left unspecified.
**Decided by:** the Owner, 2026-08-30. **Mode confirmed** by Codex against `ROUND_CEILING`.
**Implements in:** `rules.py` (money primitives), `engine.py` (line + totals computation),
`schema.py` (input guards, currency scope) + tests.
**One line:** *money is computed in `Decimal`, rounded to two places HALF_UP at the line, taxed per
rate group, and the document adds up exactly as printed.*

---

## A7.1 The problem

Pre-A7 the engine did float arithmetic rounded to four places. Measured on the shipped code:

| input | pre-A7 `grand_total` |
|---|---|
| 3 × 33.33 @18% TRY | `117.9882` |
| 7 × 0.07 @18% TRY | `0.5782` |
| 100 less 33.333% @20% TRY | `80.0004` |
| 1 × 1.005 @20% TRY | `1.206` |
| 3 × 0.10 @20% **JPY** | `0.36` (a zero-decimal currency given two) |

No document can print `117.9882`. So the caller had to round for display, which meant either the
PDF disagreed with the stored snapshot, or PHP owned the rounding rule — and the architecture makes
python-erp the single source of calculation semantics. The convention appeared nowhere: neither
`CONTRACT_v1.md` nor `CANONICAL_INVOICE_PRODUCT_ALGORITHM.md` contains the words round, precision,
decimal or scale. `test_money_contract.py` is deliberately convention-agnostic — *"whatever the
rounding convention, the invoice must agree with itself"* — and passes on `117.9882`.

## A7.2 Normative rules

1. **Representation.** Every amount entering money arithmetic is converted with
   `Decimal(str(value))` and computed in `Decimal`. Never `float` arithmetic, and never
   `Decimal(float)`.
2. **Scale.** Every monetary *result* is quantized to exactly **two decimal places**: line
   `discount_amount`, line `tax_amount`, `line_total`, `subtotal_amount`, `discount_amount`,
   `freight_amount`, `net_amount`, `tax_amount`, `grand_total`.
3. **Mode.** `ROUND_HALF_UP`.
4. **Line rounding point.** `gross = round2(quantity × unit_price)`;
   `discount_amount = round2(gross × discount_percent / 100)`;
   `taxable = gross − discount_amount`. Both operands are already at scale 2, so `taxable` is exact
   and is **not** rounded again.
5. **Tax base — per rate group.** Lines are grouped by resolved `tax_percent`; the group base is the
   sum of that group's `taxable` amounts; `group_tax = round2(base × rate / 100)`;
   `tax_amount = Σ group_tax`.
6. **Per-line tax allocation — largest remainder.** The contract reports a per-line `tax_amount`,
   so the group figure is allocated back to the lines. Each line is **floored** to the cent
   (`ROUND_DOWN`); the cents still outstanding against `group_tax` are then handed out **one at a
   time** to the lines with the largest discarded fraction, ties broken by the lowest `line_no`.
   This guarantees two things: the per-line tax column sums exactly to `tax_amount`, and **no single
   line is adjusted by more than one cent**, whatever the line count.

   **The outstanding count is never negative, by construction.** Each floor is at most its exact
   share, so the sum of floors is a multiple of a cent that is at most the exact group total; the
   largest such multiple is `ROUND_DOWN(total)`, and `ROUND_HALF_UP(total) >= ROUND_DOWN(total)`.
   Hence `group_tax >= Σ floors` for every input, given that all amounts are non-negative — which
   the schema guarantees (`unit_price >= 0`, `discount_percent <= 100` so `taxable >= 0`,
   `tax_percent >= 0`). No line is ever adjusted downward. And since every discarded fraction is
   under one cent, the count can never exceed the number of lines in the group.

   The property a conforming implementation must exhibit is therefore **exactly `k` lines lifted by
   exactly one cent**, where `k` is the outstanding count — not merely "each line is within a cent",
   which largest remainder satisfies automatically and which a wrong implementation can also satisfy.
7. **Totals are exact sums.** `subtotal_amount = Σ gross`; `discount_amount = Σ` line discounts;
   `freight_amount = round2(freight_cost)`; `net_amount = subtotal − discount + freight`;
   `grand_total = net + tax`. Every operand is already at scale 2, so these are exact — no rounding
   step is applied at the totals level and none is needed.
8. **Freight is not taxed** (unchanged from v1).
9. **Rates and inputs are not money.** `quantity`, `unit_price`, `discount_percent` and
   `tax_percent` are not forced to scale 2; useful unit-price precision is preserved. They are
   validated as finite (see A7.4).
10. **Currency scope.** Only `TRY`, `USD`, `EUR`, `GBP`. Any other code — including zero-decimal
    currencies such as `JPY` and `KRW` — is a `validation_error` with code `unsupported_currency`.
    The check runs **before** the numbering step, so an out-of-scope currency can never burn a
    document sequence (same pre-counter guard principle as A4's `{CUSTOMER_NO}` and A6's
    `{DOCUMENT_TYPE_CODE}`).

### Why per rate group, and not per line or total-only

Rounding tax per line and summing drifts by up to half a cent per line, which is visible on a long
invoice. Rounding only at the document total makes the printed line amounts fail to add up to the
printed total, which reads as an arithmetic error to the buyer. Grouping by rate is standard UBL-TR
and EU practice and is the only variant where the document reconciles exactly against itself.

### Why `Decimal(str(value))` specifically

The schema declares money inputs as `float`, so Pydantic has already coerced the JSON number before
the engine sees it. `Decimal(1.005)` is `1.00499999999999989…` and rounds **down** under HALF_UP;
`Decimal(str(1.005))` is exactly `1.005` and rounds **up**, because `str()` of a float is its
shortest round-tripping decimal. Without this conversion the convention is not implementable —
`round_money(Decimal(1.005))` returns `1.00`, `round_money(to_money(1.005))` returns `1.01`.

## A7.3 JSON representation

The wire format is unchanged: money fields remain JSON numbers, and the response schema still
declares `float`. A two-decimal `Decimal` converted to `float` round-trips through
`json.dumps`/`json.loads` to the same value, because a float's `repr` is its shortest
round-tripping decimal. The guarantee A7 adds is that **every emitted amount has at most two
decimal places of significance** — formally, `Decimal(str(value)).as_tuple().exponent >= -2`.

A trailing zero may not survive (`Decimal("80.00")` emits as `80.0`). That is a *display* concern:
the value is exact, and formatting to two places (`%.2f`) is the caller's responsibility. The engine
guarantees the number, not its presentation.

## A7.3b Magnitude bound — `MAX_AMOUNT_MAGNITUDE = 1e15`

Not a business rule about invoice size. `Decimal.quantize` raises `InvalidOperation` when the result
needs more digits than the context precision (28 by default), and A7's first implementation had no
bound — so `unit_price = 1e26` made `quantize` raise **straight out of `create_proforma`**, a crash
through the contract boundary instead of an error envelope. Pre-A7 float arithmetic did not crash
there, so **A7 introduced this path** and closes it by refusing the input.

Headroom at this bound, **measured rather than reasoned** — an earlier version of this paragraph
counted two of the three wrong, off by one in each case:

| value | digits the `Decimal` coefficient needs |
|---|---|
| `1e15` at scale 2 | 18 |
| × a rate up to 100 | 20 |
| summed over 1,000 lines at the bound | 21 |
| the first magnitude that actually raises | **`1e26`** (`1e25` uses all 28) |

So the bound sits eleven orders of magnitude below the wall, and the margin survives a hundred
thousand lines at the bound. What refuses an absurd input is the bound, never the arithmetic.

The bound is declared twice — as a `Decimal` in `rules.py` and a `float` in `schema.py`, so the
validators stay free of `Decimal` — and a test asserts the two agree.

## A7.4 Input guards added

Pre-A7 the range validators compared with `<` and `<=`, and **every comparison against NaN is
False** — so `float("nan")` satisfied `quantity > 0`, `unit_price >= 0`, `0 ≤ discount ≤ 100` and
`0 ≤ tax ≤ 100` alike, and propagated into the totals as `nan` with `status: "ok"`. `freight_cost`
had no validator at all, so NaN, Infinity and negative freight all passed.

A7 rejects non-finite values on `quantity`, `unit_price`, `discount_percent`, `tax_percent` and
`freight_cost`, and adds `freight_cost >= 0`.

## A7.5 Worked examples — normative

All figures below are derived from the rules above by hand, not from engine output.

| case | line detail | tax | `grand_total` |
|---|---|---|---|
| 3 × 33.33 @18% | gross `99.99` | group base `99.99` → `18.00` | **`117.99`** |
| 7 × 0.07 @18% | gross `0.07` each | base `0.49` → `0.09`; residual `0.02` to line 1 | **`0.58`** |
| 100 less 33.333% @20% | gross `100.00`, disc `33.33`, taxable `66.67` | `13.33` | **`80.00`** |
| 1 × 1.005 @20% | gross `1.01` (HALF_UP) | `0.20` | **`1.21`** |
| 3 × 0.10 @20% | gross `0.30` | `0.06` | **`0.36`** |

Mixed rates: lines `3 × 33.33 @18%`, `2 × 10.005 @18%`, `1 × 50.00 @8%` →
group 18% base `99.99 + 20.01 = 120.00` → `21.60`; group 8% base `50.00` → `4.00`;
`subtotal 170.00`, `tax 25.60`, **`grand_total 195.60`**.

Allocation: `3 × 0.07 @18%` → exact share `0.0126` each, floored `0.01` each summing to `0.03`;
group `round2(0.21 × 0.18) = 0.04`, so one cent is outstanding; the discarded fractions tie at
`0.0026`, so the lowest `line_no` takes it → line taxes `0.02, 0.01, 0.01`,
**`grand_total 0.25`**.

### Why largest remainder, and not "residual to the largest line"

A7's first implementation rounded each line independently and gave the **entire** residual to the
largest line, on the stated assumption that the residual was "a cent or two". That assumption is
false: each per-line rounding can be off by up to half a cent, so the residual scales with the line
count. Measured independently of the engine, for `n` lines of taxable `0.07` @18%:

| n | group tax | per-line | sum | residual | target line's tax | correct |
|---|---|---|---|---|---|---|
| 2 | `0.03` | `0.01` | `0.02` | `0.01` | `0.02` | `0.01` |
| 10 | `0.13` | `0.01` | `0.10` | `0.03` | `0.04` | `0.01` |
| 50 | `0.63` | `0.01` | `0.50` | `0.13` | `0.14` | `0.01` |
| 100 | `1.26` | `0.01` | `1.00` | `0.26` | **`0.27`** | `0.01` |

At `n = 100` one line carried twenty-seven times its correct tax, on a document a customer reads.

**The reason this matters beyond the fix:** every reconciliation identity in §A7.6 held throughout —
`Σ tax_amount == tax_amount`, `net + tax == grand_total`, all of it. The defect was invisible to
every totals-based test, and would have been invisible to any written later. It was found by review.
`test_no_line_absorbs_the_whole_group_residual` now guards it by asserting each line's tax is within
one cent of its independently derived exact share; that assertion fails under the old rule at
`n ≥ 10` and passes under largest remainder at every `n`.

Freight: `1 × 100 @20%` with `freight_cost 5.005` → `freight_amount 5.01`, `net 105.01`,
`tax 20.00`, **`grand_total 125.01`**. Note `Σ line_total = 120.00`, so the document identity is
`Σ line_total + freight_amount = grand_total` (freight is not a line).

## A7.6 Invariants a conforming implementation must satisfy

For every successful response:

1. `Decimal(str(v)).as_tuple().exponent >= -2` for every money field.
2. `subtotal_amount − discount_amount + freight_amount == net_amount`.
3. `net_amount + tax_amount == grand_total`.
4. `Σ line_items[].tax_amount == totals.tax_amount`.
5. `Σ line_items[].line_total + freight_amount == grand_total`.
6. Identical input produces byte-identical money output.
7. Each line's `tax_amount` is within one cent of `taxable × rate / 100`. Invariants 1-6 are all
   satisfied by an allocation that is badly wrong per line, so this one is not optional.

## A7.7 Backward compatibility

- Wire format, field names and field meanings are unchanged. `line_total` remains **tax-inclusive**.
- `generate_document_number`, `render_document_number` and all A4/A5/A6 numbering semantics are
  untouched.
- The full pre-A7 suite (76 tests) passes unmodified, because `test_money_contract.py` asserts
  self-consistency, determinism and input bounds rather than the convention.
- **This is a deliberate behavior change**: monetary results move (`117.9882` → `117.99`). Any
  snapshot persisted under pre-A7 behavior will not reproduce. No production snapshots exist, so
  the cost is zero today and rises the moment the online vertical slice ships.

## A7.8 Out of scope

Zero- and three-decimal currencies; a `Decimal` wire format; unit-price input *scale* limits (the
magnitude bound in §A7.3b is a sanity guard, not a precision policy); an upper bound on
`freight_cost` beyond that magnitude guard, which is deliberately left to business rules rather than
the engine; `erp_data` persistence rounding; PDF/XLSX presentation.

---

**Separate claims, not one.** "A7 is correct" and "the deployed engine behaves correctly" are
independent: `/opt/python-erp` is twelve commits behind this branch, and the image rebuild that
would ship A7 also ships those twelve. Sequencing that is a deployment decision, not an A7 one.
