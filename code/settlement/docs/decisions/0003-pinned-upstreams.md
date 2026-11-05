# ADR 0003: Pinned Upstreams without Git Submodules

Status: Accepted
Date: 2026-09-04

## Context

FairBind needs repeatable integration with the gateway, arena, and x402 specification. Git submodules preserve revisions but make a clean artifact checkout and automated review more fragile. Copying either full repository would hide upstream changes and duplicate maintenance.

## Decision

`UPSTREAMS.lock.json` records exact revisions and roles. CI checks out an upstream only in the job that needs it. Runtime code depends on public interfaces, HTTP contracts, versioned trace files, or minimal copied interfaces with retained license notices.

## Consequences

An upstream update is an explicit review. The updating change must modify the lock file, run differential tests, and describe any protocol drift.
