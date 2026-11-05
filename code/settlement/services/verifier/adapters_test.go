package verifier

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"example.org/fairbind/protocol"
	gate "example.org/fairbind/runtime/verifier"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/ethkey"
)

// fakeCaseReader answers GetCase with a fixed view, for HTTPSeller tests.
type fakeCaseReader struct{ c chain.Case }

func (f fakeCaseReader) GetCase(context.Context, protocol.Bytes32) (chain.Case, error) {
	return f.c, nil
}

func TestBundleRoundTripAndHashCheck(t *testing.T) {
	e := newEnv(t)
	s := e.bound()
	proof := &protocol.ReceiptProof{Index: 1, Count: 2, Siblings: []protocol.Bytes32{{3}}}
	raw, err := EncodeBundle(s.ChainID, s.Contract, e.seller.b, proof)
	if err != nil {
		t.Fatal(err)
	}
	b, p, err := DecodeBundle(raw, s.ChainID, s.Contract)
	if err != nil {
		t.Fatal(err)
	}
	b.Claims = e.seller.b.Claims
	if g := gate.Check(context.Background(), s, b, gate.CastVerifier{}); g.Status != gate.Ready {
		t.Fatal("decoded bundle not authenticated:", g.Reason)
	}
	if p.Index != 1 || p.Count != 2 || len(p.Siblings) != 1 || p.Siblings[0] != (protocol.Bytes32{3}) {
		t.Fatal("proof", p)
	}
	if _, _, err = DecodeBundle(raw, s.ChainID+1, s.Contract); err == nil {
		t.Fatal("accepted another chain")
	}
	var m map[string]any
	json.Unmarshal(raw, &m)
	m["idempotencyKey"] = "0x" + strings.Repeat("06", 16) // bundle hash no longer matches
	bad, _ := json.Marshal(m)
	if _, _, err = DecodeBundle(bad, s.ChainID, s.Contract); err == nil || !strings.Contains(err.Error(), "bundle hash") {
		t.Fatal("accepted altered bundle:", err)
	}
	// The body is covered by the signed responseHash, which the gate checks.
	m["idempotencyKey"] = "0x" + strings.Repeat("05", 1) + strings.Repeat("00", 15)
	m["responseBody"] = "e30="
	bad, _ = json.Marshal(m)
	altered, _, err := DecodeBundle(bad, s.ChainID, s.Contract)
	if err != nil {
		t.Fatal(err)
	}
	altered.Claims = e.seller.b.Claims
	if g := gate.Check(context.Background(), s, altered, gate.CastVerifier{}); g.Status != gate.Inconclusive || g.Reason != "response_binding" {
		t.Fatal("altered body passed the gate:", g)
	}
	delete(m, "responseBody")
	m["extra"] = 1
	bad, _ = json.Marshal(m)
	if _, _, err = DecodeBundle(bad, s.ChainID, s.Contract); err == nil {
		t.Fatal("accepted unknown field")
	}
	noProof, _ := EncodeBundle(s.ChainID, s.Contract, e.seller.b, nil)
	if !bytes.Contains(noProof, []byte(`"receiptProof":null`)) {
		t.Fatal("absent proof not encoded as null")
	}
}

func TestHTTPSellerRedelivery(t *testing.T) {
	e := newEnv(t)
	s := e.bound()
	raw, err := EncodeBundle(s.ChainID, s.Contract, e.seller.b, nil)
	if err != nil {
		t.Fatal(err)
	}
	var gotAuth, gotPath string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.Method == http.MethodGet && r.URL.Path == "/fairbind/serve/"+hx(s.Nonce):
			gotAuth, gotPath = r.Header.Get(x402.HeaderServeAuth), r.URL.Path
			w.Write(raw)
		case r.Method == http.MethodGet && r.URL.Path == "/fairbind/claims":
			w.Write(e.seller.b.Claims)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	seller := HTTPSeller{ChainID: s.ChainID, Contract: s.Contract, Endpoints: map[uint32]string{7: srv.URL + "/"},
		Cases: fakeCaseReader{c: chain.Case{CaseOpenedBlock: 5}}, Signer: testKeySigner{}}
	b, _, err := seller.Redeliver(context.Background(), e.a)
	if err != nil {
		t.Fatal(err)
	}
	if gotPath != "/fairbind/serve/"+hx(s.Nonce) {
		t.Fatal("wrong redelivery path", gotPath)
	}
	if gotAuth == "" {
		t.Fatal("no serve authorization header sent")
	}
	authRaw, err := base64.StdEncoding.DecodeString(gotAuth)
	if err != nil {
		t.Fatal(err)
	}
	var a x402.ServeAuthorization
	if err = x402.DecodeStrict(authRaw, &a); err != nil {
		t.Fatal(err)
	}
	if a.Role != x402.RoleVerifier || a.CaseOpenedBlock != 5 || a.ValidUntil != e.a.JudgeDue {
		t.Fatalf("authorization %+v", a)
	}
	sig, err := x402.ParseHex(a.Signature)
	if err != nil {
		t.Fatal(err)
	}
	digest := x402.ServeAuthDigest(s.ChainID, s.Contract, s.Nonce, x402.RoleVerifier, a.CaseOpenedBlock, a.ValidUntil)
	signerKey, _ := ethkey.ParsePrivateKey("0x" + strings.Repeat("0", 63) + "1")
	if err = ethkey.Verify(signerKey.Address(), digest, sig); err != nil {
		t.Fatal("authorization signature does not verify:", err)
	}
	if g := gate.Check(context.Background(), s, b, gate.CastVerifier{}); g.Status != gate.Ready {
		t.Fatal(g.Reason)
	}
	seller.MaxBytes = 10
	if _, _, err = seller.Redeliver(context.Background(), e.a); err == nil {
		t.Fatal("oversize response accepted")
	}
	seller.Endpoints = map[uint32]string{7: "http://example.com"}
	if _, _, err = seller.Redeliver(context.Background(), e.a); err == nil {
		t.Fatal("plain HTTP to a non-loopback host accepted")
	}
}

func TestRPCChainQueries(t *testing.T) {
	nonce := protocol.Bytes32{0xaa}
	contract := protocol.Address{1}
	evidenceHash := protocol.Bytes32{0xee}
	var filters []map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Method string           `json:"method"`
			Params []map[string]any `json:"params"`
		}
		body, _ := io.ReadAll(r.Body)
		json.Unmarshal(body, &req)
		var result any
		switch req.Method {
		case "eth_chainId":
			result = "0x7a69"
		case "eth_blockNumber":
			result = "0x20"
		case "eth_getBlockByNumber":
			result = map[string]string{"number": "0x10"}
		case "eth_getTransactionReceipt":
			result = map[string]string{"status": "0x0", "blockNumber": "0x11"}
		case "eth_getLogs":
			f := req.Params[0]
			filters = append(filters, f)
			topics := f["topics"].([]any)
			addr := fmt.Sprintf("0x%x", contract)
			if topics[0] == hx(VerifierAssignedTopic) {
				result = []map[string]any{
					{"address": addr, "topics": []string{hx(VerifierAssignedTopic), hx(nonce), topicUint(3)}, "data": "0x"},
					{"address": addr, "topics": []string{hx(VerifierAssignedTopic), hx(nonce), topicUint(3)}, "data": "0x", "removed": true},
				}
			} else {
				data := "0x" + strings.TrimPrefix(topicUint(2), "0x") + strings.TrimPrefix(topicUint(1), "0x") + strings.TrimPrefix(hx(evidenceHash), "0x")
				result = []map[string]any{{"address": addr, "topics": []string{hx(VerdictSubmittedTopic), hx(nonce), topicUint(3)}, "data": data}}
			}
		}
		json.NewEncoder(w).Encode(map[string]any{"jsonrpc": "2.0", "id": 1, "result": result})
	}))
	defer srv.Close()
	c, err := NewRPC(srv.URL, 31337, contract, 4, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	if n, err := c.BlockNumber(ctx); err != nil || n != 32 {
		t.Fatal(n, err)
	}
	if n, err := c.FinalizedBlock(ctx); err != nil || n != 16 {
		t.Fatal(n, err)
	}
	nonces, err := c.AssignedNonces(ctx, 3, 1, 10)
	if err != nil || len(nonces) != 3 || nonces[0] != nonce {
		t.Fatal("chunked scan should return one live log per chunk", nonces, err)
	}
	if len(filters) != 3 || filters[0]["fromBlock"] != "0x1" || filters[0]["toBlock"] != "0x4" || filters[2]["toBlock"] != "0xa" {
		t.Fatal("chunking", filters)
	}
	if ok, err := c.VerdictRecorded(ctx, nonce, 3, 2, evidenceHash, 1, 2); err != nil || !ok {
		t.Fatal("verdict not found", err)
	}
	if ok, _ := c.VerdictRecorded(ctx, nonce, 3, 1, evidenceHash, 1, 2); ok {
		t.Fatal("matched wrong stage")
	}
	if ok, _ := c.VerdictRecorded(ctx, nonce, 3, 2, protocol.Bytes32{1}, 1, 2); ok {
		t.Fatal("matched wrong evidence")
	}
	if st, err := c.TxStatus(ctx, protocol.Bytes32{9}); err != nil || !st.Found || st.Success || st.Block != 17 {
		t.Fatal(st, err)
	}
	wrong, _ := NewRPC(srv.URL, 1, contract, 4, time.Second)
	if _, err = wrong.BlockNumber(ctx); err == nil {
		t.Fatal("chain mismatch accepted")
	}
}

func TestConfigParsing(t *testing.T) {
	good := `{"rpcUrl":"http://127.0.0.1:8545","chainId":31337,"contract":"0x0100000000000000000000000000000000000000","verifierId":3,
"keystore":"/k","passwordFile":"/p","castPath":"/c","stateDir":"/s","pollIntervalSeconds":6,"startBlock":0,"submitMarginBlocks":2,
"relay":{"from":"0x0200000000000000000000000000000000000000","gas":3000000},"sellers":{"7":"https://seller.example"},
"profiles":{"4":{"sourceSetHash":"0x` + strings.Repeat("11", 32) + `","tolerancePolicyHash":"0x` + strings.Repeat("22", 32) + `"}}}`
	p, err := ParseConfig([]byte(good))
	if err != nil {
		t.Fatal(err)
	}
	if p.Poll != 6*time.Second || p.SellerURLs[7] != "https://seller.example" || p.Bindings[4].SourceSetHash[31] != 0x11 || p.Bindings[4].TolerancePolicyHash[0] != 0x22 || p.Relay.URL != p.RPCURL || p.MaxLogRange != 2000 {
		t.Fatalf("%+v", p)
	}
	for _, bad := range []string{
		strings.Replace(good, `"verifierId":3`, `"verifierId":0`, 1),
		strings.Replace(good, `http://127.0.0.1:8545`, `http://10.0.0.1:8545`, 1),
		strings.Replace(good, `"pollIntervalSeconds":6`, `"pollIntervalSeconds":0`, 1),
		strings.Replace(good, `"sellers":{"7"`, `"sellers":{"x"`, 1),
		strings.Replace(good, `"startBlock":0`, `"startBlock":0,"unknown":1`, 1),
		strings.Replace(good, `"gas":3000000`, `"gas":0`, 1),
	} {
		if _, err := ParseConfig([]byte(bad)); err == nil {
			t.Fatal("accepted", bad)
		}
	}
}
