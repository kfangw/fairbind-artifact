# ADR 0011: Exposure condition and rate cap keyed to registered bond

Status: Accepted 2026-09-22, together with ADR 0012 and ADR 0013. Supersedes the
per-`sellerId` reading of the rate condition in `profile-v1.md` section 2.

## Problem

The version 1 token bucket is a field of the seller registration
(`contract-interface-v1.md` section 11, `SellerView.bucketBalancePpm`), and the
reserved seller penalty is also per registration
(`fairbind-v1.md` section 5.2). Changing the profile, the signing key, or the
advertised claims requires a new registration, so a seller that operates several
endpoints already holds several `sellerId` values by design.

That makes the admission inequality in `profile-v1.md` section 2 a per-identity
bound. An operator that splits one service across `N` registrations obtains `N`
buckets, `N` times the settlement rate, and `N` times the value exposed during
the enforcement delay, while each registration posts only `sellerPenalty`. The
capped quantity is identity count, which nobody bounds, rather than capital,
which the protocol can observe. The exposure argument does not survive this.

The measured seller-rate distribution makes the gap material rather than
theoretical: in the fourteen-day ledger recount the top one percent of receiving
addresses accounts for 92.5 percent of settlements, and peak one-hour rates run
from a median of one per hour to 4,201 per hour. Splitting is cheap exactly
where the value is.

## Decision

Key the token bucket and the exposure condition to a registered bond, not to a
seller registration.

1. A new registry object, the bond account, holds the bond balance, the reserved
   seller penalty, the token-bucket state, and the bond lifecycle state. It is
   identified by `bondId` and owned by one address.
2. A seller registration names a `bondId`. It no longer carries a bond balance,
   a penalty reservation, or bucket state. Several registrations may name the
   same `bondId`; a registration names exactly one.
3. `settle` updates and consumes the bucket of the registration's bond account.
   Registrations under one bond share one bucket, so their combined settlement
   rate is bounded by the bond's parameters, and the order in which they consume
   it is first come, first served.
4. Bucket parameters scale with the bond. The profile fixes a unit bucket, and a
   bond account of balance `B` receives
   `bucketCapacity = q * floor(B / sellerPenalty)` and
   `maxRatePpmPerBlock`, `refillPpmPerBlock` scaled by the same integer factor.
   The factor is recomputed on top-up and on any slash, and a slash lowers it.
5. Bucket state is never reset by adding or removing a seller registration. A
   new registration under an existing bond inherits the current bucket balance.
6. The exposure condition is checked against the bond, not the identity. Profile
   admission keeps the division-free form of `profile-v1.md` section 2 but reads
   it per unit of `sellerPenalty`, and the bond requirement becomes
   `B >= g * (1/p + Lambda * max(0, L - D))`, where `Lambda` is the bond's
   configured maximum settlement rate, `L` is the enforcement delay defined in
   ADR 0012, and `D` is `deferBlocks`. The rate cap is a required component only
   when `D < L`.

## Burst capacity

`q` is set from the measured peak one-hour rate, not from a window average. The
fourteen-day average understates the top of the distribution by one to two
orders of magnitude for the same address: the largest observed address averages
557 settlements per hour over fourteen days and reaches 4,201 in its busiest
hour. A bucket sized from the average would reject a compliant seller during
every normal burst, and the rejection would land on the sellers that carry most
of the value.

The profile therefore records `q` as the peak one-hour settlement count a single
unit of `sellerPenalty` is allowed to cover, converted to blocks by the profile
epoch schedule, and records the percentile of the measured peak-hour
distribution it was taken from. The default is the ninety-ninth percentile of
the per-class peak one-hour distribution, and an operator may raise it; the
maximum is not a usable default because it is set by a single address. Sustained
rate stays governed by `refillPpmPerBlock`; `q` governs only the burst.
Rejection frequency under the chosen `q` is a reported limitation, measured
against the same distribution.

## What identity splitting now costs

Under the decision, `N` registrations under one bond share one bucket and give
no rate advantage. Obtaining `N` times the rate requires `N` times the bond, so
the cost of splitting is linear in capital rather than in registration
transactions. This is the intended property: the protocol does not try to detect
that two identities belong to one operator, and does not rely on reputation
propagation or on a root identity. It makes the split economically neutral.

Splitting across distinct bonds remains possible and remains correct. Each bond
then carries its own exposure and its own penalty reservation, and the sum of
the bonds covers the sum of the exposures. What is removed is the case where one
unit of capital backs several buckets.

## Spec sections that change

- `fairbind-v1.md` section 5.2: seller registration fields; bond balance,
  reserved penalty and bucket state move out to the bond account. Add section
  5.4 for the bond account.
- `fairbind-v1.md` section 19: the rate limit is described per bond.
- `fairbind-v1.md` section 21.3: seller state machine gains the bond lifecycle
  as a separate machine; seller states no longer own the bond.
- `fairbind-v1.md` section 21.5: add `registerBond`, `topUpBond`,
  `requestBondExit`, `finalizeBondExit`; `registerSeller` takes `bondId`;
  `topUpSellerBond` is removed.
- `profile-v1.md` section 1: bucket units are per unit of `sellerPenalty`.
- `profile-v1.md` section 2: the rate inequality is stated per bond unit, and
  `q` acquires a recorded provenance field.
- `profile-v1.md` section 4: the penalty floor and the bond requirement are
  restated with `Lambda` as a bond parameter.
- `contract-interface-v1.md` section 3: `ServiceProfileInput` gains the
  peak-rate provenance field inside `parameterHash`.
- `contract-interface-v1.md` section 11: `SellerView` loses `bond`,
  `bucketBalancePpm`, `bucketUpdatedBlock` and gains `bondId`; a new `BondView`
  carries them. `SellerQuote` reads the bond's bucket.
- `lifecycle-v1.md` section 2: unchanged deadlines, but the release and
  retention text refers to the bond account for penalty availability.
- `sortition-v1.md`: unchanged. Verifier capital is untouched by this ADR.

## Invariants and tests that change

Changed invariants in `fairbind-v1.md` section 22:

- Invariant 11 is restated per bond: the reserved seller penalty of a bond
  remains available until that bond's first effective seller failure.
- Invariant 13 gains the bond bucket: a failed token transfer leaves the bond
  bucket unchanged, not the seller bucket.

New invariants:

- The sum of settlements admitted against one bond in any `enforcementBlocks`
  window does not exceed that bond's configured maximum, regardless of how many
  seller registrations name it.
- A seller registration names exactly one bond account for its lifetime.
- Adding or removing a seller registration does not increase any bond's bucket
  balance.
- A bond's scaling factor never increases without a token transfer into the bond
  account.

Tests to add or change: bucket sharing across two and three registrations under
one bond, including interleaved settlements in one block; bucket balance
continuity across registration creation and exit; scaling-factor recomputation
on top-up and on slash, including the rounding direction; rejection at the
bucket boundary attributed to the bond rather than the registration; the
existing per-seller bucket regression tests re-pointed at the bond account; and
a splitting test that asserts `N` registrations under one bond admit no more
settlements per window than one.

## Alternatives considered

Per-identity entry cost. Charge a registration fee large enough to bound `N`.
Rejected: the bound depends on an operator's capital, which is exactly the
quantity the decision already uses, and the fee is a worse instrument because it
is not refundable and not proportional to the exposure created.

Operator-level attribution. Detect that several identities share an operator and
aggregate their buckets. Rejected: it requires an identity claim the protocol
cannot check, and it fails against an operator that does not cooperate.

Value-weighted buckets. Charge bucket units in proportion to purchase value
instead of one unit per settlement. Rejected for version 1: `maxPurchaseValue`
already bounds per-purchase value, and value weighting changes the admission
inequality into a form that needs a second calibration input.
