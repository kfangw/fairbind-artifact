// Command fairbind-facilitator runs the FairBind x402 facilitator.
//
//	fairbind-facilitator -config facilitator.json
package main

import (
	"context"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"example.org/fairbind/services/facilitator"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/fsstore"
)

type config struct {
	Listen           string    `json:"listen"`
	DataDir          string    `json:"dataDir"`
	Network          string    `json:"network"`
	RPCURL           string    `json:"rpcUrl"`
	ChainID          uint64    `json:"chainId"`
	Contract         x402.Addr `json:"contract"`
	From             x402.Addr `json:"from"`
	Token            x402.Addr `json:"token"`
	TokenName        string    `json:"tokenName"`
	TokenVersion     string    `json:"tokenVersion"`
	SettlementSchema string    `json:"settlementSchema"`
}

func main() {
	path := flag.String("config", "facilitator.json", "JSON configuration file")
	flag.Parse()
	logger := log.New(os.Stderr, "facilitator ", log.LstdFlags)
	var cfg config
	if err := x402.LoadConfig(*path, &cfg); err != nil {
		logger.Fatal(err)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	rawSchema, err := os.ReadFile(cfg.SettlementSchema)
	if err != nil {
		logger.Fatal(err)
	}
	schema, err := x402.InlineSchema(rawSchema)
	if err != nil {
		logger.Fatal(err)
	}
	client, err := chain.NewRPC(ctx, chain.RPCConfig{URL: cfg.RPCURL, ChainID: cfg.ChainID, Contract: chain.Address(cfg.Contract), From: chain.Address(cfg.From)})
	if err != nil {
		logger.Fatal(err)
	}
	store, err := fsstore.Open(cfg.DataDir)
	if err != nil {
		logger.Fatal(err)
	}
	defer store.Close()
	f, err := facilitator.New(facilitator.Options{Network: cfg.Network, Token: chain.Address(cfg.Token), TokenName: cfg.TokenName, TokenVersion: cfg.TokenVersion,
		SettlementSchema: schema, Log: logger}, client, store)
	if err != nil {
		logger.Fatal(err)
	}
	n, err := f.Recover(ctx)
	if err != nil {
		logger.Fatal(err)
	}
	logger.Printf("recovered %d uncertain settlements", n)
	srv := &http.Server{Addr: cfg.Listen, Handler: f.Handler(), ReadHeaderTimeout: 10 * time.Second}
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		srv.Shutdown(shutdown)
	}()
	logger.Printf("listening on %s", cfg.Listen)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		logger.Fatal(err)
	}
}
