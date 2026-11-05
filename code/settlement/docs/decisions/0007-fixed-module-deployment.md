# ADR 0007: Fixed Modules with One Settlement Address

Status: Implemented; 39 regression checks and ABI/storage/size checks passed; clean-revision local deployment recorded separately

## Decision

Split the monolith into a shared `FairBindCore` and six separately deployed
modules: Registry, Settlement, Sampling, Delivery, Publication, and Recovery.
The `FairBind` contract retains explicit typed entry points and delegates each
mutating entry point to a constructor-fixed module. Read-only functions execute
in the router. There is no fallback-based selector registry, upgrade method,
or arbitrary delegate-call entry point.

The constructor gains a fixed array of six module addresses. Modules must report
the matching role, deployment token, and penalty treasury. These metadata checks
are configuration checks, not a proof of arbitrary supplied bytecode. A deployment
must verify module code against the built artifact and record code hashes.
Deployment is an authorized construction step; a governance call cannot replace
modules afterward. Modules reject direct mutating calls.

All original fields remain in the same storage order and retain the same types.
The router and modules inherit one storage definition. Module addresses and the
module direct-call guard are immutable, so they add no storage slots. The token
and treasury immutables are initialized consistently in every component. The
shared reentrancy lock remains slot 5 and executes in router storage.

## Compatibility

Original runtime selectors and tuple encodings must be preserved. Six module
address getters are new. Solidity source callers use `FairBindCore` for nested
types, enums and errors; ABI clients retain the same encoding. Purchase identifiers,
seller receipt domains, caller identity, custody and events use the router address.
The constructor signature changes because modules deploy in separate transactions;
embedding all module creation code in the router would defeat initcode limits.

## Property review

P1 retains the same nonce, key, atomic token-call and lock rules. P2 retains the
same fund priority and delivery branches. P3 and P4 retain the same selection and
review rules, including their unresolved proof assumptions. This packaging work
does not resolve the effective-bond versus actual-bond liability inconsistency.
The existing buyer-recovery/active-case interaction also requires separate review.

## Required checks

Run the existing suite on the modular deployment, compare baseline ABI and storage
layout, check direct module calls and shared lock behavior, measure every runtime
and initcode, and deploy each component on a local chain enforcing normal limits.
Passing these checks establishes packaging conformance, not complete M1-M5 safety.
