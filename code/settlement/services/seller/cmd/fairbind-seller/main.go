// Command fairbind-seller runs a FairBind resource server that sells static
// resources from files.
//
//	fairbind-seller -config seller.json
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

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/judgment"
	"example.org/fairbind/services/internal/directive"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/ethkey"
	"example.org/fairbind/services/internal/x402/fsstore"
	"example.org/fairbind/services/seller"
)

type routeConfig struct {
	Path        string        `json:"path"`
	Description string        `json:"description"`
	MimeType    string        `json:"mimeType"`
	BodyFile    string        `json:"bodyFile"`
	Preimage    x402.Preimage `json:"preimage"`
	// CheatBodyFile is served, with the same preimage, on the sales a
	// finite-attack directive cheats on.
	CheatBodyFile string `json:"cheatBodyFile,omitempty"`
}

type keystoreConfig struct {
	CastPath     string `json:"castPath"`
	KeystorePath string `json:"keystorePath"`
	PasswordFile string `json:"passwordFile"`
}

type config struct {
	Listen            string          `json:"listen"`
	DataDir           string          `json:"dataDir"`
	PublicURL         string          `json:"publicUrl"`
	Network           string          `json:"network"`
	RPCURL            string          `json:"rpcUrl"`
	ChainID           uint64          `json:"chainId"`
	Contract          x402.Addr       `json:"contract"`
	Owner             x402.Addr       `json:"owner"`
	SellerID          uint32          `json:"sellerId"`
	SigningKeyFile    string          `json:"signingKeyFile,omitempty"`
	Keystore          *keystoreConfig `json:"keystore,omitempty"`
	FacilitatorURL    string          `json:"facilitatorUrl"`
	ServiceName       string          `json:"serviceName"`
	ServiceClass      string          `json:"serviceClass"`
	ProfileHash       x402.H32        `json:"profileHash"`
	CanonicalHeaders  []string        `json:"canonicalHeaders"`
	Price             uint64          `json:"price"`
	MaxTimeoutSeconds uint64          `json:"maxTimeoutSeconds"`
	TokenName         string          `json:"tokenName"`
	TokenVersion      string          `json:"tokenVersion"`
	ExtensionSchema   string          `json:"extensionSchema"`
	SettlementSchema  string          `json:"settlementSchema"`
	ClaimsFile        string          `json:"claimsFile"`
	TickSeconds       int             `json:"tickSeconds"`
	Routes            []routeConfig   `json:"routes"`
}

func schema(logger *log.Logger, path string) []byte {
	raw, err := os.ReadFile(path)
	if err != nil {
		logger.Fatal(err)
	}
	s, err := x402.InlineSchema(raw)
	if err != nil {
		logger.Fatal(err)
	}
	return s
}

func main() {
	path := flag.String("config", "seller.json", "JSON configuration file")
	directivePath := flag.String("directive", os.Getenv("FAIRBIND_DIRECTIVE"), "scenario directive file (default $FAIRBIND_DIRECTIVE)")
	progress := flag.String("progress", "", "write the head block of every completed pass to this file")
	flag.Parse()
	logger := log.New(os.Stderr, "seller ", log.LstdFlags)
	dir, err := directive.Load(*directivePath, directive.RoleSeller)
	if err != nil {
		logger.Fatal(err)
	}
	var cfg config
	if err := x402.LoadConfig(*path, &cfg); err != nil {
		logger.Fatal(err)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	var signer ethkey.Signer
	switch {
	case cfg.Keystore != nil:
		signer = judgment.KeystoreSigner{CastPath: cfg.Keystore.CastPath, KeystorePath: cfg.Keystore.KeystorePath, PasswordFile: cfg.Keystore.PasswordFile}
	case cfg.SigningKeyFile != "":
		k, err := ethkey.LoadPrivateKeyFile(cfg.SigningKeyFile)
		if err != nil {
			logger.Fatal(err)
		}
		signer = k
	default:
		logger.Fatal("configure signingKeyFile or keystore")
	}
	var routes []seller.Route
	for _, rc := range cfg.Routes {
		body, err := os.ReadFile(rc.BodyFile)
		if err != nil {
			logger.Fatal(err)
		}
		if _, err = rc.Preimage.Commitment(); err != nil {
			logger.Fatalf("route %s: %v", rc.Path, err)
		}
		resp := seller.Response{Status: 200, ContentType: rc.MimeType, Body: body, Preimage: rc.Preimage}
		route := seller.Route{Path: rc.Path, Description: rc.Description, MimeType: rc.MimeType,
			Handler: seller.HandlerFunc(func(context.Context, x402.CanonicalRequest) (seller.Response, error) { return resp, nil })}
		if rc.CheatBodyFile != "" {
			bad, err := os.ReadFile(rc.CheatBodyFile)
			if err != nil {
				logger.Fatal(err)
			}
			cheat := seller.Response{Status: 200, ContentType: rc.MimeType, Body: bad, Preimage: rc.Preimage}
			route.Cheat = seller.HandlerFunc(func(context.Context, x402.CanonicalRequest) (seller.Response, error) { return cheat, nil })
		}
		routes = append(routes, route)
	}
	claims, err := os.ReadFile(cfg.ClaimsFile)
	if err != nil {
		logger.Fatal(err)
	}
	client, err := chain.NewRPC(ctx, chain.RPCConfig{URL: cfg.RPCURL, ChainID: cfg.ChainID, Contract: chain.Address(cfg.Contract), From: chain.Address(cfg.Owner)})
	if err != nil {
		logger.Fatal(err)
	}
	store, err := fsstore.Open(cfg.DataDir)
	if err != nil {
		logger.Fatal(err)
	}
	defer store.Close()
	s, err := seller.New(ctx, seller.Options{SellerID: cfg.SellerID, Network: cfg.Network, PublicURL: cfg.PublicURL,
		ServiceName: cfg.ServiceName, ServiceClass: cfg.ServiceClass, ProfileHash: protocol.Bytes32(cfg.ProfileHash),
		CanonicalHeaders: cfg.CanonicalHeaders, Price: cfg.Price, MaxTimeoutSeconds: cfg.MaxTimeoutSeconds,
		TokenName: cfg.TokenName, TokenVersion: cfg.TokenVersion, ExtensionSchema: schema(logger, cfg.ExtensionSchema),
		SettlementSchema: schema(logger, cfg.SettlementSchema), Claims: claims, Routes: routes,
		Facilitator: x402.HTTPFacilitator{URL: cfg.FacilitatorURL}, Signer: signer, Log: logger,
		WorstPath: dir != nil && dir.WorstPath != nil, ProgressFile: *progress, FiniteAttack: finiteAttack(dir)}, client, store)
	if err != nil {
		logger.Fatal(err)
	}
	tick := time.Duration(cfg.TickSeconds) * time.Second
	if tick <= 0 {
		tick = 2 * time.Second
	}
	go s.Run(ctx, tick)
	srv := &http.Server{Addr: cfg.Listen, Handler: s.Handler(), ReadHeaderTimeout: 10 * time.Second}
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

func finiteAttack(dir *directive.File) *directive.FiniteAttack {
	if dir == nil {
		return nil
	}
	return dir.FiniteAttack
}
