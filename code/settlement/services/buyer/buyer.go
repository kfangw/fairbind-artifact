// Package buyer implements a FairBind buyer: it negotiates x402 version 2
// payments, signs EIP-3009 authorizations with the FairBind-derived nonce,
// keeps receipts, checks inclusion proofs after the anchor, and pursues
// non-delivery disputes and refunds.
package buyer

import (
	"bytes"
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"example.org/fairbind/adapters/httpcanon"
	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/ethkey"
	"example.org/fairbind/services/internal/x402/fsstore"
)

// Options configure a Buyer.
type Options struct {
	Network  string
	Signer   ethkey.Signer
	Address  protocol.Address // the payer; must match Signer
	MaxPrice uint64           // offers above this amount are refused
	HTTP     *http.Client
	Now      func() uint64
	// ValidAfterSkew is subtracted from Now for validAfter (default 30s).
	ValidAfterSkew uint64
	Log            *log.Logger
	// WorstPath enables the worst-path directive (experiments/controller/
	// worstpath.py, buyer block): the buyer opens no NON_DELIVERY dispute, so a
	// sampled sale is never turned into a dispute case, and claims a purchase
	// from a frozen bond only after the purchase's own case is final.
	WorstPath bool
}

// Purchase states.
const (
	StateNew       = "new"       // key chosen, nothing sent that could settle
	StateOffered   = "offered"   // payload signed and saved; payment may be settled
	StateReceived  = "received"  // response and valid receipt stored
	StateProven    = "proven"    // receipt inclusion verified against the anchor
	StateDisputed  = "disputed"  // NON_DELIVERY case open
	StateDelivered = "delivered" // case ended DELIVERED without a retrievable body
	StateRefunded  = "refunded"  // refund paid by the contract
	StateAbandoned = "abandoned" // authorization expired without a ledger record
	StateFailed    = "failed"    // offer refused before signing
)

// Request describes the protected request.
type Request struct {
	Method  string      `json:"method"`
	URL     string      `json:"url"`
	Headers [][2]string `json:"headers"`
	Body    []byte      `json:"body"`
}

// StoredResponse is a received protected response.
type StoredResponse struct {
	Status      int    `json:"status"`
	ContentType string `json:"contentType"`
	Body        []byte `json:"body"`
	Source      string `json:"source"` // "http", "serve" or "publication"
}

// Record is the persisted state of one purchase (purchases/<key>.json).
type Record struct {
	Version      int                      `json:"version"`
	Key          x402.H16                 `json:"idempotencyKey"`
	Request      Request                  `json:"request"`
	State        string                   `json:"state"`
	Reason       string                   `json:"reason,omitempty"`
	Offer        *x402.PaymentRequired    `json:"offer,omitempty"`
	Payload      *x402.PaymentPayload     `json:"payload,omitempty"`
	Nonce        *x402.H32                `json:"nonce,omitempty"`
	RequestHash  *x402.H32                `json:"requestHash,omitempty"`
	SellerID     uint32                   `json:"sellerId,omitempty"`
	Epoch        uint32                   `json:"epoch"`
	ResponseDue  uint64                   `json:"responseDue,omitempty"`
	ClaimUntil   uint64                   `json:"claimUntil,omitempty"`
	Settlement   *x402.SettlementResponse `json:"settlement,omitempty"`
	Response     *StoredResponse          `json:"response,omitempty"`
	Receipt      *x402.Receipt            `json:"receipt,omitempty"`
	Proof        *x402.Proof              `json:"proof,omitempty"`
	AnchorRoot   *x402.H32                `json:"anchorRoot,omitempty"`
	Transactions []string                 `json:"transactions,omitempty"`
}

type Buyer struct {
	opt   Options
	chain chain.Client
	store *fsstore.Store
	locks sync.Map
}

// New checks that the signer controls the payer address and that the chain
// client sends from it.
func New(ctx context.Context, opt Options, c chain.Client, store *fsstore.Store) (*Buyer, error) {
	if opt.Now == nil {
		opt.Now = func() uint64 { return uint64(time.Now().Unix()) }
	}
	if opt.HTTP == nil {
		opt.HTTP = &http.Client{Timeout: 60 * time.Second, Transport: &http.Transport{DisableCompression: true}}
	}
	if opt.Log == nil {
		opt.Log = log.New(io.Discard, "", 0)
	}
	if opt.ValidAfterSkew == 0 {
		opt.ValidAfterSkew = 30
	}
	if opt.Signer == nil || opt.Network == "" || opt.MaxPrice == 0 {
		return nil, errors.New("signer, network and maxPrice are required")
	}
	if c.From() != opt.Address {
		return nil, errors.New("chain client does not send from the buyer address")
	}
	probe := protocol.Keccak256([]byte("fairbind/buyer/signer-check"))
	sig, err := opt.Signer.SignDigest(ctx, probe)
	if err != nil {
		return nil, err
	}
	if err = ethkey.Verify(opt.Address, probe, sig); err != nil {
		return nil, fmt.Errorf("signer does not control %s: %w", x402.Addr(opt.Address), err)
	}
	return &Buyer{opt: opt, chain: c, store: store}, nil
}

func (b *Buyer) lock(id string) func() {
	m, _ := b.locks.LoadOrStore(id, &sync.Mutex{})
	mu := m.(*sync.Mutex)
	mu.Lock()
	return mu.Unlock
}

func (b *Buyer) get(id string) (*Record, error) {
	var r Record
	ok, err := b.store.Get("purchases", id, &r)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, fmt.Errorf("unknown purchase %s", id)
	}
	return &r, nil
}

func (b *Buyer) put(r *Record) error { return b.store.Put("purchases", r.Key.String(), r) }

// Get returns a stored purchase by its idempotency key.
func (b *Buyer) Get(id string) (*Record, error) { return b.get(id) }

// List returns the stored purchase ids.
func (b *Buyer) List() ([]string, error) { return b.store.List("purchases") }

// Buy records a new purchase and runs it as far as it can go now. The
// record is saved before anything is sent, so a restart resumes it.
func (b *Buyer) Buy(ctx context.Context, req Request) (*Record, error) {
	var key x402.H16
	if _, err := rand.Read(key[:]); err != nil {
		return nil, err
	}
	if req.Method == "" {
		req.Method = http.MethodGet
	}
	r := &Record{Version: 1, Key: key, Request: req, State: StateNew}
	if err := b.put(r); err != nil {
		return nil, err
	}
	return b.Advance(ctx, key.String())
}

// Advance performs the next steps of one purchase and returns its record.
func (b *Buyer) Advance(ctx context.Context, id string) (*Record, error) {
	unlock := b.lock(id)
	defer unlock()
	r, err := b.get(id)
	if err != nil {
		return nil, err
	}
	err = b.step(ctx, r)
	return r, err
}

func (b *Buyer) step(ctx context.Context, r *Record) error {
	switch r.State {
	case StateNew:
		if err := b.negotiate(ctx, r); err != nil {
			return err
		}
		if r.State != StateOffered {
			return nil
		}
		fallthrough
	case StateOffered:
		return b.progressPaid(ctx, r)
	case StateReceived:
		return b.progressReceived(ctx, r)
	case StateProven:
		return b.claimIfFrozen(ctx, r)
	case StateDisputed:
		return b.progressDispute(ctx, r)
	}
	return nil
}

// Tick advances every open purchase.
func (b *Buyer) Tick(ctx context.Context) error {
	ids, err := b.List()
	if err != nil {
		return err
	}
	var errs []error
	for _, id := range ids {
		if _, err := b.Advance(ctx, id); err != nil {
			errs = append(errs, fmt.Errorf("%s: %w", id, err))
		}
	}
	return errors.Join(errs...)
}

// Run calls Tick every interval until ctx ends.
func (b *Buyer) Run(ctx context.Context, interval time.Duration) {
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		if err := b.Tick(ctx); err != nil {
			b.opt.Log.Printf("tick: %v", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
	}
}

func (b *Buyer) send(ctx context.Context, r *Record, payment string) (*http.Response, []byte, error) {
	req, err := http.NewRequestWithContext(ctx, r.Request.Method, r.Request.URL, bytes.NewReader(r.Request.Body))
	if err != nil {
		return nil, nil, err
	}
	for _, h := range r.Request.Headers {
		req.Header.Add(h[0], h[1])
	}
	req.Header.Set(x402.HeaderKey, x402.EncodeKey(r.Key))
	req.Header.Set(x402.HeaderPayer, x402.Addr(b.opt.Address).String())
	if payment != "" {
		req.Header.Set(x402.HeaderPaymentSignature, payment)
	}
	resp, err := b.opt.HTTP.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 64<<20))
	return resp, body, err
}

// requestHash canonicalizes the request exactly as it is sent.
func requestHash(req Request, names []string, maxBytes int) (protocol.Bytes32, error) {
	u, err := url.Parse(req.URL)
	if err != nil {
		return protocol.Bytes32{}, err
	}
	path, query, _ := strings.Cut(u.RequestURI(), "?")
	var headers []httpcanon.Header
	for _, h := range req.Headers {
		headers = append(headers, httpcanon.Header{Name: h[0], Value: h[1]})
	}
	joinable := map[string]bool{}
	for _, n := range names {
		joinable[n] = true
	}
	c, err := httpcanon.Normalize(httpcanon.Request{Method: req.Method, Path: path, Query: query, Headers: headers, Body: req.Body}, names, joinable, maxBytes)
	if err != nil {
		return protocol.Bytes32{}, err
	}
	return c.Hash(), nil
}

func (b *Buyer) refuse(r *Record, reason string) error {
	r.State, r.Reason = StateFailed, reason
	return b.put(r)
}

// negotiate sends the unpaid request, validates the offer, and saves a
// signed payload.
func (b *Buyer) negotiate(ctx context.Context, r *Record) error {
	resp, _, err := b.send(ctx, r, "")
	if err != nil {
		return err
	}
	if resp.StatusCode >= 500 {
		return fmt.Errorf("unpaid request answered %d", resp.StatusCode)
	}
	if resp.StatusCode != http.StatusPaymentRequired {
		return b.refuse(r, fmt.Sprintf("unpaid request answered %d", resp.StatusCode))
	}
	var pr x402.PaymentRequired
	if err = x402.DecodeHeader(resp.Header.Get(x402.HeaderPaymentRequired), &pr); err != nil {
		return b.refuse(r, "invalid PAYMENT-REQUIRED: "+err.Error())
	}
	accept, info, reason := b.validateOffer(ctx, pr)
	if reason != "" {
		return b.refuse(r, reason)
	}
	rh, err := requestHash(r.Request, info.CanonicalHeaders, int(info.MaxRequestBytes))
	if err != nil {
		return b.refuse(r, "request cannot be canonicalized: "+err.Error())
	}
	cid, contract := b.chain.ChainID(), b.chain.Contract()
	nonce := protocol.DeriveNonce(cid, contract, info.SellerID, info.ProfileID, protocol.Bytes32(info.ClaimsHash), b.opt.Address, protocol.Bytes16(r.Key), rh)
	amount, _ := strconv.ParseUint(accept.Amount, 10, 64)
	now := b.opt.Now()
	auth := x402.Authorization{From: x402.Addr(b.opt.Address), To: x402.Addr(contract), Value: x402.U64(amount),
		ValidAfter: x402.U64(now - b.opt.ValidAfterSkew), ValidBefore: x402.U64(now + accept.MaxTimeoutSeconds), Nonce: x402.H32(nonce)}
	sig, err := b.opt.Signer.SignDigest(ctx, x402.ReceiveDigest(accept.Extra.Name, accept.Extra.Version, cid, protocol.Address(accept.Asset), auth))
	if err != nil {
		return err
	}
	ext := pr.Extensions[x402.ExtensionKey]
	k, h := r.Key, x402.H32(rh)
	ext.Info.IdempotencyKey, ext.Info.RequestHash = &k, &h
	pp := x402.PaymentPayload{X402Version: x402.Version, Resource: pr.Resource, Accepted: accept,
		Payload: x402.ExactPayload{Signature: x402.Hex(sig), Authorization: auth}, Extensions: map[string]x402.OfferExtension{x402.ExtensionKey: ext}}
	n := x402.H32(nonce)
	r.Offer, r.Payload, r.Nonce, r.RequestHash, r.SellerID = &pr, &pp, &n, &h, info.SellerID
	r.State = StateOffered
	return b.put(r)
}

// validateOffer applies the buyer-side checks of the binding and compares
// the offer with the seller registration on chain.
func (b *Buyer) validateOffer(ctx context.Context, pr x402.PaymentRequired) (x402.Accept, x402.OfferInfo, string) {
	var zero x402.Accept
	ext, ok := pr.Extensions[x402.ExtensionKey]
	if pr.X402Version != x402.Version || !ok || len(pr.Accepts) == 0 {
		return zero, x402.OfferInfo{}, x402.ErrExtensionMissing
	}
	info := ext.Info
	contract := x402.Addr(b.chain.Contract())
	var accept *x402.Accept
	for i := range pr.Accepts {
		a := pr.Accepts[i]
		if a.Scheme == x402.Scheme && a.Network == b.opt.Network && a.Extra.AssetTransferMethod == x402.AssetTransferMethod && a.Extra.PaymentFlow == x402.PaymentFlow {
			accept = &a
			break
		}
	}
	if accept == nil {
		return zero, info, "no supported payment option"
	}
	if accept.PayTo != contract || info.Contract != contract || info.Version != 1 || info.IdempotencyKey != nil || info.RequestHash != nil {
		return zero, info, x402.ErrExtensionInvalid
	}
	amount, err := strconv.ParseUint(accept.Amount, 10, 64)
	if err != nil || amount == 0 || amount > b.opt.MaxPrice {
		return zero, info, "price above limit"
	}
	if info.CanonID != x402.H32(httpcanon.ID) {
		return zero, info, x402.ErrUnknownCanon
	}
	if !sort.StringsAreSorted(info.CanonicalHeaders) {
		return zero, info, x402.ErrExtensionInvalid
	}
	s, err := b.chain.GetSeller(ctx, info.SellerID)
	if err != nil {
		return zero, info, "seller lookup failed: " + err.Error()
	}
	if s.SellerID != info.SellerID || s.ProfileID != info.ProfileID {
		return zero, info, x402.ErrProfileMismatch
	}
	if s.ClaimsHash != protocol.Bytes32(info.ClaimsHash) {
		return zero, info, x402.ErrClaimsMismatch
	}
	if s.BondID != info.BondID {
		return zero, info, x402.ErrProfileMismatch
	}
	if s.Status != chain.SellerActive {
		return zero, info, x402.ErrSellerInactive
	}
	p, err := b.chain.GetProfile(ctx, s.ProfileID)
	if err != nil {
		return zero, info, "profile lookup failed: " + err.Error()
	}
	if accept.Asset != x402.Addr(p.Token) || amount > p.MaxPurchaseValue {
		return zero, info, x402.ErrValueTooLarge
	}
	if info.CanonID != x402.H32(p.CanonID) || info.PredicateID != x402.H32(p.PredicateID) ||
		info.ResponseBlocks != uint64(p.Deadlines.ResponseBlocks) || info.ClaimBlocks != uint64(p.Deadlines.ClaimBlocks) ||
		info.MaxRequestBytes != uint64(p.MaxRequestBytes) || info.MaxResponseBytes != uint64(p.MaxResponseBytes) ||
		info.RetentionBlocks != uint64(p.RetentionBlocks) {
		return zero, info, x402.ErrProfileMismatch
	}
	return *accept, info, ""
}

func verifySig(want protocol.Address, digest protocol.Bytes32, sig []byte) error {
	return ethkey.Verify(want, digest, sig)
}
