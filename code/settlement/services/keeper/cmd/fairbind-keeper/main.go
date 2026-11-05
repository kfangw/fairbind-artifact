// Command fairbind-keeper runs the FairBind keeper against one deployment.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"example.org/fairbind/runtime/judgment"
	"example.org/fairbind/services/internal/directive"
	"example.org/fairbind/services/keeper"
)

func main() {
	configPath := flag.String("config", "", "path to the keeper JSON configuration")
	once := flag.Bool("once", false, "run one tick and exit")
	directivePath := flag.String("directive", os.Getenv("FAIRBIND_DIRECTIVE"), "scenario directive file (default $FAIRBIND_DIRECTIVE)")
	events := flag.String("events", os.Getenv("FAIRBIND_EVENTS"), "append call_sent rows to this JSON lines file (default $FAIRBIND_EVENTS)")
	progress := flag.String("progress", "", "write the head block of every completed pass to this file")
	flag.Parse()
	if err := run(*configPath, *once, *directivePath, *events, *progress); err != nil {
		fmt.Fprintln(os.Stderr, "fairbind-keeper:", err)
		os.Exit(1)
	}
}

func run(path string, once bool, directivePath, eventsPath, progressPath string) error {
	if path == "" {
		return fmt.Errorf("-config is required")
	}
	cfg, err := keeper.LoadConfig(path)
	if err != nil {
		return err
	}
	contract, _ := keeper.ParseHexAddress(cfg.Contract)
	from, _ := keeper.ParseHexAddress(cfg.From)
	chain, err := keeper.NewRPC(cfg.RPCURL, cfg.ChainID, contract, from, cfg.RPCTimeout())
	if err != nil {
		return err
	}
	dir, err := directive.Load(directivePath, directive.RoleKeeper)
	if err != nil {
		return err
	}
	store, err := keeper.OpenStore(cfg.StateFile)
	if err != nil {
		return err
	}
	defer store.Close()
	k := &keeper.Keeper{
		Chain:       chain,
		Sender:      judgment.LocalRelay{URL: cfg.RPCURL, ChainID: cfg.ChainID, Contract: contract, From: from, Gas: cfg.Gas},
		Contract:    contract,
		Store:       store,
		Enabled:     cfg.EnabledActions(),
		ResendAfter: cfg.ResendAfterBlocks,
		MaxLogRange: cfg.MaxLogRange,
		StartBlock:  cfg.StartBlock,
	}
	if cfg.ReceiptsDir != "" {
		k.Receipts = keeper.DirReceiptList{Dir: cfg.ReceiptsDir}
	}
	if dir != nil && dir.WorstPath != nil {
		k.WorstPath = true
		chain.SimulateAt = "pending"
		if dir.KeeperDelay != nil {
			k.DelayBlocks = dir.KeeperDelay.BudgetBlocks
		}
	}
	var events *json.Encoder
	if eventsPath != "" {
		f, err := os.OpenFile(eventsPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			return err
		}
		defer f.Close()
		events = json.NewEncoder(f)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	logger := json.NewEncoder(os.Stdout)
	for {
		rep, err := k.Tick(ctx)
		if err != nil {
			logger.Encode(map[string]any{"time": time.Now().UTC().Format(time.RFC3339Nano), "error": err.Error()})
		}
		for _, o := range rep.Outcomes {
			if o.Status == "pending" || o.Status == "disabled" {
				continue
			}
			line := map[string]any{"time": time.Now().UTC().Format(time.RFC3339Nano), "finalized": rep.Finalized, "head": rep.Head,
				"action": o.Action.Name, "key": o.Action.Key, "status": o.Status, "tx": o.Tx, "error": o.Err,
				"due": o.Action.Due, "nonce": o.Action.Nonce, "epoch": o.Action.Epoch}
			logger.Encode(line)
			if events != nil && o.Status == "sent" {
				line["event"] = "call_sent"
				events.Encode(line)
			}
		}
		if rep.Head > 0 {
			if perr := directive.WriteProgress(progressPath, rep.Head); perr != nil {
				logger.Encode(map[string]any{"time": time.Now().UTC().Format(time.RFC3339Nano), "error": perr.Error()})
			}
		}
		if once {
			return err
		}
		select {
		case <-ctx.Done():
			return nil
		case <-time.After(cfg.PollInterval()):
		}
	}
}
