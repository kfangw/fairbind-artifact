package seller

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"example.org/fairbind/adapters/httpcanon"
	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
)

// Handler returns the HTTP handler for protected routes and the FairBind
// endpoints under /fairbind/.
func (s *Seller) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /fairbind/serve/{nonce}", s.handleServe)
	mux.HandleFunc("GET /fairbind/claims", s.handleClaims)
	mux.HandleFunc("GET /fairbind/proofs/{nonce}", s.handleProof)
	mux.HandleFunc("GET /fairbind/epochs/{epoch}/entries", s.handleEntries)
	mux.HandleFunc("GET /fairbind/epochs/{epoch}/manifest", s.handleManifest)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/fairbind/") {
			mux.ServeHTTP(w, r)
			return
		}
		s.handlePaid(w, r)
	})
}

type apiError struct {
	Error string `json:"error"`
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	if w.Header().Get("Cache-Control") == "" {
		w.Header().Set("Cache-Control", "no-store")
	}
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

func fail(w http.ResponseWriter, status int, id string) { writeJSON(w, status, apiError{id}) }

func (s *Seller) canonicalize(r *http.Request, body []byte) (x402.CanonicalRequest, error) {
	target := r.RequestURI
	if i := strings.Index(target, "://"); i >= 0 { // absolute-form target
		rest := target[i+3:]
		if j := strings.IndexByte(rest, '/'); j >= 0 {
			target = rest[j:]
		} else {
			target = "/"
		}
	}
	path, query, _ := strings.Cut(target, "?")
	var headers []httpcanon.Header
	for name, values := range r.Header {
		for _, v := range values {
			headers = append(headers, httpcanon.Header{Name: name, Value: v})
		}
	}
	joinable := map[string]bool{}
	for _, n := range s.opt.CanonicalHeaders {
		joinable[n] = true
	}
	c, err := httpcanon.Normalize(httpcanon.Request{Method: r.Method, Path: path, Query: query, Headers: headers, Body: body},
		s.opt.CanonicalHeaders, joinable, int(s.profile.MaxRequestBytes))
	if err != nil {
		return x402.CanonicalRequest{}, err
	}
	return x402.CanonicalRequest{Method: []byte(c.Method), Path: []byte(c.Path), Query: []byte(c.Query),
		HeaderBlock: []byte(c.Headers), Body: c.Body}, nil
}

func (s *Seller) accept() x402.Accept {
	return x402.Accept{Scheme: x402.Scheme, Network: s.opt.Network, Amount: strconv.FormatUint(s.opt.Price, 10),
		Asset: x402.Addr(s.profile.Token), PayTo: x402.Addr(s.chain.Contract()), MaxTimeoutSeconds: s.opt.MaxTimeoutSeconds,
		Extra: x402.AcceptExtra{AssetTransferMethod: x402.AssetTransferMethod, PaymentFlow: x402.PaymentFlow,
			Name: s.opt.TokenName, Version: s.opt.TokenVersion}}
}

func (s *Seller) resource(route Route, c x402.CanonicalRequest) x402.Resource {
	url := s.opt.PublicURL + string(c.Path)
	if len(c.Query) > 0 {
		url += "?" + string(c.Query)
	}
	return x402.Resource{URL: url, Description: route.Description, MimeType: route.MimeType, ServiceName: s.opt.ServiceName}
}

func offerID(key x402.H16, payer x402.Addr) string { return key.String() + "-" + payer.String() }

func (s *Seller) handlePaid(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	body, err := io.ReadAll(io.LimitReader(r.Body, int64(s.profile.MaxRequestBytes)+1))
	if err != nil {
		fail(w, http.StatusBadRequest, x402.ErrCanonicalizationFailed)
		return
	}
	c, err := s.canonicalize(r, body)
	if err != nil {
		fail(w, http.StatusBadRequest, x402.ErrCanonicalizationFailed)
		return
	}
	route, ok := s.routes[string(c.Path)]
	if !ok {
		fail(w, http.StatusNotFound, "not_found")
		return
	}
	key, err := x402.DecodeKey(r.Header.Get(x402.HeaderKey))
	if err != nil {
		fail(w, http.StatusBadRequest, x402.ErrExtensionInvalid)
		return
	}
	payer, err := x402.ParseAddr(r.Header.Get(x402.HeaderPayer))
	if err != nil {
		fail(w, http.StatusBadRequest, x402.ErrExtensionInvalid)
		return
	}
	requestHash := x402.H32(c.Hash(s.profile.CanonID))
	if sig := r.Header.Get(x402.HeaderPaymentSignature); sig != "" {
		s.handlePayment(ctx, w, route, c, key, payer, requestHash, sig)
		return
	}
	s.handleOffer(ctx, w, route, c, key, payer, requestHash)
}

func (s *Seller) handleOffer(ctx context.Context, w http.ResponseWriter, route Route, c x402.CanonicalRequest, key x402.H16, payer x402.Addr, requestHash x402.H32) {
	if s.refusesOffers() {
		s.refuse(w)
		return
	}
	q, err := s.chain.QuoteSeller(ctx, s.opt.SellerID)
	if err != nil {
		fail(w, http.StatusInternalServerError, "quote_unavailable")
		return
	}
	info := x402.OfferInfo{Version: 1, Contract: x402.Addr(s.chain.Contract()), SellerID: s.view.SellerID, ProfileID: s.view.ProfileID,
		BondID: s.view.BondID, ServiceClass: s.opt.ServiceClass, PredicateID: x402.H32(s.profile.PredicateID), CanonID: x402.H32(s.profile.CanonID),
		ClaimsHash: x402.H32(s.view.ClaimsHash), ProfileHash: x402.H32(s.opt.ProfileHash),
		CanonicalHeaders: append([]string{}, s.opt.CanonicalHeaders...), QuotedAtBlock: q.QuotedAtBlock, Remaining: uint64(q.Remaining),
		ResponseBlocks: uint64(s.profile.Deadlines.ResponseBlocks), ClaimBlocks: uint64(s.profile.Deadlines.ClaimBlocks),
		MaxRequestBytes: uint64(s.profile.MaxRequestBytes), MaxResponseBytes: uint64(s.profile.MaxResponseBytes),
		RetentionBlocks: uint64(s.profile.RetentionBlocks)}
	id := offerID(key, payer)
	var o Offer
	if _, err = s.store.Get("offers", id, &o); err != nil {
		fail(w, http.StatusInternalServerError, "store_failure")
		return
	}
	now := s.opt.Now()
	if o.Version == 0 || o.RequestHash != requestHash || o.ExpiresAt < now {
		o = Offer{Version: 1, Key: key, Payer: payer, RequestHash: requestHash}
	}
	o.Issued = append(o.Issued, info)
	if len(o.Issued) > 8 {
		o.Issued = o.Issued[len(o.Issued)-8:]
	}
	o.ExpiresAt = now + s.opt.MaxTimeoutSeconds + uint64(s.profile.Deadlines.ResponseBlocks)*12
	if err = s.store.Put("offers", id, o); err != nil {
		fail(w, http.StatusInternalServerError, "store_failure")
		return
	}
	pr := x402.PaymentRequired{X402Version: x402.Version, Error: "Payment required", Resource: s.resource(route, c),
		Accepts:    []x402.Accept{s.accept()},
		Extensions: map[string]x402.OfferExtension{x402.ExtensionKey: {Info: info, Schema: s.opt.ExtensionSchema}}}
	h, err := x402.EncodeHeader(pr)
	if err != nil {
		fail(w, http.StatusInternalServerError, "encoding_failure")
		return
	}
	w.Header().Set(x402.HeaderPaymentRequired, h)
	writeJSON(w, http.StatusPaymentRequired, pr)
}

func sameInfo(a, b x402.OfferInfo) bool {
	x, _ := json.Marshal(a)
	y, _ := json.Marshal(b)
	return string(x) == string(y)
}

func (s *Seller) handlePayment(ctx context.Context, w http.ResponseWriter, route Route, c x402.CanonicalRequest, key x402.H16, payer x402.Addr, requestHash x402.H32, header string) {
	var pp x402.PaymentPayload
	if err := x402.DecodeHeader(header, &pp); err != nil || pp.X402Version != x402.Version {
		fail(w, http.StatusBadRequest, x402.ErrExtensionInvalid)
		return
	}
	a, _ := json.Marshal(pp.Accepted)
	b, _ := json.Marshal(s.accept())
	if !x402.SameJSON(a, b) {
		fail(w, http.StatusBadRequest, x402.ErrExtensionInvalid)
		return
	}
	ext, ok := pp.Extensions[x402.ExtensionKey]
	if !ok {
		fail(w, http.StatusBadRequest, x402.ErrExtensionMissing)
		return
	}
	info := ext.Info
	if info.IdempotencyKey == nil || info.RequestHash == nil {
		fail(w, http.StatusBadRequest, x402.ErrExtensionInvalid)
		return
	}
	auth := pp.Payload.Authorization
	if *info.IdempotencyKey != key || auth.From != payer {
		fail(w, http.StatusBadRequest, x402.ErrExtensionInvalid)
		return
	}
	var o Offer
	if found, err := s.store.Get("offers", offerID(key, payer), &o); err != nil {
		fail(w, http.StatusInternalServerError, "store_failure")
		return
	} else if !found {
		fail(w, http.StatusBadRequest, x402.ErrExtensionEchoMismatch)
		return
	}
	echoed := false
	for _, issued := range o.Issued {
		if sameInfo(issued, info.ServerAuthored()) {
			echoed = true
		}
	}
	if !echoed || !x402.SameJSON(ext.Schema, s.opt.ExtensionSchema) {
		fail(w, http.StatusBadRequest, x402.ErrExtensionEchoMismatch)
		return
	}
	if *info.RequestHash != requestHash || o.RequestHash != requestHash {
		fail(w, http.StatusBadRequest, x402.ErrRequestHashMismatch)
		return
	}
	cid, contract := s.chain.ChainID(), s.chain.Contract()
	nonce := protocol.DeriveNonce(cid, contract, s.view.SellerID, s.view.ProfileID, s.view.ClaimsHash,
		protocol.Address(payer), protocol.Bytes16(key), protocol.Bytes32(requestHash))
	if protocol.Bytes32(auth.Nonce) != nonce {
		fail(w, http.StatusBadRequest, x402.ErrNonceMismatch)
		return
	}
	if auth.To != x402.Addr(contract) || uint64(auth.Value) != s.opt.Price {
		fail(w, http.StatusBadRequest, x402.ErrExtensionInvalid)
		return
	}
	unlock := s.lock(nonce)
	defer unlock()
	rec, err := s.getRecord(nonce)
	if err != nil {
		fail(w, http.StatusInternalServerError, "store_failure")
		return
	}
	if rec == nil || rec.State == StateRejected {
		fresh := &Record{Version: 1, Nonce: x402.H32(nonce), KeyID: x402.H32(protocol.DeriveKeyID(cid, contract, s.view.SellerID, protocol.Address(payer), protocol.Bytes16(key))),
			Key: key, Buyer: payer, RequestHash: requestHash, Route: route.Path, Request: &c, Payload: &pp, State: StateSettling}
		// A rejected settlement retried keeps the sale's place in the attack.
		if rec != nil {
			fresh.Cheat = rec.Cheat
		} else if refuse, err := s.admitSale(fresh); err != nil {
			fail(w, http.StatusInternalServerError, "store_failure")
			return
		} else if refuse {
			s.refuse(w)
			return
		}
		rec = fresh
		if err = s.putRecord(rec); err != nil {
			fail(w, http.StatusInternalServerError, "store_failure")
			return
		}
	}
	if rec.State == StateSettling {
		if status, reason, tx := s.settle(ctx, rec, *rec.Payload); status != 0 {
			w.Header().Set("Cache-Control", "no-store")
			if tx != "" || status == http.StatusPaymentRequired {
				sr := x402.SettlementResponse{Success: false, ErrorReason: reason, Transaction: tx, Network: s.opt.Network, Payer: payer.String()}
				if h, err := x402.EncodeHeader(sr); err == nil {
					w.Header().Set(x402.HeaderPaymentResponse, h)
				}
			}
			fail(w, status, reason)
			return
		}
	}
	if rec.State == StateSettled {
		if err = s.deliver(ctx, rec); err != nil {
			s.opt.Log.Printf("deliver %s: %v", rec.Nonce, err)
			fail(w, http.StatusInternalServerError, "handler_failure")
			return
		}
	}
	if rec.State != StateDelivered || rec.Response == nil || rec.Receipt == nil {
		fail(w, http.StatusGone, x402.ErrReceiptMissing)
		return
	}
	s.writeDelivered(w, rec)
}

func (s *Seller) writeDelivered(w http.ResponseWriter, rec *Record) {
	pr, err := x402.EncodeHeader(rec.Settlement)
	if err != nil {
		fail(w, http.StatusInternalServerError, "encoding_failure")
		return
	}
	rh, err := x402.EncodeHeader(rec.Receipt)
	if err != nil {
		fail(w, http.StatusInternalServerError, "encoding_failure")
		return
	}
	h := w.Header()
	h.Set(x402.HeaderPaymentResponse, pr)
	h.Set(x402.HeaderReceipt, rh)
	h.Set("Cache-Control", "private")
	if rec.Response.ContentType != "" {
		h.Set("Content-Type", rec.Response.ContentType)
	}
	w.WriteHeader(rec.Response.Status)
	w.Write(rec.Response.Body)
}

// settle obtains a confirmed ledger record for rec. It returns a zero status
// on success, updating rec to StateSettled.
func (s *Seller) settle(ctx context.Context, rec *Record, pp x402.PaymentPayload) (int, string, string) {
	resp, err := s.opt.Facilitator.Settle(ctx, x402.SettleRequest{X402Version: x402.Version, PaymentPayload: pp, PaymentRequirements: pp.Accepted})
	tx := resp.Transaction
	if err == nil && !resp.Success && resp.ErrorReason != x402.ErrSettlementPending {
		// A definite rejection. The ledger remains the authority: a matching
		// record would still be accepted below on a later retry.
		switch resp.ErrorReason {
		case x402.ErrKeyConflict, x402.ErrNonceUsed:
		default:
			rec.State = StateRejected
			rec.Reason = resp.ErrorReason
			s.putRecord(rec)
		}
		return http.StatusPaymentRequired, resp.ErrorReason, tx
	}
	// Success, pending or unknown: confirm through the ledger.
	for i := 0; i < s.opt.PendingPolls; i++ {
		ok, conflict, verr := s.confirm(ctx, rec)
		if verr == nil && conflict {
			return http.StatusPaymentRequired, x402.ErrKeyConflict, tx
		}
		if verr == nil && ok {
			if err == nil && resp.Success {
				rec.Settlement = &resp
			} else {
				rec.Settlement = s.settlementFromLedger(ctx, rec, tx)
			}
			if perr := s.putRecord(rec); perr != nil {
				return http.StatusInternalServerError, "store_failure", tx
			}
			return 0, "", tx
		}
		if i+1 < s.opt.PendingPolls {
			select {
			case <-ctx.Done():
				return http.StatusInternalServerError, "cancelled", tx
			case <-time.After(s.opt.PendingInterval):
			}
		}
	}
	if err != nil && tx == "" {
		s.opt.Log.Printf("settle %s: %v", rec.Nonce, err)
		return http.StatusInternalServerError, "facilitator_unavailable", ""
	}
	return http.StatusPaymentRequired, x402.ErrSettlementPending, tx
}

// confirm reconciles rec against the ledger and moves it to StateSettled.
func (s *Seller) confirm(ctx context.Context, rec *Record) (ok, conflict bool, err error) {
	expected := protocol.ExpectedPurchase{Nonce: protocol.Bytes32(rec.Nonce), KeyID: protocol.Bytes32(rec.KeyID),
		SellerID: s.view.SellerID, ProfileID: s.view.ProfileID, Buyer: protocol.Address(rec.Buyer), Value: s.opt.Price,
		RequestHash: protocol.Bytes32(rec.RequestHash), ClaimsHash: s.view.ClaimsHash}
	p, err := s.chain.GetPurchase(ctx, expected.Nonce)
	if err != nil {
		return false, false, err
	}
	byKey, err := s.chain.PurchaseByKey(ctx, expected.KeyID)
	if err != nil {
		return false, false, err
	}
	var recorded *protocol.RecordedPurchase
	if p.Exists() {
		e := p.Expected()
		recorded = &e
	}
	switch protocol.Reconcile(expected, recorded, byKey) {
	case protocol.ReconcileConfirmed:
		rec.State = StateSettled
		rec.Epoch = p.Epoch
		rec.Settled = p.SettledBlock
		rec.RetainUntil = p.RetainUntil
		return true, false, nil
	case protocol.ReconcileConflict:
		return false, true, nil
	}
	return false, false, nil
}

func (s *Seller) settlementFromLedger(ctx context.Context, rec *Record, tx string) *x402.SettlementResponse {
	p, _ := s.chain.GetPurchase(ctx, protocol.Bytes32(rec.Nonce))
	if tx == "" {
		tx = x402.H32{}.String()
	}
	return &x402.SettlementResponse{Success: true, Transaction: tx, Network: s.opt.Network, Payer: rec.Buyer.String(),
		Amount: strconv.FormatUint(p.Value, 10),
		Extensions: map[string]x402.SettlementExtension{x402.ExtensionKey: {Info: x402.SettlementInfo{Version: 1,
			Purchase: rec.Nonce, KeyID: rec.KeyID, SellerID: p.SellerID, ProfileID: p.ProfileID, Epoch: p.Epoch,
			FinancialState: chain.FinancialStateName(p.FinancialState)}, Schema: s.opt.SettlementSchema}}}
}
