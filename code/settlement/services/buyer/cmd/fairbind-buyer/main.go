// Command fairbind-buyer runs a FairBind buyer with a loopback control API.
//
//	fairbind-buyer -config buyer.json
package main

import (
	"context"
	"flag"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/buyer"
	"example.org/fairbind/services/internal/directive"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/ethkey"
	"example.org/fairbind/services/internal/x402/fsstore"
)

type config struct {
	Listen      string    `json:"listen"`
	DataDir     string    `json:"dataDir"`
	Network     string    `json:"network"`
	RPCURL      string    `json:"rpcUrl"`
	ChainID     uint64    `json:"chainId"`
	Contract    x402.Addr `json:"contract"`
	KeyFile     string    `json:"keyFile"`
	MaxPrice    uint64    `json:"maxPrice"`
	TickSeconds int       `json:"tickSeconds"`
}

func main() {
	path := flag.String("config", "buyer.json", "JSON configuration file")
	directivePath := flag.String("directive", os.Getenv("FAIRBIND_DIRECTIVE"), "scenario directive file (default $FAIRBIND_DIRECTIVE)")
	flag.Parse()
	logger := log.New(os.Stderr, "buyer ", log.LstdFlags)
	dir, err := directive.Load(*directivePath, directive.RoleBuyer)
	if err != nil {
		logger.Fatal(err)
	}
	var cfg config
	if err := x402.LoadConfig(*path, &cfg); err != nil {
		logger.Fatal(err)
	}
	host, _, err := net.SplitHostPort(cfg.Listen)
	if ip := net.ParseIP(host); err != nil || ip == nil || !ip.IsLoopback() {
		logger.Fatal("listen must be a loopback address: the control API has no authentication")
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	key, err := ethkey.LoadPrivateKeyFile(cfg.KeyFile)
	if err != nil {
		logger.Fatal(err)
	}
	client, err := chain.NewRPC(ctx, chain.RPCConfig{URL: cfg.RPCURL, ChainID: cfg.ChainID, Contract: chain.Address(cfg.Contract), From: key.Address()})
	if err != nil {
		logger.Fatal(err)
	}
	store, err := fsstore.Open(cfg.DataDir)
	if err != nil {
		logger.Fatal(err)
	}
	defer store.Close()
	b, err := buyer.New(ctx, buyer.Options{Network: cfg.Network, Signer: key, Address: protocol.Address(key.Address()),
		MaxPrice: cfg.MaxPrice, Log: logger, WorstPath: dir != nil && dir.WorstPath != nil}, client, store)
	if err != nil {
		logger.Fatal(err)
	}
	tick := time.Duration(cfg.TickSeconds) * time.Second
	if tick <= 0 {
		tick = 2 * time.Second
	}
	go b.Run(ctx, tick)
	srv := &http.Server{Addr: cfg.Listen, Handler: b.Handler(), ReadHeaderTimeout: 10 * time.Second}
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		srv.Shutdown(shutdown)
	}()
	logger.Printf("control API on %s for payer %s", cfg.Listen, x402.Addr(key.Address()))
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		logger.Fatal(err)
	}
}
