// Command fairbind-verifier runs the verifier worker loop.
//
//	fairbind-verifier -config verifier.json [-once]
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"path/filepath"
	"runtime/debug"
	"sort"
	"syscall"

	"example.org/fairbind/runtime/evidence"
	"example.org/fairbind/runtime/judgment"
	"example.org/fairbind/runtime/ledger"
	gate "example.org/fairbind/runtime/verifier"
	"example.org/fairbind/services/internal/directive"
	x402chain "example.org/fairbind/services/internal/x402/chain"
	verifier "example.org/fairbind/services/verifier"
)

func main() {
	path := flag.String("config", "", "path to the JSON configuration file")
	once := flag.Bool("once", false, "run a single pass and exit")
	directivePath := flag.String("directive", os.Getenv("FAIRBIND_DIRECTIVE"), "scenario directive file (default $FAIRBIND_DIRECTIVE)")
	progress := flag.String("progress", "", "write the head block of every completed pass to this file")
	flag.Parse()
	log := slog.New(slog.NewJSONHandler(os.Stderr, nil))
	if err := run(*path, *once, *directivePath, *progress, log); err != nil {
		log.Error("verifier stopped", "err", err)
		os.Exit(1)
	}
}

func run(path string, once bool, directivePath, progress string, log *slog.Logger) error {
	if path == "" {
		return fmt.Errorf("-config is required")
	}
	cfg, err := verifier.LoadConfig(path)
	if err != nil {
		return err
	}
	dir, err := directive.Load(directivePath, directive.RoleVerifier)
	if err != nil {
		return err
	}
	state, err := verifier.OpenStore(cfg.StateDir)
	if err != nil {
		return err
	}
	defer state.Close()
	objects, err := evidence.NewStore(filepath.Join(cfg.StateDir, "objects"), cfg.MaxEvidenceBytes)
	if err != nil {
		return err
	}
	source, err := ledger.New(ledger.Config{URL: cfg.RPCURL, ChainID: cfg.ChainID, Contract: cfg.ContractAddr, Timeout: cfg.RPCTimeout, MaxResponseBytes: 1 << 20, MaxClaimsBytes: cfg.MaxClaimsBytes})
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	chain, err := verifier.NewRPC(cfg.RPCURL, cfg.ChainID, cfg.ContractAddr, cfg.MaxLogRange, cfg.RPCTimeout)
	if err != nil {
		return err
	}
	// A read-only client for the case view a serve authorization needs
	// (caseOpenedBlock). It never sends a transaction, so From is left zero.
	cases, err := x402chain.NewRPC(ctx, x402chain.RPCConfig{URL: cfg.RPCURL, ChainID: cfg.ChainID, Contract: x402chain.Address(cfg.ContractAddr)})
	if err != nil {
		return err
	}
	signer := judgment.KeystoreSigner{CastPath: cfg.CastPath, KeystorePath: cfg.Keystore, PasswordFile: cfg.PasswordFile}
	sig := gate.CastVerifier{Path: cfg.CastPath}
	// Configured pipelines are routed by predicate identifier; any other
	// identifier the gate accepts receives an INCONCLUSIVE envelope.
	router, err := verifier.NewPredicateRouter(cfg, objects, sig, revision())
	if err != nil {
		return err
	}
	w := &verifier.Worker{
		Opts:      verifier.Options{VerifierID: cfg.VerifierID, Bindings: cfg.Bindings, SubmitMarginBlocks: cfg.SubmitMarginBlocks, StartBlock: cfg.StartBlock},
		Source:    source,
		Chain:     chain,
		Seller:    verifier.HTTPSeller{ChainID: cfg.ChainID, Contract: cfg.ContractAddr, Endpoints: cfg.SellerURLs, Cases: cases, Signer: signer},
		Predicate: router,
		Outbox:    judgment.Outbox{Dir: filepath.Join(cfg.StateDir, "outbox"), Objects: objects, Verifier: sig},
		Signer:    signer,
		Sender:    judgment.LocalRelay{URL: cfg.Relay.URL, ChainID: cfg.ChainID, Contract: cfg.ContractAddr, From: cfg.RelayFrom, Gas: cfg.Relay.Gas},
		State:     state,
		Log:       log,

		ProgressFile: progress,
	}
	if dir != nil && dir.WorstPath != nil {
		w.Directed = &verifier.Directed{Path: dir.WorstPath, Chain: chain, Contract: cfg.ContractAddr, From: cfg.RelayFrom, Objects: objects}
		log.Info("worst-path directive", "maxReplacedAssignments", dir.WorstPath.MaxReplacedAssignments,
			"verdicts", []string{dir.WorstPath.InitialVerdict, dir.WorstPath.PartyReviewVerdict, dir.WorstPath.TiebreakVerdict})
	}
	if once {
		return w.Tick(ctx)
	}
	var pipelines []string
	for id := range router.ByID {
		pipelines = append(pipelines, fmt.Sprintf("0x%x", id))
	}
	sort.Strings(pipelines)
	log.Info("verifier started", "verifierId", cfg.VerifierID, "poll", cfg.Poll.String(), "pipelines", pipelines)
	if err = w.Run(ctx, cfg.Poll); err == context.Canceled {
		return nil
	}
	return err
}

// revision names the build in implementation objects: the VCS revision
// embedded by the Go toolchain, marked when the tree was modified.
func revision() string {
	info, ok := debug.ReadBuildInfo()
	if !ok {
		return "unknown"
	}
	rev, dirty := "unknown", false
	for _, s := range info.Settings {
		switch s.Key {
		case "vcs.revision":
			rev = s.Value
		case "vcs.modified":
			dirty = s.Value == "true"
		}
	}
	if dirty {
		rev += "-modified"
	}
	return rev
}
