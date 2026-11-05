package chain

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"strings"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
)

func TestSignaturesExistInDeploymentABI(t *testing.T) {
	raw, err := os.ReadFile("../../../../test-vectors/deployment/monolith-abi.json")
	if err != nil {
		t.Fatal(err)
	}
	var abi []struct {
		Type, Name string
		Inputs     []json.RawMessage
	}
	json.Unmarshal(raw, &abi)
	type param struct {
		Type       string
		Components []json.RawMessage
	}
	var typ func(json.RawMessage) string
	typ = func(m json.RawMessage) string {
		var p param
		json.Unmarshal(m, &p)
		if strings.HasPrefix(p.Type, "tuple") {
			var parts []string
			for _, c := range p.Components {
				parts = append(parts, typ(c))
			}
			return "(" + strings.Join(parts, ",") + ")" + strings.TrimPrefix(p.Type, "tuple")
		}
		return p.Type
	}
	have := map[string]bool{}
	for _, f := range abi {
		if f.Type != "function" && f.Type != "event" && f.Type != "error" {
			continue
		}
		var parts []string
		for _, in := range f.Inputs {
			parts = append(parts, typ(in))
		}
		have[f.Name+"("+strings.Join(parts, ",")+")"] = true
	}
	for _, s := range []string{sigSettle, sigAnchor, sigDispute, sigServed, sigAcceptServe, sigEscalate, sigFinalizeServed,
		sigTimeoutServe, sigPublish, sigBeginPublication, sigPublishChunk, sigFinalizePub, sigClaimRefund, sigClaimRefundRcpt,
		sigClaimEpochFail, sigGetServiceProfile, sigGetDeadlineConfig, sigGetSeller, sigQuoteSeller, sigGetPurchase,
		sigPurchaseByKey, sigPurchaseState, sigGetCase, sigGetAnchor, sigGetBond, sigGetVerifier, eventSettled} {
		if !have[s] {
			t.Errorf("%s is not in the deployment ABI", s)
		}
	}
	for _, n := range errorNames {
		// Listed in contract-interface-v1 section 13 but absent from the
		// deployment ABI.
		if n == "IneligibleVerifier" {
			continue
		}
		if !have[n+"()"] {
			t.Errorf("error %s is not in the deployment ABI", n)
		}
	}
}

func castCalldata(t *testing.T, args ...string) string {
	cast, err := exec.LookPath("cast") // cast from PATH
	if err != nil {
		t.Skip("cast not available")
	}
	out, err := exec.Command(cast, append([]string{"calldata"}, args...)...).CombinedOutput()
	if err != nil {
		t.Fatalf("cast calldata: %v %s", err, out)
	}
	return strings.TrimSpace(string(out))
}

func TestCalldataMatchesCast(t *testing.T) {
	h := func(b byte) Hash { return protocol.Keccak256([]byte{b}) }
	hb := func(b byte) []byte { x := h(b); return x[:] }
	hx := func(x Hash) string { return x402.H32(x).String() }
	rc := protocol.Receipt{Version: 1, SellerID: 7, ProfileID: 3, Nonce: h(1), RequestHash: h(2), ResponseHash: h(3),
		ClaimsHash: h(4), PredicateCommitment: h(5), Epoch: 14, IssuedAt: 1788480000}
	rcText := "(1,7,3," + hx(h(1)) + "," + hx(h(2)) + "," + hx(h(3)) + "," + hx(h(4)) + "," + hx(h(5)) + ",14,1788480000)"
	sig := make([]byte, 65)
	sig[0], sig[64] = 0xaa, 27
	key := protocol.Bytes16{0, 0x11, 0x22}
	auth := x402.Authorization{From: x402.Addr{1}, To: x402.Addr{2}, Value: 10000, ValidAfter: 5, ValidBefore: 9, Nonce: x402.H32(h(1))}
	got := x402.Hex(call(sigSettle, st(u(7)), st(u(3)), st(hb(4)), st(b16Word(key)), st(hb(2)),
		st(aWord(Address(auth.From)), aWord(Address(auth.To)), u(10000), u(5), u(9), auth.Nonce[:]), dynBytes(sig)))
	want := castCalldata(t, sigSettle, "7", "3", hx(h(4)), x402.H16(key).String(), hx(h(2)),
		"("+auth.From.String()+","+auth.To.String()+",10000,5,9,"+hx(h(1))+")", x402.Hex(sig))
	if got != want {
		t.Fatalf("settle\n got %s\nwant %s", got, want)
	}
	req := x402.CanonicalRequest{Method: []byte("GET"), Path: []byte("/v1/quote"), Query: []byte("a=1"), HeaderBlock: []byte("accept:x\n"), Body: nil}
	body := []byte(strings.Repeat("z", 70))
	got = x402.Hex(call(sigPublish, st(hb(1)), st(b16Word(key)), requestArg(req), dynBytes(body), receiptArg(rc), dynBytes(sig)))
	want = castCalldata(t, sigPublish, hx(h(1)), x402.H16(key).String(),
		"("+x402.Hex(req.Method)+","+x402.Hex(req.Path)+","+x402.Hex(req.Query)+","+x402.Hex(req.HeaderBlock)+",0x)",
		x402.Hex(body), rcText, x402.Hex(sig))
	if got != want {
		t.Fatalf("publish\n got %s\nwant %s", got, want)
	}
	proof := protocol.ReceiptProof{Index: 1, Count: 3, Siblings: []protocol.Bytes32{h(8), h(9)}}
	got = x402.Hex(call(sigClaimRefundRcpt, st(hb(1)), receiptArg(rc), dynBytes(sig), proofArg(proof)))
	want = castCalldata(t, sigClaimRefundRcpt, hx(h(1)), rcText, x402.Hex(sig), "(1,3,["+hx(h(8))+","+hx(h(9))+"])")
	if got != want {
		t.Fatalf("claimRefund\n got %s\nwant %s", got, want)
	}
	got = x402.Hex(call(sigDispute, st(hb(1)), st(u(2)), receiptArg(protocol.Receipt{}), dynBytes(nil)))
	z := hx(Hash{})
	want = castCalldata(t, sigDispute, hx(h(1)), "2", "(0,0,0,"+z+","+z+","+z+","+z+","+z+",0,0)", "0x")
	if got != want {
		t.Fatalf("dispute\n got %s\nwant %s", got, want)
	}
}

// stubNode answers JSON-RPC with a handler per method.
func stubNode(t *testing.T, handle func(method string, params []json.RawMessage) (any, *rpcError)) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		var req struct {
			ID     uint64
			Method string
			Params []json.RawMessage
		}
		json.Unmarshal(raw, &req)
		res, e := handle(req.Method, req.Params)
		out := map[string]any{"jsonrpc": "2.0", "id": req.ID}
		if e != nil {
			out["error"] = e
		} else {
			out["result"] = res
		}
		json.NewEncoder(w).Encode(out)
	}))
}

func TestRPCViewDecodingAndRevertNames(t *testing.T) {
	nonce := protocol.Keccak256([]byte("n"))
	var sent int
	srv := stubNode(t, func(method string, params []json.RawMessage) (any, *rpcError) {
		switch method {
		case "eth_chainId":
			return "0x7a69", nil
		case "eth_call":
			var msg struct{ Data string }
			json.Unmarshal(params[0], &msg)
			data, _ := x402.ParseHex(msg.Data)
			switch x402.Hex(data[:4]) {
			case x402.Hex(selector(sigGetPurchase)):
				var ret []byte
				ret = append(ret, nonce[:]...)
				ret = append(ret, make([]byte, 32)...)
				for _, v := range []uint64{7, 3} {
					ret = append(ret, u(v)...)
				}
				ret = append(ret, aWord(Address{9})...)
				ret = append(ret, u(10000)...)
				ret = append(ret, make([]byte, 64)...)
				for _, v := range []uint64{14, 100, 160, 1960, 30000, 22100, 1} {
					ret = append(ret, u(v)...)
				}
				return x402.Hex(ret), nil
			case x402.Hex(selector(sigSettle)):
				d := x402.Hex(selector("KeyAlreadyUsed()"))
				raw, _ := json.Marshal(d)
				return nil, &rpcError{Code: 3, Message: "execution reverted", Data: raw}
			case x402.Hex(selector(sigAcceptServe)):
				return "0x", nil
			}
			return nil, &rpcError{Code: -32000, Message: "unexpected call"}
		case "eth_sendTransaction":
			sent++
			return x402.H32(protocol.Keccak256([]byte("tx"))).String(), nil
		case "eth_getTransactionReceipt":
			return map[string]string{"status": "0x1"}, nil
		}
		return nil, &rpcError{Code: -32601, Message: "no method " + method}
	})
	defer srv.Close()
	ctx := context.Background()
	if _, err := NewRPC(ctx, RPCConfig{URL: srv.URL, ChainID: 1}); err == nil {
		t.Fatal("wrong chain ID accepted")
	}
	c, err := NewRPC(ctx, RPCConfig{URL: srv.URL, ChainID: 31337})
	if err != nil {
		t.Fatal(err)
	}
	p, err := c.GetPurchase(ctx, nonce)
	if err != nil || p.Nonce != nonce || p.SellerID != 7 || p.Value != 10000 || p.Epoch != 14 || p.ClaimUntil != 1960 || p.FinancialState != 1 || p.Buyer != (Address{9}) {
		t.Fatalf("decoded %+v %v", p, err)
	}
	if _, err := c.Settle(ctx, Settlement{}); !IsRevert(err, "KeyAlreadyUsed") {
		t.Fatalf("revert name: %v", err)
	}
	if sent != 0 {
		t.Fatal("a reverting call was submitted")
	}
	if _, err := c.AcceptServe(ctx, nonce); err != nil || sent != 1 {
		t.Fatalf("send: %v sent=%d", err, sent)
	}
}
