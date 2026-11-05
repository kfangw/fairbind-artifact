package buyer

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"example.org/fairbind/adapters/httpcanon"
	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/fsstore"
	"example.org/fairbind/services/internal/x402/testworld"
)

var ctx = context.Background()

// stubSeller is a minimal resource server for buyer tests. It settles on
// the fake chain directly and keeps one receipt per nonce.
type stubSeller struct {
	t        *testing.T
	w        *testworld.World
	mu       sync.Mutex
	mode     string // "", "withhold", "badReceipt", "down", "badBundle"
	receipts map[protocol.Bytes32]x402.Receipt
	requests map[protocol.Bytes32]x402.CanonicalRequest
	keys     map[protocol.Bytes32]x402.H16
	paid     int
}

var body = []byte(`{"price":"1"}`)

func (s *stubSeller) setMode(m string) { s.mu.Lock(); s.mode = m; s.mu.Unlock() }

func (s *stubSeller) receipt(nonce protocol.Bytes32, rh x402.H32, respBody []byte) x402.Receipt {
	if rc, ok := s.receipts[nonce]; ok {
		return rc
	}
	p, _ := s.w.Fake.As(testworld.SellerOwner).GetPurchase(ctx, nonce)
	rt := x402.U64(1)
	ss, tp := x402.H32{1}, x402.H32{2}
	c, _ := x402.Preimage{Kind: "data-api", ReferenceTime: &rt, SourceSetHash: &ss, TolerancePolicyHash: &tp}.Commitment()
	rc := x402.Receipt{Version: 1, ChainID: testworld.ChainID, ContractAddress: x402.Addr(testworld.Contract), SellerID: testworld.SellerID,
		ProfileID: testworld.ProfileID, Nonce: x402.H32(nonce), RequestHash: rh, ResponseHash: x402.H32(protocol.ResponseHash(respBody)),
		ClaimsHash: x402.H32(testworld.ClaimsHash), PredicateCommitment: x402.H32(c), Epoch: p.Epoch, IssuedAt: 1}
	rc.Signature = x402.Hex(s.w.SellerKey.Sign(rc.Digest()))
	s.receipts[nonce] = rc
	return rc
}

func (s *stubSeller) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.mode == "down" || (s.mode == "downPaid" && r.Header.Get(x402.HeaderPaymentSignature) != "") {
		http.Error(w, "down", http.StatusServiceUnavailable)
		return
	}
	if strings.HasPrefix(r.URL.Path, "/fairbind/serve/") {
		s.serve(w, r)
		return
	}
	if strings.HasPrefix(r.URL.Path, "/fairbind/proofs/") {
		s.proof(w, r)
		return
	}
	var hs []httpcanon.Header
	for n, vs := range r.Header {
		for _, v := range vs {
			hs = append(hs, httpcanon.Header{Name: n, Value: v})
		}
	}
	path, query, _ := strings.Cut(r.RequestURI, "?")
	c, err := httpcanon.Normalize(httpcanon.Request{Method: r.Method, Path: path, Query: query, Headers: hs}, []string{"accept"}, map[string]bool{"accept": true}, 65536)
	if err != nil {
		http.Error(w, err.Error(), 400)
		return
	}
	pay := r.Header.Get(x402.HeaderPaymentSignature)
	if pay == "" {
		pr := x402.PaymentRequired{X402Version: 2, Error: "Payment required", Resource: x402.Resource{URL: "http://seller.test" + path, Description: "q", MimeType: "application/json"},
			Accepts: []x402.Accept{s.w.Accept()}, Extensions: map[string]x402.OfferExtension{x402.ExtensionKey: {Info: s.w.Offer(), Schema: testworld.Schema("fairbind-extension-v1.schema.json")}}}
		h, _ := x402.EncodeHeader(pr)
		w.Header().Set(x402.HeaderPaymentRequired, h)
		w.WriteHeader(402)
		return
	}
	var pp x402.PaymentPayload
	if err := x402.DecodeHeader(pay, &pp); err != nil {
		http.Error(w, err.Error(), 400)
		return
	}
	info := pp.Extensions[x402.ExtensionKey].Info
	if *info.RequestHash != x402.H32(c.Hash()) {
		http.Error(w, x402.ErrRequestHashMismatch, 400)
		return
	}
	s.paid++
	sig, _ := x402.ParseHex(pp.Payload.Signature)
	_, err = s.w.Fake.As(testworld.Facilitator).Settle(ctx, chain.Settlement{SellerID: info.SellerID, ProfileID: info.ProfileID,
		ClaimsHash: protocol.Bytes32(info.ClaimsHash), Key: protocol.Bytes16(*info.IdempotencyKey), RequestHash: protocol.Bytes32(*info.RequestHash),
		Authorization: pp.Payload.Authorization, Signature: sig})
	if err != nil && !chain.IsRevert(err, "KeyAlreadyUsed") {
		http.Error(w, err.Error(), 402)
		return
	}
	nonce := protocol.Bytes32(pp.Payload.Authorization.Nonce)
	s.requests[nonce] = x402.CanonicalRequest{Method: []byte(c.Method), Path: []byte(c.Path), Query: []byte(c.Query), HeaderBlock: []byte(c.Headers), Body: c.Body}
	s.keys[nonce] = *info.IdempotencyKey
	if s.mode == "withhold" {
		http.Error(w, "internal", 500)
		return
	}
	rc := s.receipt(nonce, *info.RequestHash, body)
	if s.mode == "badReceipt" {
		rc.ResponseHash[0] ^= 1
	}
	h, _ := x402.EncodeHeader(rc)
	w.Header().Set(x402.HeaderReceipt, h)
	w.Write(body)
}

func (s *stubSeller) proof(w http.ResponseWriter, r *http.Request) {
	n, _ := x402.ParseH32(strings.TrimPrefix(r.URL.Path, "/fairbind/proofs/"))
	var entries []x402.Entry
	for nonce, rc := range s.receipts {
		entries = append(entries, x402.Entry{Nonce: x402.H32(nonce), ReceiptLeaf: x402.H32(rc.Digest())})
	}
	tree, err := x402.BuildTree(entries)
	if err != nil {
		http.Error(w, "none", 404)
		return
	}
	e, p, ok := tree.Prove(protocol.Bytes32(n))
	if !ok {
		http.Error(w, "none", 404)
		return
	}
	json.NewEncoder(w).Encode(proofResponse{Root: x402.H32(tree.Root()), Entry: e, Proof: p})
}

func (s *stubSeller) bundle(nonce protocol.Bytes32) x402.ServeBundle {
	rc := s.receipt(nonce, x402.H32(s.requests[nonce].Hash(httpcanon.ID)), body)
	rt := x402.U64(1)
	ss, tp := x402.H32{1}, x402.H32{2}
	b := x402.ServeBundle{Version: 1, Nonce: x402.H32(nonce), IdempotencyKey: s.keys[nonce], CanonicalRequest: s.requests[nonce], ResponseBody: body,
		Receipt: rc, PredicatePreimage: x402.Preimage{Kind: "data-api", ReferenceTime: &rt, SourceSetHash: &ss, TolerancePolicyHash: &tp}}
	if s.mode == "badBundle" {
		b.ResponseBody = []byte("other")
	}
	b.BundleHash = x402.H32(b.ComputeHash())
	return b
}

func (s *stubSeller) serve(w http.ResponseWriter, r *http.Request) {
	n, _ := x402.ParseH32(strings.TrimPrefix(r.URL.Path, "/fairbind/serve/"))
	raw, _ := base64.StdEncoding.DecodeString(r.Header.Get(x402.HeaderServeAuth))
	var a x402.ServeAuthorization
	if json.Unmarshal(raw, &a) != nil || a.Role != x402.RoleBuyer {
		http.Error(w, "forbidden", 403)
		return
	}
	json.NewEncoder(w).Encode(s.bundle(protocol.Bytes32(n)))
}

// serveOnChain records the served bundle as the seller would.
func (s *stubSeller) serveOnChain(nonce protocol.Bytes32) {
	s.mu.Lock()
	b := s.bundle(nonce)
	s.mu.Unlock()
	if _, err := s.w.Fake.As(testworld.SellerOwner).Served(ctx, nonce, protocol.Bytes32(b.BundleHash)); err != nil {
		s.t.Fatal(err)
	}
}

type harness struct {
	t     *testing.T
	w     *testworld.World
	stub  *stubSeller
	srv   *httptest.Server
	dir   string
	store *fsstore.Store
	b     *Buyer
	worst bool // worst-path directive
}

func newHarness(t *testing.T) *harness {
	w := testworld.New()
	h := &harness{t: t, w: w, dir: t.TempDir()}
	h.stub = &stubSeller{t: t, w: w, receipts: map[protocol.Bytes32]x402.Receipt{}, requests: map[protocol.Bytes32]x402.CanonicalRequest{}, keys: map[protocol.Bytes32]x402.H16{}}
	h.srv = httptest.NewServer(h.stub)
	t.Cleanup(h.srv.Close)
	h.open()
	t.Cleanup(func() { h.store.Close() })
	return h
}

func (h *harness) open() {
	st, err := fsstore.Open(h.dir)
	if err != nil {
		h.t.Fatal(err)
	}
	h.store = st
	b, err := New(ctx, Options{Network: "eip155:31337", Signer: h.w.BuyerKey, Address: h.w.BuyerKey.Address(), MaxPrice: 50_000, Now: h.w.Fake.Time,
		WorstPath: h.worst}, h.w.Fake.As(h.w.BuyerKey.Address()), st)
	if err != nil {
		h.t.Fatal(err)
	}
	h.b = b
}

func (h *harness) restart() { h.store.Close(); h.open() }

func (h *harness) req() Request {
	return Request{Method: "GET", URL: h.srv.URL + "/v1/quote?b=2&a=1", Headers: [][2]string{{"Accept", "application/json"}}}
}

func (h *harness) mustState(r *Record, want string) {
	h.t.Helper()
	if r.State != want {
		h.t.Fatalf("state %s (%s), want %s", r.State, r.Reason, want)
	}
}

func (h *harness) advance(id string) *Record {
	h.t.Helper()
	r, err := h.b.Advance(ctx, id)
	if err != nil {
		h.t.Fatalf("advance: %v", err)
	}
	return r
}

func (h *harness) anchor(epoch uint32) protocol.Bytes32 {
	var entries []x402.Entry
	for n, rc := range h.stub.receipts {
		entries = append(entries, x402.Entry{Nonce: x402.H32(n), ReceiptLeaf: x402.H32(rc.Digest())})
	}
	tree, _ := x402.BuildTree(entries)
	h.w.Fake.MineTo(h.w.Profile.AnchorBase(epoch))
	if _, err := h.w.Fake.As(testworld.SellerOwner).Anchor(ctx, testworld.SellerID, epoch, tree.Entries, tree.Count(), protocol.Bytes32{}); err != nil {
		h.t.Fatal(err)
	}
	return tree.Root()
}

func TestPurchaseReceiptAndInclusionProof(t *testing.T) {
	h := newHarness(t)
	r, err := h.b.Buy(ctx, h.req())
	if err != nil {
		t.Fatal(err)
	}
	h.mustState(r, StateReceived)
	if string(r.Response.Body) != string(body) || r.Receipt == nil {
		t.Fatal("response not stored")
	}
	h.mustState(h.advance(r.Key.String()), StateReceived) // not anchored yet
	root := h.anchor(0)
	r = h.advance(r.Key.String())
	h.mustState(r, StateProven)
	if protocol.Bytes32(*r.AnchorRoot) != root {
		t.Fatal("root")
	}
}

func TestRestartResendsTheSavedPayload(t *testing.T) {
	h := newHarness(t)
	h.stub.setMode("downPaid")
	r, err := h.b.Buy(ctx, h.req())
	if err != nil {
		t.Fatal(err)
	}
	h.mustState(r, StateOffered)
	saved := r.Payload.Payload.Signature
	h.restart()
	h.stub.setMode("")
	h.w.Fake.Mine(3)
	r = h.advance(r.Key.String())
	h.mustState(r, StateReceived)
	if r.Payload.Payload.Signature != saved || h.w.Fake.Calls("Settle") != 1 {
		t.Fatal("a new authorization was created")
	}
}

func TestExpiredUnsettledAuthorizationIsAbandoned(t *testing.T) {
	h := newHarness(t)
	h.stub.setMode("downPaid")
	r, _ := h.b.Buy(ctx, h.req())
	h.w.Fake.Mine(100) // 200 seconds of fake time
	r = h.advance(r.Key.String())
	h.mustState(r, StateAbandoned)
}

func TestNonDeliveryServeAccepted(t *testing.T) {
	h := newHarness(t)
	h.stub.setMode("withhold")
	r, _ := h.b.Buy(ctx, h.req())
	h.mustState(r, StateOffered)
	h.w.Fake.MineTo(h.w.Profile.EpochOrigin + uint64(h.w.Profile.Deadlines.ResponseBlocks) + 2)
	r = h.advance(r.Key.String())
	h.mustState(r, StateDisputed)
	nonce := protocol.Bytes32(*r.Nonce)
	h.stub.setMode("")
	h.stub.serveOnChain(nonce)
	h.restart()
	r = h.advance(r.Key.String())
	h.mustState(r, StateReceived)
	cs, _ := h.w.Fake.As(testworld.SellerOwner).GetCase(ctx, nonce)
	if cs.State != chain.CaseDelivered || r.Response.Source != "serve" {
		t.Fatalf("case %d source %s", cs.State, r.Response.Source)
	}
}

func TestInvalidReceiptLeadsToDisputeAndBadBundleToEscalation(t *testing.T) {
	h := newHarness(t)
	h.stub.setMode("badReceipt")
	r, _ := h.b.Buy(ctx, h.req())
	h.mustState(r, StateOffered)
	if !strings.Contains(r.Reason, "invalid receipt") {
		t.Fatal(r.Reason)
	}
	h.w.Fake.Mine(uint64(h.w.Profile.Deadlines.ResponseBlocks) + 1)
	r = h.advance(r.Key.String())
	h.mustState(r, StateDisputed)
	nonce := protocol.Bytes32(*r.Nonce)
	h.stub.setMode("badBundle")
	h.stub.serveOnChain(nonce)
	r = h.advance(r.Key.String())
	cs, _ := h.w.Fake.As(testworld.SellerOwner).GetCase(ctx, nonce)
	if cs.State != chain.CasePublishing {
		t.Fatalf("case %d (%s)", cs.State, r.Reason)
	}
	// The seller never publishes: the buyer times the case out and is refunded.
	before := h.w.Fake.Balance(h.w.BuyerKey.Address())
	h.w.Fake.Mine(uint64(h.w.Profile.Deadlines.ServeBlocks) + 1)
	r = h.advance(r.Key.String())
	r = h.advance(r.Key.String())
	h.mustState(r, StateRefunded)
	if got := h.w.Fake.Balance(h.w.BuyerKey.Address()) - before; got != testworld.Price+h.w.Profile.DisputeDeposit {
		t.Fatalf("refund %d", got)
	}
}

func TestClaimWithReceiptWhenBondIsClaimOpen(t *testing.T) {
	h := newHarness(t)
	r, _ := h.b.Buy(ctx, h.req())
	h.anchor(0)
	r = h.advance(r.Key.String())
	h.mustState(r, StateProven)
	h.w.Fake.FreezeBond(testworld.BondID, 100)
	h.stub.setMode("down") // the proof was fetched earlier
	before := h.w.Fake.Balance(h.w.BuyerKey.Address())
	r = h.advance(r.Key.String())
	h.mustState(r, StateRefunded)
	if h.w.Fake.Balance(h.w.BuyerKey.Address())-before != testworld.Price || h.w.Fake.Calls("ClaimRefundWithReceipt") != 1 {
		t.Fatal("claim not paid")
	}
}

func TestEpochFailureRefund(t *testing.T) {
	h := newHarness(t)
	r, _ := h.b.Buy(ctx, h.req())
	h.w.Fake.MineTo(h.w.Profile.AnchorDeadline(0) + 1)
	r = h.advance(r.Key.String())
	h.mustState(r, StateRefunded)
}

func TestOfferValidation(t *testing.T) {
	h := newHarness(t)
	b2, _ := New(ctx, Options{Network: "eip155:31337", Signer: h.w.BuyerKey, Address: h.w.BuyerKey.Address(), MaxPrice: 100, Now: h.w.Fake.Time},
		h.w.Fake.As(h.w.BuyerKey.Address()), h.store)
	r, _ := b2.Buy(ctx, h.req())
	h.mustState(r, StateFailed)
	req := h.req()
	req.Headers = nil // missing canonical header
	r, _ = h.b.Buy(ctx, req)
	h.mustState(r, StateFailed)
	if _, err := New(ctx, Options{Network: "x", Signer: h.w.SellerKey, Address: h.w.BuyerKey.Address(), MaxPrice: 1}, h.w.Fake.As(h.w.BuyerKey.Address()), h.store); err == nil {
		t.Fatal("mismatched signer accepted")
	}
	h.stub.setMode("down")
	r, err := h.b.Buy(ctx, h.req())
	if err == nil || r != nil && r.State != StateNew {
		t.Fatal("an unavailable seller is not transient")
	}
	h.stub.setMode("")
	if err := h.b.Tick(ctx); err != nil {
		t.Fatal(err)
	}
}
