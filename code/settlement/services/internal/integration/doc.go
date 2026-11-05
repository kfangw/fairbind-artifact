// Package integration runs the service processes against a local Anvil
// deployment made by scripts/deploy-local.sh. The tests start the keeper,
// verifier, facilitator, seller and buyer binaries as subprocesses, drive
// purchases through the buyer control API, advance blocks with anvil_mine and
// read every state transition from the chain and the services' state files.
//
// They need anvil, cast and forge on PATH, contract artifacts in out/, and
// FAIRBIND_INTEGRATION=1; otherwise they are skipped. Run them with
// `make integration-check`.
package integration
