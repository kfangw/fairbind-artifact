// Package facilitator implements the x402 facilitator for the FairBind
// eip3009-fairbind-v1 transfer method. It checks a PaymentPayload, persists
// the exact settle arguments before submission, calls FairBind settle and
// reconciles retries through the purchase views. It never creates or
// alters an authorization, and never calls the token: the buyer signs an
// EIP-3009 ReceiveWithAuthorization, which only the FairBind contract, as
// payee, can execute (ADR 0016).
package facilitator

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/settlement"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/ethkey"
	"example.org/fairbind/services/internal/x402/fsstore"
)

// Options configure a Facilitator.
type Options struct {
	Network      string // CAIP-2, for example eip155:31337
	TokenName    string // EIP-712 domain name of the deployment token
	TokenVersion string // EIP-712 domain version of the deployment token
	// Token, when set, must equal the accepted asset.
	Token protocol.Address
	// SettlementSchema is the inline settlement schema returned in
	// SettlementResponse.extensions.fairbind.schema.
	SettlementSchema json.RawMessage
	// Now returns the unix time used for authorization validity checks.
	Now func() uint64
	Log *log.Logger
}

// Attempt status values in attempts/<nonce>.json.
const (
	StatusSubmitting = "submitting" // outcome unknown; reconcile before anything else
	StatusConfirmed  = "confirmed"  // the purchase is recorded and matches
	StatusRejected   = "rejected"   // the settle transaction reverted
	StatusConflict   = "conflict"   // the key or nonce names another purchase
)

// Attempt is the facilitator's own record next to the settlement journal.
type Attempt struct {
	Version      int      `json:"version"`
	Nonce        x402.H32 `json:"nonce"`
	Status       string   `json:"status"`
	Transactions []string `json:"transactions"`
	Revert       string   `json:"revert,omitempty"`
	UpdatedAt    int64    `json:"updatedAt"`
}

type Facilitator struct {
	opt   Options
	chain chain.Client
	store *fsstore.Store
	mu    sync.Mutex // serializes settlement per process; the journal also locks per record
}

// New returns a facilitator that stores state in store and submits through c.
func New(opt Options, c chain.Client, store *fsstore.Store) (*Facilitator, error) {
	if opt.Network == "" || opt.TokenName == "" || opt.TokenVersion == "" || len(opt.SettlementSchema) == 0 {
		return nil, errors.New("network, token domain and settlement schema are required")
	}
	if opt.Now == nil {
		opt.Now = func() uint64 { return uint64(time.Now().Unix()) }
	}
	if opt.Log == nil {
		opt.Log = log.New(io.Discard, "", 0)
	}
	return &Facilitator{opt: opt, chain: c, store: store}, nil
}

// Failure is a settlement result that is not a success.
type Failure struct {
	Status int    // HTTP status for the facilitator response
	Reason string // x402 errorReason
	Tx     string
	Detail string
}

func (f *Failure) Error() string { return f.Reason + ": " + f.Detail }

func fail(status int, reason, detail string) *Failure {
	return &Failure{Status: status, Reason: reason, Detail: detail}
}

// checked holds the values derived from a validated request.
type checked struct {
	settlement chain.Settlement
	expected   protocol.ExpectedPurchase
	payer      x402.Addr
	amount     uint64
}

// Check performs the stateless checks of the binding. It does not read chain
// state; the contract repeats every state-sensitive check.
func (f *Facilitator) Check(req x402.SettleRequest) (checked, *Failure) {
	var c checked
	bad := func(reason, detail string) (checked, *Failure) { return c, fail(http.StatusBadRequest, reason, detail) }
	pp := req.PaymentPayload
	if req.X402Version != x402.Version || pp.X402Version != x402.Version {
		return bad("invalid_x402_version", "x402 version 2 is required")
	}
	a := pp.Accepted
	ra, _ := json.Marshal(a)
	rr, _ := json.Marshal(req.PaymentRequirements)
	if !x402.SameJSON(ra, rr) {
		return bad("invalid_payment_requirements", "accepted differs from paymentRequirements")
	}
	if a.Scheme != x402.Scheme || a.Network != f.opt.Network || a.Extra.AssetTransferMethod != x402.AssetTransferMethod || a.Extra.PaymentFlow != x402.PaymentFlow {
		return bad("unsupported_scheme", "unsupported scheme, network, transfer method or flow")
	}
	contract := x402.Addr(f.chain.Contract())
	if a.PayTo != contract {
		return bad("invalid_payment_requirements", "payTo is not the FairBind contract")
	}
	if f.opt.Token != (protocol.Address{}) && protocol.Address(a.Asset) != f.opt.Token {
		return bad("invalid_payment_requirements", "asset is not the deployment token")
	}
	if a.Extra.Name != f.opt.TokenName || a.Extra.Version != f.opt.TokenVersion {
		return bad("invalid_payment_requirements", "token domain differs from the deployment token")
	}
	ext, ok := pp.Extensions[x402.ExtensionKey]
	if !ok {
		return bad(x402.ErrExtensionMissing, "fairbind extension missing")
	}
	info := ext.Info
	if info.Version != 1 || info.Contract != contract || info.IdempotencyKey == nil || info.RequestHash == nil {
		return bad(x402.ErrExtensionInvalid, "fairbind extension incomplete")
	}
	amount, err := strconv.ParseUint(a.Amount, 10, 64)
	if err != nil || strconv.FormatUint(amount, 10) != a.Amount {
		return bad("invalid_payment_requirements", "amount is not a canonical decimal")
	}
	auth := pp.Payload.Authorization
	if auth.To != contract || uint64(auth.Value) != amount {
		return bad("invalid_payload", "authorization recipient or value mismatch")
	}
	buyer := protocol.Address(auth.From)
	key := protocol.Bytes16(*info.IdempotencyKey)
	cid := f.chain.ChainID()
	nonce := protocol.DeriveNonce(cid, protocol.Address(contract), info.SellerID, info.ProfileID, protocol.Bytes32(info.ClaimsHash), buyer, key, protocol.Bytes32(*info.RequestHash))
	if protocol.Bytes32(auth.Nonce) != nonce {
		return bad(x402.ErrNonceMismatch, "authorization nonce is not the FairBind-derived nonce")
	}
	now := f.opt.Now()
	if now <= uint64(auth.ValidAfter) || now >= uint64(auth.ValidBefore) {
		return bad("invalid_payload", "authorization outside its validity window")
	}
	sig, err := x402.ParseHex(pp.Payload.Signature)
	if err != nil {
		return bad("invalid_payload", "signature encoding")
	}
	digest := x402.ReceiveDigest(a.Extra.Name, a.Extra.Version, cid, protocol.Address(a.Asset), auth)
	if err = ethkey.Verify(buyer, digest, sig); err != nil {
		return bad("invalid_payload", "authorization signature: "+err.Error())
	}
	c.settlement = chain.Settlement{SellerID: info.SellerID, ProfileID: info.ProfileID, ClaimsHash: protocol.Bytes32(info.ClaimsHash),
		Key: key, RequestHash: protocol.Bytes32(*info.RequestHash), Authorization: auth, Signature: sig}
	c.expected = protocol.ExpectedPurchase{Nonce: nonce, KeyID: protocol.DeriveKeyID(cid, protocol.Address(contract), info.SellerID, buyer, key),
		SellerID: info.SellerID, ProfileID: info.ProfileID, Buyer: buyer, Value: amount,
		RequestHash: protocol.Bytes32(*info.RequestHash), ClaimsHash: protocol.Bytes32(info.ClaimsHash)}
	c.payer = auth.From
	c.amount = amount
	return c, nil
}

func (f *Facilitator) journalPath(nonce protocol.Bytes32) string {
	return filepath.Join(f.store.Dir(), "journal", x402.H32(nonce).String()+".json")
}

func (f *Facilitator) attempt(nonce protocol.Bytes32) (Attempt, error) {
	a := Attempt{Version: 1, Nonce: x402.H32(nonce), Transactions: []string{}}
	_, err := f.store.Get("attempts", x402.H32(nonce).String(), &a)
	return a, err
}

func (f *Facilitator) putAttempt(a Attempt) error {
	a.UpdatedAt = time.Now().Unix()
	return f.store.Put("attempts", a.Nonce.String(), a)
}

// ledger adapts the chain to runtime/settlement.Ledger.
type ledger struct {
	ctx context.Context
	f   *Facilitator
	a   *Attempt
}

func (l ledger) Lookup(e protocol.ExpectedPurchase) (*protocol.RecordedPurchase, protocol.Bytes32, error) {
	p, err := l.f.chain.GetPurchase(l.ctx, e.Nonce)
	if err != nil {
		return nil, protocol.Bytes32{}, err
	}
	byKey, err := l.f.chain.PurchaseByKey(l.ctx, e.KeyID)
	if err != nil {
		return nil, protocol.Bytes32{}, err
	}
	if !p.Exists() {
		return nil, byKey, nil
	}
	rec := p.Expected()
	return &rec, byKey, nil
}

func (l ledger) Submit(_ protocol.ExpectedPurchase, raw []byte) error {
	var s chain.Settlement
	if err := json.Unmarshal(raw, &s); err != nil {
		return err
	}
	// Record intent before sending so a restart knows a transaction may exist.
	l.a.Status = StatusSubmitting
	l.a.Revert = ""
	if err := l.f.putAttempt(*l.a); err != nil {
		return err
	}
	tx, err := l.f.chain.Settle(l.ctx, s)
	if tx != (protocol.Bytes32{}) {
		l.a.Transactions = append(l.a.Transactions, x402.H32(tx).String())
	}
	if chain.IsRevert(err, "KeyAlreadyUsed") || chain.IsRevert(err, "NonceAlreadyUsed") {
		// A used identifier: reconciliation decides between success and conflict.
		err = nil
	} else if chain.IsRevert(err, "") {
		var r *chain.RevertError
		errors.As(err, &r)
		l.a.Status = StatusRejected
		l.a.Revert = r.Name
	}
	if perr := l.f.putAttempt(*l.a); perr != nil && err == nil {
		err = perr
	}
	return err
}

var revertReasons = map[string]string{
	"SellerInactive": x402.ErrSellerInactive, "SellerIsSuspended": x402.ErrSellerInactive, "BondNotActive": x402.ErrSellerInactive,
	"InactiveProfile": x402.ErrSellerInactive, "Paused": x402.ErrSellerInactive,
	"RateLimitExceeded": x402.ErrRateLimited, "ValueTooLarge": x402.ErrValueTooLarge,
	"ProfileMismatch": x402.ErrProfileMismatch, "ClaimsMismatch": x402.ErrClaimsMismatch,
	"NonceMismatch": x402.ErrNonceMismatch, "KeyAlreadyUsed": x402.ErrKeyUsed, "NonceAlreadyUsed": x402.ErrNonceUsed,
}

// Settle submits or reconciles one purchase. The same request may be sent
// any number of times; it produces at most one purchase.
func (f *Facilitator) Settle(ctx context.Context, req x402.SettleRequest) (x402.SettlementResponse, *Failure) {
	c, bad := f.Check(req)
	if bad != nil {
		return x402.SettlementResponse{}, bad
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	nonce := c.expected.Nonce
	raw, _ := json.Marshal(c.settlement)
	path := f.journalPath(nonce)
	a, err := f.attempt(nonce)
	if err != nil {
		return x402.SettlementResponse{}, fail(http.StatusInternalServerError, "unexpected_settle_error", err.Error())
	}
	err = settlement.Prepare(path, c.expected, raw)
	if errors.Is(err, settlement.ErrConflict) && a.Status == StatusRejected {
		// The earlier authorization reverted finally. Only then may a new
		// authorization for the same purchase replace it, and only while the
		// ledger has no record for the key or nonce.
		l := ledger{ctx, f, &a}
		rec, byKey, lerr := l.Lookup(c.expected)
		if lerr == nil && rec == nil && byKey == (protocol.Bytes32{}) {
			if err = os.Remove(path); err == nil {
				err = settlement.Prepare(path, c.expected, raw)
			}
		}
	}
	if errors.Is(err, settlement.ErrConflict) {
		return x402.SettlementResponse{}, fail(http.StatusOK, x402.ErrKeyConflict, "a different authorization is already recorded for this purchase")
	}
	if err != nil {
		return x402.SettlementResponse{}, fail(http.StatusInternalServerError, "unexpected_settle_error", err.Error())
	}
	return f.resume(ctx, c, &a)
}

func (f *Facilitator) resume(ctx context.Context, c checked, a *Attempt) (x402.SettlementResponse, *Failure) {
	nonce := c.expected.Nonce
	err := settlement.Resume(f.journalPath(nonce), ledger{ctx, f, a})
	lastTx := ""
	if n := len(a.Transactions); n > 0 {
		lastTx = a.Transactions[n-1]
	}
	switch {
	case err == nil:
		a.Status = StatusConfirmed
		a.Revert = ""
		if perr := f.putAttempt(*a); perr != nil {
			f.opt.Log.Printf("attempt record for %s: %v", x402.H32(nonce), perr)
		}
		return f.success(ctx, c, lastTx)
	case errors.Is(err, settlement.ErrConflict):
		a.Status = StatusConflict
		f.putAttempt(*a)
		reason := x402.ErrKeyConflict
		if byKey, _ := f.chain.PurchaseByKey(ctx, c.expected.KeyID); byKey == (protocol.Bytes32{}) {
			reason = x402.ErrNonceUsed
		}
		return x402.SettlementResponse{}, &Failure{Status: http.StatusOK, Reason: reason, Tx: lastTx, Detail: err.Error()}
	case chain.IsRevert(err, ""):
		var r *chain.RevertError
		errors.As(err, &r)
		reason, ok := revertReasons[r.Name]
		if !ok {
			reason = "unexpected_settle_error"
		}
		f.opt.Log.Printf("settle %s reverted: %s tx=%s", x402.H32(nonce), r.Name, lastTx)
		return x402.SettlementResponse{}, &Failure{Status: http.StatusOK, Reason: reason, Tx: lastTx, Detail: r.Name}
	default:
		f.opt.Log.Printf("settle %s uncertain: %v", x402.H32(nonce), err)
		if lastTx != "" {
			return x402.SettlementResponse{}, &Failure{Status: http.StatusOK, Reason: x402.ErrSettlementPending, Tx: lastTx, Detail: err.Error()}
		}
		return x402.SettlementResponse{}, fail(http.StatusInternalServerError, "unexpected_settle_error", err.Error())
	}
}

func (f *Facilitator) success(ctx context.Context, c checked, tx string) (x402.SettlementResponse, *Failure) {
	p, err := f.chain.GetPurchase(ctx, c.expected.Nonce)
	if err != nil || !p.Exists() {
		return x402.SettlementResponse{}, fail(http.StatusInternalServerError, "unexpected_settle_error", fmt.Sprint("purchase view: ", err))
	}
	if tx == "" {
		// Recorded by an earlier process or another submitter; the ledger
		// record, not this field, is authoritative.
		tx = x402.H32{}.String()
	}
	return x402.SettlementResponse{
		Success: true, Transaction: tx, Network: f.opt.Network, Payer: c.payer.String(),
		Amount: strconv.FormatUint(c.amount, 10),
		Extensions: map[string]x402.SettlementExtension{x402.ExtensionKey: {
			Info: x402.SettlementInfo{Version: 1, Purchase: x402.H32(p.Nonce), KeyID: x402.H32(p.KeyID), SellerID: p.SellerID,
				ProfileID: p.ProfileID, Epoch: p.Epoch, FinancialState: chain.FinancialStateName(p.FinancialState)},
			Schema: f.opt.SettlementSchema,
		}},
	}, nil
}

// Recover resumes every purchase whose last known outcome is uncertain. It
// runs at startup; each resume reconciles before any resubmission.
func (f *Facilitator) Recover(ctx context.Context) (int, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	ids, err := f.store.List("attempts")
	if err != nil {
		return 0, err
	}
	n := 0
	for _, id := range ids {
		var a Attempt
		if _, err := f.store.Get("attempts", id, &a); err != nil {
			return n, err
		}
		if a.Status != StatusSubmitting {
			continue
		}
		err := settlement.Resume(f.journalPath(protocol.Bytes32(a.Nonce)), ledger{ctx, f, &a})
		switch {
		case err == nil:
			a.Status = StatusConfirmed
			f.putAttempt(a)
			n++
		case errors.Is(err, settlement.ErrConflict):
			a.Status = StatusConflict
			f.putAttempt(a)
		default:
			f.opt.Log.Printf("recover %s: %v", id, err)
		}
	}
	return n, nil
}

type errorBody struct {
	Success     bool   `json:"success"`
	ErrorReason string `json:"errorReason"`
	Transaction string `json:"transaction"`
	Network     string `json:"network"`
}

// Handler serves GET /supported, POST /verify and POST /settle.
func (f *Facilitator) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /supported", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, x402.Supported{
			Kinds: []x402.SupportedKind{{X402Version: x402.Version, Scheme: x402.Scheme, Network: f.opt.Network,
				Extra: map[string]any{"assetTransferMethod": x402.AssetTransferMethod, "paymentFlow": x402.PaymentFlow}}},
			Extensions: []string{x402.ExtensionKey},
		})
	})
	decode := func(w http.ResponseWriter, r *http.Request) (x402.SettleRequest, bool) {
		var req x402.SettleRequest
		raw, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		if err == nil {
			err = x402.DecodeStrict(raw, &req)
		}
		if err != nil {
			writeJSON(w, http.StatusBadRequest, errorBody{ErrorReason: "invalid_request", Network: f.opt.Network})
			return req, false
		}
		return req, true
	}
	mux.HandleFunc("POST /verify", func(w http.ResponseWriter, r *http.Request) {
		req, ok := decode(w, r)
		if !ok {
			return
		}
		c, bad := f.Check(req)
		if bad != nil {
			writeJSON(w, http.StatusOK, map[string]any{"isValid": false, "invalidReason": bad.Reason})
			return
		}
		writeJSON(w, http.StatusOK, map[string]any{"isValid": true, "payer": c.payer.String()})
	})
	mux.HandleFunc("POST /settle", func(w http.ResponseWriter, r *http.Request) {
		req, ok := decode(w, r)
		if !ok {
			return
		}
		resp, bad := f.Settle(r.Context(), req)
		if bad != nil {
			writeJSON(w, bad.Status, errorBody{ErrorReason: bad.Reason, Transaction: bad.Tx, Network: f.opt.Network})
			return
		}
		writeJSON(w, http.StatusOK, resp)
	})
	return mux
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}
