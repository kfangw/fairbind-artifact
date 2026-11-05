package seller

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"example.org/fairbind/adapters/httpcanon"
	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/directive"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/ethkey"
	"example.org/fairbind/services/internal/x402/fsstore"
	"example.org/fairbind/services/internal/x402/testworld"
)

var ctx = context.Background()

// stubFacilitator settles directly on the fake chain.
type stubFacilitator struct {
	w    *testworld.World
	mode atomic.Int32 // 0 normal, 1 fail before settle, 2 settle then lose the response
}

func (f *stubFacilitator) Settle(ctx context.Context, req x402.SettleRequest) (x402.SettlementResponse, error) {
	mode := f.mode.Load()
	if mode == 1 {
		return x402.SettlementResponse{}, errors.New("connection refused")
	}
	pp := req.PaymentPayload
	info := pp.Extensions[x402.ExtensionKey].Info
	sig, _ := x402.ParseHex(pp.Payload.Signature)
	c := f.w.Fake.As(testworld.Facilitator)
	tx, err := c.Settle(ctx, chain.Settlement{SellerID: info.SellerID, ProfileID: info.ProfileID, ClaimsHash: protocol.Bytes32(info.ClaimsHash),
		Key: protocol.Bytes16(*info.IdempotencyKey), RequestHash: protocol.Bytes32(*info.RequestHash), Authorization: pp.Payload.Authorization, Signature: sig})
	if mode == 2 {
		return x402.SettlementResponse{}, errors.New("connection reset")
	}
	if err != nil && !chain.IsRevert(err, "KeyAlreadyUsed") {
		return x402.SettlementResponse{Success: false, ErrorReason: "unexpected_settle_error"}, nil
	}
	p, _ := c.GetPurchase(ctx, protocol.Bytes32(pp.Payload.Authorization.Nonce))
	return x402.SettlementResponse{Success: true, Transaction: x402.H32(tx).String(), Network: "eip155:31337", Payer: pp.Payload.Authorization.From.String(),
		Amount: "10000", Extensions: map[string]x402.SettlementExtension{x402.ExtensionKey: {Info: x402.SettlementInfo{Version: 1,
			Purchase: x402.H32(p.Nonce), KeyID: x402.H32(p.KeyID), SellerID: p.SellerID, ProfileID: p.ProfileID, Epoch: p.Epoch,
			FinancialState: "DEFERRED"}, Schema: testworld.Schema("fairbind-settlement-v1.schema.json")}}}, nil
}

type harness struct {
	t       *testing.T
	w       *testworld.World
	dir     string
	store   *fsstore.Store
	s       *Seller
	srv     *httptest.Server
	fac     *stubFacilitator
	handled atomic.Int32
	worst   bool // worst-path directive
	attack  *directive.FiniteAttack
}

func dataBody(n int) []byte {
	if n == 0 {
		return []byte(`{"price":"123.45","symbol":"ETH-USD"}`)
	}
	return bytes.Repeat([]byte("x"), n)
}

// cheatBody is what the quote route serves on a sale the finite attack cheats on.
var cheatBody = []byte(`{"price":"1.00","symbol":"ETH-USD"}`)

func newHarness(t *testing.T) *harness {
	h := &harness{t: t, w: testworld.New(), dir: t.TempDir()}
	h.fac = &stubFacilitator{w: h.w}
	h.start()
	t.Cleanup(func() { h.stop() })
	return h
}

func (h *harness) start() {
	st, err := fsstore.Open(h.dir)
	if err != nil {
		h.t.Fatal(err)
	}
	h.store = st
	rt := x402.U64(1788480000)
	ss, tp := x402.H32{1}, x402.H32{2}
	pre := x402.Preimage{Kind: "data-api", ReferenceTime: &rt, SourceSetHash: &ss, TolerancePolicyHash: &tp}
	handler := func(size int) Handler {
		return HandlerFunc(func(ctx context.Context, req x402.CanonicalRequest) (Response, error) {
			h.handled.Add(1)
			return Response{Status: 200, ContentType: "application/json", Body: dataBody(size), Preimage: pre}, nil
		})
	}
	h.srv = httptest.NewUnstartedServer(nil)
	opt := Options{SellerID: testworld.SellerID, Network: "eip155:31337", PublicURL: "https://seller.test", ServiceName: "Test API",
		ServiceClass: "data-api", ProfileHash: testworld.ProfileHash, CanonicalHeaders: []string{"accept"}, Price: testworld.Price,
		TokenName: "MockUSDC", TokenVersion: "2", ExtensionSchema: testworld.Schema("fairbind-extension-v1.schema.json"),
		SettlementSchema: testworld.Schema("fairbind-settlement-v1.schema.json"), Claims: testworld.Claims,
		Routes: []Route{{Path: "/v1/quote", Description: "quote", MimeType: "application/json", Handler: handler(0),
			Cheat: HandlerFunc(func(ctx context.Context, req x402.CanonicalRequest) (Response, error) {
				return Response{Status: 200, ContentType: "application/json", Body: cheatBody, Preimage: pre}, nil
			})},
			{Path: "/v1/large", Description: "large", MimeType: "application/octet-stream", Handler: handler(40000)}},
		Facilitator: h.fac, Signer: h.w.SellerKey, Now: h.w.Fake.Time, PendingPolls: 2, PendingInterval: 1, WorstPath: h.worst,
		FiniteAttack: h.attack}
	s, err := New(ctx, opt, h.w.Fake.As(testworld.SellerOwner), st)
	if err != nil {
		h.t.Fatal(err)
	}
	h.s = s
	h.srv.Config.Handler = s.Handler()
	h.srv.Start()
}

// stop simulates process exit: the server stops and the data directory lock
// is released. Persisted files remain.
func (h *harness) stop() {
	if h.srv != nil {
		h.srv.Close()
		h.srv = nil
	}
	if h.store != nil {
		h.store.Close()
		h.store = nil
	}
}

func (h *harness) restart() { h.stop(); h.start() }

type purchase struct {
	path    string
	key     protocol.Bytes16
	payload x402.PaymentPayload
	header  string
	nonce   protocol.Bytes32
}

func (h *harness) request(method, path string, key protocol.Bytes16, payment string) *http.Response {
	req, _ := http.NewRequest(method, h.srv.URL+path, nil)
	req.Header.Set("Accept", "application/json")
	req.Header.Set(x402.HeaderKey, x402.EncodeKey(x402.H16(key)))
	req.Header.Set(x402.HeaderPayer, x402.Addr(h.w.BuyerKey.Address()).String())
	if payment != "" {
		req.Header.Set(x402.HeaderPaymentSignature, payment)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		h.t.Fatal(err)
	}
	return resp
}

func requestHash(t *testing.T, path string) protocol.Bytes32 {
	p, q, _ := strings.Cut(path, "?")
	c, err := httpcanon.Normalize(httpcanon.Request{Method: "GET", Path: p, Query: q, Headers: []httpcanon.Header{{Name: "Accept", Value: "application/json"}}},
		[]string{"accept"}, map[string]bool{"accept": true}, 65536)
	if err != nil {
		t.Fatal(err)
	}
	return c.Hash()
}

// offerAndSign runs the unpaid request and signs a payload for the offer.
func (h *harness) offerAndSign(path string, key protocol.Bytes16) purchase {
	resp := h.request("GET", path, key, "")
	if resp.StatusCode != http.StatusPaymentRequired {
		h.t.Fatalf("unpaid status %d", resp.StatusCode)
	}
	var pr x402.PaymentRequired
	if err := x402.DecodeHeader(resp.Header.Get(x402.HeaderPaymentRequired), &pr); err != nil {
		h.t.Fatal(err)
	}
	ext := pr.Extensions[x402.ExtensionKey]
	rh := requestHash(h.t, path)
	k, r := x402.H16(key), x402.H32(rh)
	ext.Info.IdempotencyKey, ext.Info.RequestHash = &k, &r
	nonce := protocol.DeriveNonce(testworld.ChainID, testworld.Contract, testworld.SellerID, testworld.ProfileID, testworld.ClaimsHash, h.w.BuyerKey.Address(), key, rh)
	now := h.w.Fake.Time()
	auth := x402.Authorization{From: x402.Addr(h.w.BuyerKey.Address()), To: pr.Accepts[0].PayTo, Value: testworld.Price,
		ValidAfter: x402.U64(now - 10), ValidBefore: x402.U64(now + 60), Nonce: x402.H32(nonce)}
	sig := h.w.BuyerKey.Sign(x402.ReceiveDigest("MockUSDC", "2", testworld.ChainID, testworld.Token, auth))
	pp := x402.PaymentPayload{X402Version: 2, Resource: pr.Resource, Accepted: pr.Accepts[0],
		Payload: x402.ExactPayload{Signature: x402.Hex(sig), Authorization: auth}, Extensions: map[string]x402.OfferExtension{x402.ExtensionKey: ext}}
	header, _ := x402.EncodeHeader(pp)
	return purchase{path: path, key: key, payload: pp, header: header, nonce: nonce}
}

func (h *harness) buy(path string, key protocol.Bytes16) (purchase, *http.Response, []byte) {
	p := h.offerAndSign(path, key)
	resp := h.request("GET", path, key, p.header)
	body, _ := io.ReadAll(resp.Body)
	return p, resp, body
}

func (h *harness) checkReceipt(resp *http.Response, body []byte, nonce protocol.Bytes32) x402.Receipt {
	h.t.Helper()
	var rc x402.Receipt
	if err := x402.DecodeHeader(resp.Header.Get(x402.HeaderReceipt), &rc); err != nil {
		h.t.Fatalf("receipt header: %v (status %d, body %s)", err, resp.StatusCode, body)
	}
	sig, _ := rc.SignatureBytes()
	if err := ethkey.Verify(h.w.SellerKey.Address(), rc.Digest(), sig); err != nil {
		h.t.Fatal(err)
	}
	if protocol.Bytes32(rc.Nonce) != nonce || protocol.ResponseHash(body) != protocol.Bytes32(rc.ResponseHash) {
		h.t.Fatal("receipt does not bind the response")
	}
	return rc
}

func TestPurchaseReceiptAndIdempotentReplay(t *testing.T) {
	h := newHarness(t)
	p, resp, body := h.buy("/v1/quote?b=2&a=1", protocol.Bytes16{1})
	if resp.StatusCode != 200 || resp.Header.Get("Cache-Control") != "private" {
		t.Fatalf("status %d %s", resp.StatusCode, body)
	}
	rc := h.checkReceipt(resp, body, p.nonce)
	var sr x402.SettlementResponse
	if err := x402.DecodeHeader(resp.Header.Get(x402.HeaderPaymentResponse), &sr); err != nil || !sr.Success {
		t.Fatalf("payment response %v %+v", err, sr)
	}
	again := h.request("GET", p.path, p.key, p.header)
	body2, _ := io.ReadAll(again.Body)
	if !bytes.Equal(body, body2) || again.Header.Get(x402.HeaderReceipt) != resp.Header.Get(x402.HeaderReceipt) {
		t.Fatal("replay returned a different response or receipt")
	}
	if h.handled.Load() != 1 || h.w.Fake.Calls("Settle") != 1 {
		t.Fatalf("handler %d settle %d", h.handled.Load(), h.w.Fake.Calls("Settle"))
	}
	if rc.Epoch != 0 {
		t.Fatalf("epoch %d", rc.Epoch)
	}
}

func TestNegotiationRejections(t *testing.T) {
	h := newHarness(t)
	resp := h.request("GET", "/v1/quote", protocol.Bytes16{2}, "")
	if resp.StatusCode != 402 || resp.Header.Get("Cache-Control") != "no-store" {
		t.Fatal(resp.StatusCode)
	}
	var pr x402.PaymentRequired
	x402.DecodeHeader(resp.Header.Get(x402.HeaderPaymentRequired), &pr)
	info := pr.Extensions[x402.ExtensionKey].Info
	if pr.Accepts[0].PayTo != info.Contract || info.IdempotencyKey != nil || info.RequestHash != nil {
		t.Fatalf("offer %+v", info)
	}
	expect := func(p purchase, status int, id string) {
		t.Helper()
		header, _ := x402.EncodeHeader(p.payload)
		r := h.request("GET", p.path, p.key, header)
		var e apiError
		json.NewDecoder(r.Body).Decode(&e)
		if r.StatusCode != status || e.Error != id {
			t.Fatalf("got %d %q, want %d %q", r.StatusCode, e.Error, status, id)
		}
	}
	p := h.offerAndSign("/v1/quote", protocol.Bytes16{3})
	p.payload.Extensions[x402.ExtensionKey] = func() x402.OfferExtension {
		e := p.payload.Extensions[x402.ExtensionKey]
		e.Info.Remaining++
		return e
	}()
	expect(p, 400, x402.ErrExtensionEchoMismatch)
	p = h.offerAndSign("/v1/quote", protocol.Bytes16{4})
	p.path = "/v1/quote?changed=1"
	expect(p, 400, x402.ErrRequestHashMismatch)
	p = h.offerAndSign("/v1/quote", protocol.Bytes16{5})
	p.payload.Payload.Authorization.Nonce[0] ^= 1
	expect(p, 400, x402.ErrNonceMismatch)
	p = h.offerAndSign("/v1/quote", protocol.Bytes16{6})
	delete(p.payload.Extensions, x402.ExtensionKey)
	expect(p, 400, x402.ErrExtensionMissing)
	if h.w.Fake.Calls("Settle") != 0 {
		t.Fatal("a rejected payment reached settlement")
	}
	r := h.request("GET", "/v1/missing", protocol.Bytes16{7}, "")
	if r.StatusCode != 404 {
		t.Fatal(r.StatusCode)
	}
}

func TestSettlementOutcomeLostThenRestart(t *testing.T) {
	h := newHarness(t)
	h.fac.mode.Store(1)
	p := h.offerAndSign("/v1/quote", protocol.Bytes16{8})
	resp := h.request("GET", p.path, p.key, p.header)
	if resp.StatusCode != 500 {
		t.Fatalf("status %d", resp.StatusCode)
	}
	rec, _ := h.s.Record(p.nonce)
	if rec == nil || rec.State != StateSettling {
		t.Fatalf("record %+v", rec)
	}
	// The payment lands through another path while the seller is down.
	h.fac.mode.Store(0)
	h.fac.Settle(ctx, x402.SettleRequest{PaymentPayload: p.payload})
	h.restart()
	if err := h.s.Tick(ctx); err != nil {
		t.Fatal(err)
	}
	rec, _ = h.s.Record(p.nonce)
	if rec.State != StateSettled {
		t.Fatalf("after restart: %s", rec.State)
	}
	resp = h.request("GET", p.path, p.key, p.header)
	body, _ := io.ReadAll(resp.Body)
	h.checkReceipt(resp, body, p.nonce)
	// A lost facilitator response is confirmed through the ledger at once.
	h.fac.mode.Store(2)
	p2, resp2, body2 := h.buy("/v1/quote", protocol.Bytes16{9})
	if resp2.StatusCode != 200 {
		t.Fatalf("status %d %s", resp2.StatusCode, body2)
	}
	h.checkReceipt(resp2, body2, p2.nonce)
}

func TestAnchorProofsAndRestartAfterLostAnchor(t *testing.T) {
	h := newHarness(t)
	var nonces []protocol.Bytes32
	var receipts []x402.Receipt
	for i := byte(10); i < 13; i++ {
		p, resp, body := h.buy("/v1/quote", protocol.Bytes16{i})
		nonces = append(nonces, p.nonce)
		receipts = append(receipts, h.checkReceipt(resp, body, p.nonce))
	}
	// A settled purchase whose buyer never fetched the response.
	h.fac.mode.Store(1)
	late := h.offerAndSign("/v1/quote", protocol.Bytes16{13})
	h.request("GET", late.path, late.key, late.header)
	h.fac.mode.Store(0)
	h.fac.Settle(ctx, x402.SettleRequest{PaymentPayload: late.payload})
	if err := h.s.Tick(ctx); err != nil {
		t.Fatal(err)
	}
	if a, _ := h.w.Fake.As(testworld.SellerOwner).GetAnchor(ctx, testworld.SellerID, 0); a.State != chain.EpochNone {
		t.Fatal("anchored before the window")
	}
	h.w.Fake.MineTo(h.w.Profile.AnchorBase(0))
	h.w.Fake.Inject("Anchor", chain.LoseAfter)
	if err := h.s.Tick(ctx); err == nil {
		t.Fatal("lost anchor response not reported")
	}
	h.restart()
	if err := h.s.Tick(ctx); err != nil {
		t.Fatal(err)
	}
	if h.w.Fake.Calls("Anchor") != 1 {
		t.Fatalf("anchor submitted %d times", h.w.Fake.Calls("Anchor"))
	}
	a, _ := h.w.Fake.As(testworld.SellerOwner).GetAnchor(ctx, testworld.SellerID, 0)
	if a.State != chain.EpochAnchored || a.Count != 4 {
		t.Fatalf("anchor %+v", a)
	}
	rec, _ := h.s.Record(late.nonce)
	if rec.Receipt == nil {
		t.Fatal("late purchase has no receipt in the tree")
	}
	receipts = append(receipts, *rec.Receipt)
	nonces = append(nonces, late.nonce)
	for i, n := range nonces {
		r, err := http.Get(h.srv.URL + "/fairbind/proofs/" + x402.H32(n).String())
		if err != nil || r.StatusCode != 200 {
			t.Fatalf("proof %d: %v %d", i, err, r.StatusCode)
		}
		var pr ProofResponse
		json.NewDecoder(r.Body).Decode(&pr)
		leaf := receipts[i].Digest()
		if protocol.Bytes32(pr.Entry.ReceiptLeaf) != leaf || !protocol.VerifyReceiptProof(a.Root, protocol.ReceiptEntry{Nonce: n, ReceiptLeaf: leaf}, pr.Proof.Typed()) {
			t.Fatalf("proof %d does not verify against the anchored root", i)
		}
	}
	r, _ := http.Get(h.srv.URL + "/fairbind/epochs/0/manifest")
	raw, _ := io.ReadAll(r.Body)
	if protocol.Keccak256(raw) != a.PublicationHash {
		t.Fatal("manifest does not hash to the anchored publicationHash")
	}
	var m x402.Manifest
	json.Unmarshal(raw, &m)
	r, _ = http.Get(h.srv.URL + "/fairbind/epochs/0/entries")
	raw, _ = io.ReadAll(r.Body)
	if protocol.Keccak256(raw) != protocol.Bytes32(m.EntriesHash) {
		t.Fatal("entries do not hash to entriesHash")
	}
	// Retention ends: bodies are dropped, proofs remain.
	h.w.Fake.MineTo(rec.RetainUntil + 1)
	if err := h.s.Tick(ctx); err != nil {
		t.Fatal(err)
	}
	rec, _ = h.s.Record(nonces[0])
	if rec.State != StatePruned || rec.Response != nil || rec.Receipt == nil {
		t.Fatalf("pruned record %+v", rec.State)
	}
}

func (h *harness) serveAuth(nonce protocol.Bytes32, key *ethkey.PrivateKey, role uint8) string {
	cs, _ := h.w.Fake.As(testworld.SellerOwner).GetCase(ctx, nonce)
	until := cs.ServeDue
	if cs.State == chain.CaseServeConfirm {
		until = cs.ChallengeUntil
	}
	d := x402.ServeAuthDigest(testworld.ChainID, testworld.Contract, nonce, role, cs.CaseOpenedBlock, until)
	raw, _ := json.Marshal(x402.ServeAuthorization{Role: role, CaseOpenedBlock: cs.CaseOpenedBlock, ValidUntil: until, Signature: x402.Hex(key.Sign(d))})
	return base64.StdEncoding.EncodeToString(raw)
}

func (h *harness) fetchBundle(nonce protocol.Bytes32, auth string) (*x402.ServeBundle, int) {
	req, _ := http.NewRequest("GET", h.srv.URL+"/fairbind/serve/"+x402.H32(nonce).String(), nil)
	req.Header.Set(x402.HeaderServeAuth, auth)
	r, err := http.DefaultClient.Do(req)
	if err != nil {
		h.t.Fatal(err)
	}
	if r.StatusCode != 200 {
		return nil, r.StatusCode
	}
	var b x402.ServeBundle
	if err = json.NewDecoder(r.Body).Decode(&b); err != nil {
		h.t.Fatal(err)
	}
	return &b, 200
}

func testServeAndPublish(t *testing.T, path string) {
	h := newHarness(t)
	p, resp, body := h.buy(path, protocol.Bytes16{20})
	if resp.StatusCode != 200 {
		t.Fatal(resp.StatusCode)
	}
	buyer := h.w.Fake.As(h.w.BuyerKey.Address())
	pur, _ := buyer.GetPurchase(ctx, p.nonce)
	h.w.Fake.MineTo(pur.ResponseDue + 1)
	if _, err := buyer.Dispute(ctx, p.nonce, chain.TriggerNonDelivery, protocol.Receipt{}, nil); err != nil {
		t.Fatal(err)
	}
	h.restart() // the seller restarts while the case is open
	if err := h.s.Tick(ctx); err != nil {
		t.Fatal(err)
	}
	cs, _ := buyer.GetCase(ctx, p.nonce)
	if cs.State != chain.CaseServeConfirm {
		t.Fatalf("case state %d", cs.State)
	}
	stranger, _ := ethkey.ParsePrivateKey("0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d")
	if _, code := h.fetchBundle(p.nonce, h.serveAuth(p.nonce, stranger, x402.RoleBuyer)); code != http.StatusUnauthorized {
		t.Fatalf("stranger got %d", code)
	}
	if _, code := h.fetchBundle(protocol.Bytes32{0xff}, h.serveAuth(p.nonce, h.w.BuyerKey, x402.RoleBuyer)); code != http.StatusNotFound {
		t.Fatalf("unknown nonce got %d", code)
	}
	if _, code := h.fetchBundle(p.nonce, "not base64"); code != http.StatusBadRequest {
		t.Fatalf("malformed authorization got %d", code)
	}
	if r, err := http.Get(h.srv.URL + "/fairbind/serve/0x12"); err != nil || r.StatusCode != http.StatusBadRequest {
		t.Fatalf("invalid nonce: %v", err)
	}
	// The claims document hashes to the claimsHash the purchase commits to.
	cr, err := http.Get(h.srv.URL + "/fairbind/claims")
	if err != nil || cr.StatusCode != 200 {
		t.Fatalf("claims: %v", err)
	}
	claims, _ := io.ReadAll(cr.Body)
	if protocol.Keccak256(claims) != protocol.Bytes32(pur.ClaimsHash) {
		t.Fatal("claims document does not hash to the on-chain claimsHash")
	}
	tampered := h.serveAuth(p.nonce, h.w.BuyerKey, x402.RoleBuyer)
	raw, _ := base64.StdEncoding.DecodeString(tampered)
	var a x402.ServeAuthorization
	if err := json.Unmarshal(raw, &a); err != nil {
		t.Fatal(err)
	}
	sig, _ := x402.ParseHex(a.Signature)
	sig[10] ^= 0xff // still valid hex, but the signature no longer verifies
	a.Signature = x402.Hex(sig)
	raw2, _ := json.Marshal(a)
	if _, code := h.fetchBundle(p.nonce, base64.StdEncoding.EncodeToString(raw2)); code != http.StatusUnauthorized {
		t.Fatalf("corrupted signature got %d", code)
	}
	b, code := h.fetchBundle(p.nonce, h.serveAuth(p.nonce, h.w.BuyerKey, x402.RoleBuyer))
	if code != 200 || b.ComputeHash() != cs.BundleHash || !bytes.Equal(b.ResponseBody, body) {
		t.Fatalf("bundle %d", code)
	}
	if _, err := buyer.Escalate(ctx, p.nonce); err != nil {
		t.Fatal(err)
	}
	if err := h.s.Tick(ctx); err != nil {
		t.Fatal(err)
	}
	cs, _ = buyer.GetCase(ctx, p.nonce)
	pub, _ := buyer.Publication(ctx, p.nonce)
	if cs.State != chain.CaseDelivered || pub == nil || !bytes.Equal(pub.Body, body) {
		t.Fatalf("after publication: state %d", cs.State)
	}
	if want := (len(body) + protocol.ResponseChunkBytes - 1) / protocol.ResponseChunkBytes; want > 1 && h.w.Fake.Calls("PublishChunk") != want {
		t.Fatalf("chunks published %d, want %d", h.w.Fake.Calls("PublishChunk"), want)
	}
}

func TestServeAndSingleCallPublication(t *testing.T) { testServeAndPublish(t, "/v1/quote") }
func TestServeAndChunkedPublication(t *testing.T)    { testServeAndPublish(t, "/v1/large") }

func TestDataDirectoryIsExclusive(t *testing.T) {
	h := newHarness(t)
	if _, err := fsstore.Open(h.dir); err == nil {
		t.Fatal("second process could open the data directory")
	}
}
