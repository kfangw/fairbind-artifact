# Contracts

This directory contains the Solidity reference implementation and Foundry tests
for FairBind milestones M1 through M3.

`src/FairBind.sol` implements seller and verifier registration, EIP-3009
settlement, exposure accounting, epoch anchoring, nonce sampling, verifier
assignment, redelivery, publication, failure proofs, and refunds.
`src/FairBindMerkle.sol` implements the protocol's sorted Merkle tree rules.
The tests are separated by milestone and use shared cross-language vectors where
the specification requires exact byte compatibility.

Run the complete suite from the repository root with `make check`. Generate or
verify gas measurements with Foundry's snapshot command. Contract changes must
follow `docs/spec/fairbind-v1.md`.

The current reference contract is larger than the EIP-170 deployed-code limit.
M5 will divide it into fixed, non-upgradeable modules before a public-network
deployment while retaining the same external protocol behavior.
