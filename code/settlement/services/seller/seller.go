// Package seller implements a FairBind resource server: x402 version 2
// payment negotiation, settlement through a facilitator, signed receipts,
// retention, epoch anchors, and the redelivery and publication paths.
package seller

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"sort"
	"sync"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/directive"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/ethkey"
	"example.org/fairbind/services/internal/x402/fsstore"
)

// Response is what a protected handler returns. Body is the entity body
// before any content coding is removed. Preimage is the service-class
// predicate-commitment preimage the receipt commits to.
type Response struct {
	Status      int           `json:"status"`
	ContentType string        `json:"contentType"`
	Body        []byte        `json:"body"`
	Preimage    x402.Preimage `json:"preimage"`
}

// Handler produces the protected resource for a normalized request.
type Handler interface {
	Serve(ctx context.Context, req x402.CanonicalRequest) (Response, error)
}

// HandlerFunc adapts a function to Handler.
type HandlerFunc func(ctx context.Context, req x402.CanonicalRequest) (Response, error)

func (f HandlerFunc) Serve(ctx context.Context, req x402.CanonicalRequest) (Response, error) {
	return f(ctx, req)
}

// Route is one protected resource.
type Route struct {
	Path        string // normalized path, for example /v1/quote
	Description string
	MimeType    string
	Handler     Handler
	// Cheat, when set, produces the response of a sale the finite-attack
	// directive cheats on (finite.go); without it such a sale is served by
	// Handler and only its record is marked.
	Cheat Handler
}

// Options configure a Seller. Profile values come from the chain.
type Options struct {
	SellerID     uint32
	Network      string
	PublicURL    string // scheme and authority used for resource URLs and entriesUri
	ServiceName  string
	ServiceClass string // "data-api" or "open-weights-inference"
	ProfileHash  protocol.Bytes32
	// Claims is the exact registered claims document. Its keccak256 must equal
	// the seller registration's claimsHash. It is served verbatim at
	// GET /fairbind/claims so a verifier can authenticate it against the
	// on-chain hash before judging a redelivered bundle.
	Claims            []byte
	CanonicalHeaders  []string // sorted, lowercase, from the profile document
	Price             uint64
	MaxTimeoutSeconds uint64
	TokenName         string
	TokenVersion      string
	ExtensionSchema   json.RawMessage
	// SettlementSchema is used when the seller builds a SettlementResponse
	// from the ledger because the facilitator's response was lost.
	SettlementSchema json.RawMessage
	Routes           []Route
	Facilitator      x402.FacilitatorClient
	Signer           ethkey.Signer
	Now              func() uint64
	// PendingPolls and PendingInterval bound how long a paid request waits
	// for an uncertain settlement before answering fairbind_settlement_pending.
	PendingPolls    int
	PendingInterval time.Duration
	Log             *log.Logger
	// WorstPath enables the worst-path directive (directed.go). The chain
	// client must then implement chain.Reviewer.
	WorstPath bool
	// ProgressFile, when set, receives the block each completed Tick started
	// from (directive.WriteProgress).
	ProgressFile string
	// FiniteAttack enables the finite-attack directive (finite.go). With
	// After = request_exit the chain client must implement chain.Exiter.
	FiniteAttack *directive.FiniteAttack
}

// Purchase states.
const (
	StateSettling  = "settling"  // payload saved, settlement outcome unknown
	StateSettled   = "settled"   // ledger record confirmed, no receipt yet
	StateDelivered = "delivered" // receipt signed and retained
	StateRejected  = "rejected"  // settlement failed finally
	StatePruned    = "pruned"    // retention ended; bodies removed, receipt kept
)

// Record is the persisted state of one purchase (purchases/<nonce>.json).
type Record struct {
	Version     int                      `json:"version"`
	Nonce       x402.H32                 `json:"nonce"`
	KeyID       x402.H32                 `json:"keyId"`
	Key         x402.H16                 `json:"idempotencyKey"`
	Buyer       x402.Addr                `json:"buyer"`
	RequestHash x402.H32                 `json:"requestHash"`
	Route       string                   `json:"route"`
	Request     *x402.CanonicalRequest   `json:"request,omitempty"`
	Payload     *x402.PaymentPayload     `json:"payload,omitempty"`
	State       string                   `json:"state"`
	Reason      string                   `json:"reason,omitempty"`
	Settlement  *x402.SettlementResponse `json:"settlement,omitempty"`
	Epoch       uint32                   `json:"epoch"`
	Settled     uint64                   `json:"settledBlock"`
	RetainUntil uint64                   `json:"retainUntil"`
	Response    *Response                `json:"response,omitempty"`
	Receipt     *x402.Receipt            `json:"receipt,omitempty"`
	BundleHash  *x402.H32                `json:"bundleHash,omitempty"`
	ServedCase  uint64                   `json:"servedCaseOpenedBlock,omitempty"`
	Published   bool                     `json:"published,omitempty"`
	Chunks      []bool                   `json:"publishedChunks,omitempty"`
	Directed    *DirectedProgress        `json:"directed,omitempty"`
	// Cheat marks a sale the finite-attack directive cheats on.
	Cheat bool `json:"cheat,omitempty"`
}

// Offer is an issued PaymentRequired extension (offers/<key>-<payer>.json).
type Offer struct {
	Version     int              `json:"version"`
	Key         x402.H16         `json:"idempotencyKey"`
	Payer       x402.Addr        `json:"payer"`
	RequestHash x402.H32         `json:"requestHash"`
	Issued      []x402.OfferInfo `json:"issued"`
	ExpiresAt   uint64           `json:"expiresAt"`
}

// Epoch anchor states.
const (
	EpochEmpty      = "empty"
	EpochSubmitting = "submitting"
	EpochAnchored   = "anchored"
	EpochMissed     = "missed"
)

// EpochRecord is the persisted anchor state (epochs/<epoch>.json).
type EpochRecord struct {
	Version         int           `json:"version"`
	Epoch           uint32        `json:"epoch"`
	State           string        `json:"state"`
	Entries         []x402.Entry  `json:"entries"`
	Root            x402.H32      `json:"root"`
	Manifest        x402.Manifest `json:"manifest"`
	PublicationHash x402.H32      `json:"publicationHash"`
	Tx              string        `json:"tx,omitempty"`
}

type cursor struct {
	Version   int    `json:"version"`
	NextEpoch uint32 `json:"nextEpoch"`
}

type Seller struct {
	opt      Options
	chain    chain.Client
	store    *fsstore.Store
	profile  chain.Profile
	view     chain.Seller
	routes   map[string]Route
	locks    sync.Map // nonce -> *sync.Mutex
	epochMu  sync.Mutex
	attackMu sync.Mutex
}

// New reads the seller registration and profile from the chain and checks
// that the signer matches the registered signing key and that the client
// sends from the seller owner.
func New(ctx context.Context, opt Options, c chain.Client, store *fsstore.Store) (*Seller, error) {
	if opt.Now == nil {
		opt.Now = func() uint64 { return uint64(time.Now().Unix()) }
	}
	if opt.Log == nil {
		opt.Log = log.New(io.Discard, "", 0)
	}
	if opt.PendingPolls == 0 {
		opt.PendingPolls = 5
	}
	if opt.PendingInterval == 0 {
		opt.PendingInterval = 500 * time.Millisecond
	}
	if opt.MaxTimeoutSeconds == 0 {
		opt.MaxTimeoutSeconds = 60
	}
	if len(opt.ExtensionSchema) == 0 || opt.Facilitator == nil || opt.Signer == nil || opt.Network == "" {
		return nil, errors.New("extension schema, facilitator, signer and network are required")
	}
	if len(opt.Claims) == 0 {
		return nil, errors.New("claims document is required")
	}
	if !sort.StringsAreSorted(opt.CanonicalHeaders) {
		return nil, errors.New("canonical headers must be sorted")
	}
	view, err := c.GetSeller(ctx, opt.SellerID)
	if err != nil {
		return nil, err
	}
	if view.SellerID != opt.SellerID {
		return nil, fmt.Errorf("seller %d is not registered", opt.SellerID)
	}
	if view.Owner != c.From() {
		return nil, fmt.Errorf("chain client sends from %s, seller owner is %s", x402.Addr(c.From()), x402.Addr(view.Owner))
	}
	if got := protocol.Keccak256(opt.Claims); got != view.ClaimsHash {
		return nil, fmt.Errorf("claims document hashes to %s, registration claimsHash is %s", x402.H32(got), x402.H32(view.ClaimsHash))
	}
	probe := protocol.Keccak256([]byte("fairbind/seller/signer-check"))
	sig, err := opt.Signer.SignDigest(ctx, probe)
	if err != nil {
		return nil, err
	}
	if err = ethkey.Verify(view.SigningKey, probe, sig); err != nil {
		return nil, fmt.Errorf("signer does not match the registered signing key: %w", err)
	}
	profile, err := c.GetProfile(ctx, view.ProfileID)
	if err != nil {
		return nil, err
	}
	if profile.ProfileID != view.ProfileID || profile.EpochBlocks == 0 {
		return nil, fmt.Errorf("profile %d unavailable", view.ProfileID)
	}
	if _, ok := c.(chain.Reviewer); opt.WorstPath && !ok {
		return nil, errors.New("the worst-path directive needs a chain client with review calls")
	}
	if _, ok := c.(chain.Exiter); opt.FiniteAttack != nil && opt.FiniteAttack.After == directive.AfterRequestExit && !ok {
		return nil, errors.New("the request_exit attack needs a chain client with exit calls")
	}
	if opt.Price == 0 || opt.Price > profile.MaxPurchaseValue {
		return nil, fmt.Errorf("price %d outside (0, maxPurchaseValue %d]", opt.Price, profile.MaxPurchaseValue)
	}
	s := &Seller{opt: opt, chain: c, store: store, profile: profile, view: view, routes: map[string]Route{}}
	for _, r := range opt.Routes {
		s.routes[r.Path] = r
	}
	return s, nil
}

func (s *Seller) lock(nonce protocol.Bytes32) func() {
	m, _ := s.locks.LoadOrStore(nonce, &sync.Mutex{})
	mu := m.(*sync.Mutex)
	mu.Lock()
	return mu.Unlock
}

func (s *Seller) getRecord(nonce protocol.Bytes32) (*Record, error) {
	var r Record
	ok, err := s.store.Get("purchases", x402.H32(nonce).String(), &r)
	if err != nil || !ok {
		return nil, err
	}
	return &r, nil
}

func (s *Seller) putRecord(r *Record) error {
	return s.store.Put("purchases", r.Nonce.String(), r)
}

// Record returns the stored record of a purchase, for inspection.
func (s *Seller) Record(nonce protocol.Bytes32) (*Record, error) { return s.getRecord(nonce) }

// deliver runs the handler and signs the receipt once. The receipt is
// persisted before it is released, so a nonce never receives two receipts.
func (s *Seller) deliver(ctx context.Context, r *Record) error {
	if r.Receipt != nil {
		return nil
	}
	if r.State != StateSettled || r.Request == nil {
		return fmt.Errorf("purchase %s is %s", r.Nonce, r.State)
	}
	route, ok := s.routes[r.Route]
	if !ok {
		return fmt.Errorf("route %s is not served", r.Route)
	}
	if r.Response == nil {
		resp, err := handlerFor(route, r.Cheat).Serve(ctx, *r.Request)
		if err != nil {
			return err
		}
		if len(resp.Body) > int(s.profile.MaxResponseBytes) {
			return fmt.Errorf("response of %d bytes exceeds maxResponseBytes", len(resp.Body))
		}
		if resp.Status == 0 {
			resp.Status = 200
		}
		r.Response = &resp
	}
	commitment, err := r.Response.Preimage.Commitment()
	if err != nil {
		return err
	}
	rc := x402.Receipt{Version: 1, ChainID: x402.U64(s.chain.ChainID()), ContractAddress: x402.Addr(s.chain.Contract()),
		SellerID: s.view.SellerID, ProfileID: s.view.ProfileID, Nonce: r.Nonce, RequestHash: r.RequestHash,
		ResponseHash: x402.H32(protocol.ResponseHash(r.Response.Body)), ClaimsHash: x402.H32(s.view.ClaimsHash),
		PredicateCommitment: x402.H32(commitment), Epoch: r.Epoch, IssuedAt: x402.U64(s.opt.Now())}
	sig, err := s.opt.Signer.SignDigest(ctx, rc.Digest())
	if err != nil {
		return err
	}
	rc.Signature = x402.Hex(sig)
	r.Receipt = &rc
	r.State = StateDelivered
	return s.putRecord(r)
}
