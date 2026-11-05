package e2e

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/ledger"
	gate "example.org/fairbind/runtime/verifier"
	"example.org/fairbind/services/buyer"
	"example.org/fairbind/services/facilitator"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/ethkey"
	"example.org/fairbind/services/internal/x402/fsstore"
	"example.org/fairbind/services/internal/x402/testworld"
	"example.org/fairbind/services/seller"
	verifiersvc "example.org/fairbind/services/verifier"
)

var ctx = context.Background()

// dropPaid forwards to the seller but, while armed, discards the answer to
// paid requests, as when the connection breaks after the seller responded.
type dropPaid struct {
	next  http.Handler
	armed atomic.Bool
}

type discard struct{ h http.Header }

func (d *discard) Header() http.Header         { return d.h }
func (d *discard) Write(b []byte) (int, error) { return len(b), nil }
func (d *discard) WriteHeader(int)             {}

func (p *dropPaid) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if p.armed.Load() && r.Header.Get(x402.HeaderPaymentSignature) != "" {
		p.next.ServeHTTP(&discard{h: http.Header{}}, r)
		http.Error(w, "bad gateway", http.StatusBadGateway)
		return
	}
	p.next.ServeHTTP(w, r)
}

type system struct {
	t          *testing.T
	w          *testworld.World
	facDir     string
	facStore   *fsstore.Store
	fac        *facilitator.Facilitator
	facSrv     *httptest.Server
	sellerDir  string
	sellStore  *fsstore.Store
	seller     *seller.Seller
	proxy      *dropPaid
	sellerSrv  *httptest.Server
	buyerStore *fsstore.Store
	buyer      *buyer.Buyer
}

func (s *system) startFacilitator() {
	st, err := fsstore.Open(s.facDir)
	if err != nil {
		s.t.Fatal(err)
	}
	f, err := facilitator.New(facilitator.Options{Network: "eip155:31337", TokenName: "MockUSDC", TokenVersion: "2",
		SettlementSchema: testworld.Schema("fairbind-settlement-v1.schema.json"), Now: s.w.Fake.Time}, s.w.Fake.As(testworld.Facilitator), st)
	if err != nil {
		s.t.Fatal(err)
	}
	if _, err = f.Recover(ctx); err != nil {
		s.t.Fatal(err)
	}
	s.facStore, s.fac = st, f
	s.facSrv.Config.Handler = f.Handler()
}

func (s *system) startSeller() {
	st, err := fsstore.Open(s.sellerDir)
	if err != nil {
		s.t.Fatal(err)
	}
	rt := x402.U64(1788480000)
	ss, tp := x402.H32(protocol.Keccak256([]byte("sources"))), x402.H32(protocol.Keccak256([]byte("tolerance")))
	quote := seller.HandlerFunc(func(context.Context, x402.CanonicalRequest) (seller.Response, error) {
		return seller.Response{Status: 200, ContentType: "application/json", Body: []byte(`{"price":"123.45","symbol":"ETH-USD"}` + "\n"),
			Preimage: x402.Preimage{Kind: "data-api", ReferenceTime: &rt, SourceSetHash: &ss, TolerancePolicyHash: &tp}}, nil
	})
	sl, err := seller.New(ctx, seller.Options{SellerID: testworld.SellerID, Network: "eip155:31337", PublicURL: s.sellerSrv.URL,
		ServiceName: "Test API", ServiceClass: "data-api", ProfileHash: testworld.ProfileHash, CanonicalHeaders: []string{"accept"},
		Price: testworld.Price, TokenName: "MockUSDC", TokenVersion: "2",
		ExtensionSchema: testworld.Schema("fairbind-extension-v1.schema.json"), SettlementSchema: testworld.Schema("fairbind-settlement-v1.schema.json"),
		Claims:      testworld.Claims,
		Routes:      []seller.Route{{Path: "/v1/quote", Description: "Signed market quote", MimeType: "application/json", Handler: quote}},
		Facilitator: x402.HTTPFacilitator{URL: s.facSrv.URL}, Signer: s.w.SellerKey, Now: s.w.Fake.Time, PendingPolls: 2, PendingInterval: 1},
		s.w.Fake.As(testworld.SellerOwner), st)
	if err != nil {
		s.t.Fatal(err)
	}
	s.sellStore, s.seller = st, sl
	s.proxy.next = sl.Handler()
}

func (s *system) stopSeller() {
	s.sellStore.Close()
	s.proxy.next = http.NotFoundHandler()
}

func newSystem(t *testing.T) *system {
	s := &system{t: t, w: testworld.New(), facDir: t.TempDir(), sellerDir: t.TempDir(), proxy: &dropPaid{}}
	s.facSrv = httptest.NewServer(http.NotFoundHandler())
	s.sellerSrv = httptest.NewServer(s.proxy)
	t.Cleanup(s.facSrv.Close)
	t.Cleanup(s.sellerSrv.Close)
	s.startFacilitator()
	s.startSeller()
	st, err := fsstore.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s.buyerStore = st
	s.buyer, err = buyer.New(ctx, buyer.Options{Network: "eip155:31337", Signer: s.w.BuyerKey, Address: s.w.BuyerKey.Address(),
		MaxPrice: 50_000, Now: s.w.Fake.Time}, s.w.Fake.As(s.w.BuyerKey.Address()), st)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func (s *system) request() buyer.Request {
	return buyer.Request{Method: "GET", URL: s.sellerSrv.URL + "/v1/quote?symbol=ETH-USD", Headers: [][2]string{{"Accept", "application/json"}}}
}

func (s *system) tickAll() {
	s.t.Helper()
	if err := s.seller.Tick(ctx); err != nil {
		s.t.Fatalf("seller tick: %v", err)
	}
	if err := s.buyer.Tick(ctx); err != nil {
		s.t.Fatalf("buyer tick: %v", err)
	}
}

func want(t *testing.T, r *buyer.Record, state string) {
	t.Helper()
	if r.State != state {
		t.Fatalf("buyer state %s (%s), want %s", r.State, r.Reason, state)
	}
}

func TestPurchaseSettleReceiptAnchorProof(t *testing.T) {
	s := newSystem(t)
	r, err := s.buyer.Buy(ctx, s.request())
	if err != nil {
		t.Fatal(err)
	}
	want(t, r, buyer.StateReceived)
	nonce := protocol.Bytes32(*r.Nonce)
	view := s.w.Fake.As(testworld.SellerOwner)
	p, _ := view.GetPurchase(ctx, nonce)
	if !p.Exists() || p.FinancialState != chain.FinDeferred || s.w.Fake.Calls("Settle") != 1 {
		t.Fatalf("purchase %+v", p)
	}
	if r.Settlement == nil || r.Settlement.Extensions[x402.ExtensionKey].Info.Purchase != *r.Nonce {
		t.Fatal("settlement response not returned to the buyer")
	}
	// The facilitator restarts between the purchase and the anchor.
	s.facStore.Close()
	s.startFacilitator()
	s.tickAll()
	if a, _ := view.GetAnchor(ctx, testworld.SellerID, 0); a.State != chain.EpochNone {
		t.Fatal("anchored before the fixed window")
	}
	s.w.Fake.MineTo(s.w.Profile.AnchorBase(0))
	s.tickAll()
	a, _ := view.GetAnchor(ctx, testworld.SellerID, 0)
	if a.State != chain.EpochAnchored || a.Count != 1 {
		t.Fatalf("anchor %+v", a)
	}
	r, _ = s.buyer.Get(r.Key.String())
	want(t, r, buyer.StateProven)
	if protocol.Bytes32(*r.AnchorRoot) != a.Root ||
		!protocol.VerifyReceiptProof(a.Root, protocol.ReceiptEntry{Nonce: nonce, ReceiptLeaf: r.Receipt.Digest()}, r.Proof.Typed()) {
		t.Fatal("inclusion proof does not verify against the anchor")
	}
}

func TestNonDeliveryDisputeResolvedByServe(t *testing.T) {
	s := newSystem(t)
	s.proxy.armed.Store(true)
	r, err := s.buyer.Buy(ctx, s.request())
	if err != nil {
		t.Fatal(err)
	}
	want(t, r, buyer.StateOffered)
	nonce := protocol.Bytes32(*r.Nonce)
	view := s.w.Fake.As(testworld.SellerOwner)
	p, _ := view.GetPurchase(ctx, nonce)
	if !p.Exists() {
		t.Fatal("payment was not settled")
	}
	s.w.Fake.MineTo(p.ResponseDue + 1)
	if err := s.buyer.Tick(ctx); err != nil {
		t.Fatal(err)
	}
	r, _ = s.buyer.Get(r.Key.String())
	want(t, r, buyer.StateDisputed)
	if cs, _ := view.GetCase(ctx, nonce); cs.State != chain.CaseServeWait {
		t.Fatalf("case %d", cs.State)
	}
	// The seller restarts before it notices the case.
	s.stopSeller()
	s.startSeller()
	s.tickAll()
	cs, _ := view.GetCase(ctx, nonce)
	r, _ = s.buyer.Get(r.Key.String())
	if cs.State != chain.CaseDelivered {
		t.Fatalf("case %d, buyer %s (%s)", cs.State, r.State, r.Reason)
	}
	want(t, r, buyer.StateReceived)
	if r.Response.Source != "serve" || protocol.ResponseHash(r.Response.Body) != protocol.Bytes32(r.Receipt.ResponseHash) {
		t.Fatal("served response not stored")
	}
	s.w.Fake.MineTo(s.w.Profile.AnchorBase(p.Epoch))
	s.tickAll()
	r, _ = s.buyer.Get(r.Key.String())
	want(t, r, buyer.StateProven)
}

func TestNonDeliveryDisputeRefundedWhenSellerIsGone(t *testing.T) {
	s := newSystem(t)
	s.proxy.armed.Store(true)
	r, _ := s.buyer.Buy(ctx, s.request())
	nonce := protocol.Bytes32(*r.Nonce)
	s.stopSeller() // the seller never runs again
	view := s.w.Fake.As(testworld.SellerOwner)
	p, _ := view.GetPurchase(ctx, nonce)
	before := s.w.Fake.Balance(s.w.BuyerKey.Address())
	s.w.Fake.MineTo(p.ResponseDue + 1)
	s.buyer.Tick(ctx)
	r, _ = s.buyer.Get(r.Key.String())
	want(t, r, buyer.StateDisputed)
	s.w.Fake.Mine(uint64(s.w.Profile.Deadlines.ServeBlocks) + 1)
	s.buyer.Tick(ctx)
	s.buyer.Tick(ctx)
	r, _ = s.buyer.Get(r.Key.String())
	want(t, r, buyer.StateRefunded)
	if cs, _ := view.GetCase(ctx, nonce); cs.State != chain.CaseUnserved {
		t.Fatalf("case %d", cs.State)
	}
	if s.w.Fake.Balance(s.w.BuyerKey.Address()) != before+testworld.Price {
		t.Fatal("price and deposit not returned")
	}
}

// TestVerifierRedeliveryAcrossHTTP runs the verifier's real HTTP redelivery
// client (services/verifier.HTTPSeller) against the seller's real HTTP
// handler, so the endpoint path, the serve-authorization header and the
// claims-hash check cannot drift against each other unnoticed. The fake
// chain does not model sampling and judgment, so the case's verifier
// assignment is injected directly with Fake.OpenCaseForTest.
func TestVerifierRedeliveryAcrossHTTP(t *testing.T) {
	s := newSystem(t)
	r, err := s.buyer.Buy(ctx, s.request())
	if err != nil {
		t.Fatal(err)
	}
	want(t, r, buyer.StateReceived)
	nonce := protocol.Bytes32(*r.Nonce)
	view := s.w.Fake.As(testworld.SellerOwner)

	const verifierID = 9
	verifierKey, err := ethkey.ParsePrivateKey("0x" + strings.Repeat("0", 63) + "2")
	if err != nil {
		t.Fatal(err)
	}
	s.w.Fake.AddVerifier(chain.Verifier{VerifierID: verifierID, SigningKey: verifierKey.Address()})
	head, err := view.BlockNumber(ctx)
	if err != nil {
		t.Fatal(err)
	}
	s.w.Fake.OpenCaseForTest(nonce, chain.Case{CaseOpenedBlock: head, State: chain.CaseJudging, AssignedVerifierID: verifierID})

	a := ledger.Assignment{
		Snapshot: gate.Snapshot{ChainID: testworld.ChainID, Contract: testworld.Contract, SellerID: testworld.SellerID, Nonce: nonce},
		JudgeDue: head + 1000,
	}
	client := verifiersvc.HTTPSeller{ChainID: testworld.ChainID, Contract: testworld.Contract,
		Endpoints: map[uint32]string{testworld.SellerID: s.sellerSrv.URL}, Cases: view, Signer: verifierKey}
	b, _, err := client.Redeliver(ctx, a)
	if err != nil {
		t.Fatal(err)
	}
	if protocol.Keccak256(b.Claims) != testworld.ClaimsHash {
		t.Fatal("redelivered claims do not hash to the registered claimsHash")
	}

	// The same HTTP boundary, exercised directly for the failure statuses.
	authFor := func(validUntil uint64, key *ethkey.PrivateKey) string {
		d := x402.ServeAuthDigest(testworld.ChainID, testworld.Contract, nonce, x402.RoleVerifier, head, validUntil)
		raw, _ := json.Marshal(x402.ServeAuthorization{Role: x402.RoleVerifier, CaseOpenedBlock: head, ValidUntil: validUntil, Signature: x402.Hex(key.Sign(d))})
		return base64.StdEncoding.EncodeToString(raw)
	}
	fetch := func(n protocol.Bytes32, auth string) int {
		req, _ := http.NewRequest("GET", s.sellerSrv.URL+"/fairbind/serve/"+x402.H32(n).String(), nil)
		req.Header.Set(x402.HeaderServeAuth, auth)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		return resp.StatusCode
	}
	stranger, err := ethkey.ParsePrivateKey("0x" + strings.Repeat("0", 63) + "3")
	if err != nil {
		t.Fatal(err)
	}
	if code := fetch(nonce, authFor(head+1000, stranger)); code != http.StatusUnauthorized {
		t.Fatalf("wrong signature: got %d, want 401", code)
	}
	s.w.Fake.Mine(5) // advance the head past a validUntil fixed at the old head
	if code := fetch(nonce, authFor(head, verifierKey)); code != http.StatusUnauthorized {
		t.Fatalf("expired validUntil: got %d, want 401", code)
	}
	if code := fetch(protocol.Bytes32{0xff}, authFor(head+1000, verifierKey)); code != http.StatusNotFound {
		t.Fatalf("unknown nonce: got %d, want 404", code)
	}
}
