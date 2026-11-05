# FairBind Governance Version 1

Status: Release candidate for implementation

FairBind version 1 separates immutable purchase rules from controls that admit
new activity. Governance cannot rewrite a profile, receipt, purchase, anchor,
case, deadline, assignment, or fund destination.

## 1. Contract form

The FairBind contract is not upgradeable. It has no delegate-call proxy,
implementation pointer, or administrative storage-write escape hatch. A protocol
revision deploys a new contract and creates new service profiles. Existing
purchases finish under the old deployment.

## 2. Roles

| Role | Authority |
| --- | --- |
| governance timelock | Creates immutable deadline configurations and profiles, activates or deactivates profiles, unpauses new activity, changes the emergency guardian, and starts role transfer. |
| emergency guardian | Pauses new seller registration, new verifier registration, and new settlement. It cannot unpause. |
| penalty treasury | Receives verifier late penalties and automatic-review wrong-verdict penalties. Seller deductions and forfeitures stay locked in the contract (ADR 0022). Its address is immutable and it has no protocol authority. |
| public caller | Executes timeout, sealing, case finalization, refund, and release functions when their state predicates hold. |

No role can redirect a refund, seller release, bond withdrawal, deposit award,
or penalty after the corresponding registration or purchase exists.

## 3. Delay

A public-network deployment uses a timelock of at least 172,800 seconds, or two
days, for administrative calls. The timelock clock uses block timestamps because
it schedules governance actions rather than protocol verdicts. Purchase and case
deadlines continue to use block numbers.

The initial public-testnet administrator is a two-of-three multisignature wallet
behind that timelock. The deployment manifest records its address, members,
threshold, delay, guardian, and transaction that granted each role. Local-only
development may use one account and zero delay, but result metadata must state
that difference.

## 4. Emergency pause

The pause blocks only calls that add new exposure:

- service-profile activation;
- seller and verifier registration;
- settlement;
- expansion of a verifier's supported classes.

The pause MUST NOT block anchoring, sealing, sample opening, serve and publication
steps, disputes, judgments, appeals, evidence disclosure, timeout calls, case
finalization, refunds, releases, or exits. Deactivating a profile follows the
same rule. Existing obligations remain executable.

## 5. Role transfer and loss

Governance role transfer uses a two-step accept procedure. The current timelock
nominates another timelock and records an acceptance timestamp no earlier than
its own minimum delay. The nominee accepts after that timestamp. Guardian
replacement is a delayed timelock transaction followed by nominee acceptance.
Nominees must satisfy the constructor's nonzero and separation rules.
Renouncing the final governance role is not supported.

If every governance signer becomes unavailable, existing purchases can still
finish because their progress calls are public. New profile activation and
unpausing remain unavailable. This failure mode stops growth but does not lock
purchase principal.

## 6. Deployment record

Each deployment commits a manifest containing:

```text
chainId
contractAddress
deploymentToken
sourceRevision
compilerVersion
constructorArguments
governanceTimelock
governanceDelaySeconds
guardian
penaltyTreasury
profileIds and parameter hashes
creationTransaction
role-grant transactions
```

The repository stores a manifest conforming to
[`../../schemas/deployment-manifest-v1.schema.json`](../../schemas/deployment-manifest-v1.schema.json)
before using the deployment in an experiment.
Mainnet deployment is outside the version 1 implementation milestone.
