// Command fairbind-case-paths writes the per-case result columns of
// experiments/metrics.md (case_path_blocks, keeper_delay_sum_blocks,
// case_path_minus_keeper and, with -worst-path, worst_path_case_blocks) for
// one seller of a deployment as observation rows. It reads the chain and the
// keeper's call log (its standard output or its events file). With
// -finite-attack m it also writes the finite-attack episode columns of a
// seller that cheated on its first m settled sales.
//
//	fairbind-case-paths -rpc http://127.0.0.1:8545 -contract 0x.. -seller 1 \
//	    -keeper-log keeper.log -run-id run-1 [-worst-path] [-finite-attack 3] [-out observations/case-paths.jsonl]
package main

import (
	"context"
	"flag"
	"fmt"
	"os"

	"example.org/fairbind/services/internal/casepath"
)

func main() {
	rpc := flag.String("rpc", os.Getenv("FAIRBIND_RPC_URL"), "JSON-RPC URL (default $FAIRBIND_RPC_URL)")
	contract := flag.String("contract", "", "FairBind router address")
	seller := flag.Uint("seller", 0, "seller id")
	keeperLog := flag.String("keeper-log", "", "keeper call log (JSON lines)")
	runID := flag.String("run-id", "", "observation id of the run")
	worst := flag.Bool("worst-path", false, "the run carried the worst-path directive")
	out := flag.String("out", "", "observation rows file (default standard output)")
	finite := flag.Int("finite-attack", 0, "cheated sales of a finite attack (0: none)")
	flag.Parse()
	if err := run(*rpc, *contract, uint32(*seller), *keeperLog, *runID, *worst, *finite, *out); err != nil {
		fmt.Fprintln(os.Stderr, "fairbind-case-paths:", err)
		os.Exit(1)
	}
}

func run(rpc, contract string, seller uint32, keeperLog, runID string, worst bool, finite int, out string) error {
	if rpc == "" || contract == "" || seller == 0 || runID == "" {
		return fmt.Errorf("-rpc, -contract, -seller and -run-id are required")
	}
	var calls []casepath.KeeperCall
	if keeperLog != "" {
		f, err := os.Open(keeperLog)
		if err != nil {
			return err
		}
		defer f.Close()
		if calls, err = casepath.ParseKeeperLog(f); err != nil {
			return err
		}
	}
	client := casepath.NewRPC(rpc, contract)
	cases, err := casepath.Collect(context.Background(), client, seller, calls)
	if err != nil {
		return err
	}
	rows := casepath.Rows(runID, cases, worst)
	if finite > 0 {
		e, err := casepath.FiniteAttack(context.Background(), client, seller, finite)
		if err != nil {
			return err
		}
		rows = append(rows, casepath.EpisodeRows(runID, e)...)
	}
	w := os.Stdout
	if out != "" {
		f, err := os.OpenFile(out, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			return err
		}
		defer f.Close()
		w = f
	}
	return casepath.WriteRows(w, rows)
}
