package facilitator

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/fsstore"
	"example.org/fairbind/services/internal/x402/testworld"
)

func open(t *testing.T, w *testworld.World, dir string) (*Facilitator, *fsstore.Store) {
	t.Helper()
	st, err := fsstore.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	f, err := New(Options{Network: "eip155:31337", TokenName: "MockUSDC", TokenVersion: "2",
		SettlementSchema: testworld.Schema("fairbind-settlement-v1.schema.json"), Now: w.Fake.Time, Token: testworld.Token},
		w.Fake.As(testworld.Facilitator), st)
	if err != nil {
		t.Fatal(err)
	}
	return f, st
}

var ctx = context.Background()

func TestSettleAndIdempotentRetry(t *testing.T) {
	w := testworld.New()
	f, _ := open(t, w, t.TempDir())
	req := w.SettleRequest(w.BuyerKey, protocol.Bytes16{1}, protocol.Keccak256([]byte("req")))
	resp, bad := f.Settle(ctx, req)
	if bad != nil {
		t.Fatal(bad)
	}
	info := resp.Extensions[x402.ExtensionKey].Info
	if !resp.Success || info.Purchase != req.PaymentPayload.Payload.Authorization.Nonce || info.FinancialState != "DEFERRED" || info.SellerID != testworld.SellerID {
		t.Fatalf("response %+v", resp)
	}
	again, bad := f.Settle(ctx, req)
	if bad != nil || again.Extensions[x402.ExtensionKey].Info != info || again.Transaction != resp.Transaction {
		t.Fatalf("retry %+v %v", again, bad)
	}
	if n := w.Fake.Calls("Settle"); n != 1 {
		t.Fatalf("settle submitted %d times", n)
	}
}

func TestLostResponseAndRestartRecovery(t *testing.T) {
	w := testworld.New()
	dir := t.TempDir()
	f, st := open(t, w, dir)
	req := w.SettleRequest(w.BuyerKey, protocol.Bytes16{2}, protocol.Keccak256([]byte("req")))
	w.Fake.Inject("Settle", chain.LoseAfter)
	if _, bad := f.Settle(ctx, req); bad == nil || bad.Status != http.StatusInternalServerError {
		t.Fatalf("lost response not reported as uncertain: %v", bad)
	}
	st.Close() // process dies
	f2, _ := open(t, w, dir)
	if n, err := f2.Recover(ctx); err != nil || n != 1 {
		t.Fatalf("recover %d %v", n, err)
	}
	resp, bad := f2.Settle(ctx, req)
	if bad != nil || !resp.Success {
		t.Fatal(bad)
	}
	if n := w.Fake.Calls("Settle"); n != 1 {
		t.Fatalf("settle submitted %d times", n)
	}
	nonce := protocol.Bytes32(req.PaymentPayload.Payload.Authorization.Nonce)
	a, _ := f2.attempt(nonce)
	if a.Status != StatusConfirmed {
		t.Fatalf("attempt %+v", a)
	}
}

func TestRejectedThenNewAuthorization(t *testing.T) {
	w := testworld.New()
	f, _ := open(t, w, t.TempDir())
	w.Fake.AddSeller(chain.Seller{SellerID: testworld.SellerID, ProfileID: testworld.ProfileID, Owner: testworld.SellerOwner,
		SigningKey: w.SellerKey.Address(), ClaimsHash: testworld.ClaimsHash, BondID: testworld.BondID, Status: 2})
	key, rh := protocol.Bytes16{3}, protocol.Keccak256([]byte("req"))
	req := w.SettleRequest(w.BuyerKey, key, rh)
	if _, bad := f.Settle(ctx, req); bad == nil || bad.Reason != x402.ErrSellerInactive {
		t.Fatalf("got %v", bad)
	}
	w.Fake.AddSeller(chain.Seller{SellerID: testworld.SellerID, ProfileID: testworld.ProfileID, Owner: testworld.SellerOwner,
		SigningKey: w.SellerKey.Address(), ClaimsHash: testworld.ClaimsHash, BondID: testworld.BondID, Status: chain.SellerActive})
	w.Fake.Mine(5) // new validity window, same purchase nonce
	req2 := w.SettleRequest(w.BuyerKey, key, rh)
	if resp, bad := f.Settle(ctx, req2); bad != nil || !resp.Success {
		t.Fatalf("new authorization after final revert: %v", bad)
	}
}

func TestKeyConflictAndStatelessRejections(t *testing.T) {
	w := testworld.New()
	f, _ := open(t, w, t.TempDir())
	key := protocol.Bytes16{4}
	if _, bad := f.Settle(ctx, w.SettleRequest(w.BuyerKey, key, protocol.Keccak256([]byte("a")))); bad != nil {
		t.Fatal(bad)
	}
	if _, bad := f.Settle(ctx, w.SettleRequest(w.BuyerKey, key, protocol.Keccak256([]byte("b")))); bad == nil || bad.Reason != x402.ErrKeyConflict {
		t.Fatalf("got %v", bad)
	}
	req := w.SettleRequest(w.BuyerKey, protocol.Bytes16{5}, protocol.Keccak256([]byte("c")))
	req.PaymentPayload.Payload.Authorization.Nonce[0] ^= 1
	if _, bad := f.Settle(ctx, req); bad == nil || bad.Reason != x402.ErrNonceMismatch {
		t.Fatalf("got %v", bad)
	}
	req = w.SettleRequest(w.BuyerKey, protocol.Bytes16{5}, protocol.Keccak256([]byte("c")))
	req.PaymentPayload.Payload.Authorization.ValidBefore = 1
	if _, bad := f.Settle(ctx, req); bad == nil || bad.Status != http.StatusBadRequest {
		t.Fatalf("got %v", bad)
	}
	req = w.SettleRequest(w.BuyerKey, protocol.Bytes16{5}, protocol.Keccak256([]byte("c")))
	sig, _ := x402.ParseHex(req.PaymentPayload.Payload.Signature)
	sig[3] ^= 1
	req.PaymentPayload.Payload.Signature = x402.Hex(sig)
	if _, bad := f.Settle(ctx, req); bad == nil || bad.Reason != "invalid_payload" {
		t.Fatalf("got %v", bad)
	}
	req = w.SettleRequest(w.BuyerKey, protocol.Bytes16{5}, protocol.Keccak256([]byte("c")))
	req.PaymentRequirements.PayTo = x402.Addr{1}
	req.PaymentPayload.Accepted.PayTo = x402.Addr{1}
	if _, bad := f.Settle(ctx, req); bad == nil || bad.Status != http.StatusBadRequest {
		t.Fatalf("got %v", bad)
	}
	req = w.SettleRequest(w.BuyerKey, protocol.Bytes16{5}, protocol.Keccak256([]byte("c")))
	req.PaymentRequirements.Asset = x402.Addr{9}
	req.PaymentPayload.Accepted.Asset = x402.Addr{9}
	if _, bad := f.Settle(ctx, req); bad == nil || bad.Status != http.StatusBadRequest {
		t.Fatalf("got %v", bad)
	}
	if n := w.Fake.Calls("Settle"); n != 1 { // the conflict is found by reconciliation before submission
		t.Fatalf("settle calls %d", n)
	}
}

func TestHTTPHandler(t *testing.T) {
	w := testworld.New()
	f, _ := open(t, w, t.TempDir())
	srv := httptest.NewServer(f.Handler())
	defer srv.Close()
	r, err := http.Get(srv.URL + "/supported")
	if err != nil || r.StatusCode != 200 {
		t.Fatal(err)
	}
	var sup x402.Supported
	json.NewDecoder(r.Body).Decode(&sup)
	if len(sup.Kinds) != 1 || sup.Kinds[0].Extra["assetTransferMethod"] != x402.AssetTransferMethod {
		t.Fatalf("%+v", sup)
	}
	body, _ := json.Marshal(w.SettleRequest(w.BuyerKey, protocol.Bytes16{6}, protocol.Keccak256([]byte("h"))))
	r, err = http.Post(srv.URL+"/settle", "application/json", bytes.NewReader(body))
	if err != nil || r.StatusCode != 200 {
		t.Fatal(err, r.StatusCode)
	}
	var sr x402.SettlementResponse
	if err = json.NewDecoder(r.Body).Decode(&sr); err != nil || !sr.Success {
		t.Fatalf("%+v %v", sr, err)
	}
	r, _ = http.Post(srv.URL+"/settle", "application/json", bytes.NewReader([]byte(`{"x402Version":2,"bogus":1}`)))
	if r.StatusCode != http.StatusBadRequest {
		t.Fatal(r.StatusCode)
	}
}
