package keeper

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"example.org/fairbind/protocol"
)

func words(ws ...[]byte) string {
	var b strings.Builder
	b.WriteString("0x")
	for _, w := range ws {
		b.WriteString(hex.EncodeToString(w))
	}
	return b.String()
}

func zeros(n int) [][]byte {
	out := make([][]byte, n)
	for i := range out {
		out[i] = make([]byte, 32)
	}
	return out
}

func TestRPCReadsPinnedViewsAndLogs(t *testing.T) {
	nonce := nonceOf("a")
	blockHash := protocol.Keccak256([]byte("block"))
	sel := func(sig string) string { h := protocol.Keccak256([]byte(sig)); return hex.EncodeToString(h[:4]) }
	purchase := zeros(15)
	purchase[0] = nonce[:]
	purchase[11], purchase[12], purchase[13], purchase[14] = word(3000), word(4000), word(4100), word(1)
	caseWords := zeros(23)
	caseWords[0] = nonce[:]
	caseWords[10], caseWords[12], caseWords[15], caseWords[19] = word(3500), word(7), word(uint64(caseJudging)), word(1)
	profile := zeros(48)
	profile[0], profile[6], profile[7], profile[36], profile[45] = word(3), word(1000), word(300), word(9), word(1)
	deadlines := zeros(9)
	deadlines[0], deadlines[2] = word(100), word(200)
	anchor := zeros(12)
	anchor[6], anchor[7], anchor[11] = word(2469), word(2669), word(2)
	bond := zeros(25)
	bond[17], bond[18], bond[22] = word(4500), word(6000), word(2)
	views := map[string]string{
		sel("getPurchase(bytes32)"):      words(purchase...),
		sel("getCase(bytes32)"):          words(caseWords...),
		sel("getServiceProfile(uint32)"): words(profile...),
		sel("getDeadlineConfig(uint32)"): words(deadlines...),
		sel("getAnchor(uint32,uint24)"):  words(anchor...),
		sel("getBond(uint32)"):           words(bond...),
		sel("purchaseState(bytes32)"):    words(word(1)),
		sel("isSampled(bytes32)"):        words(word(1), word(1)),
	}
	contract := protocol.Address{0x11}
	var latestCalls int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Method string            `json:"method"`
			Params []json.RawMessage `json:"params"`
		}
		json.NewDecoder(r.Body).Decode(&req)
		var result any
		switch req.Method {
		case "eth_chainId":
			result = "0x7a69"
		case "eth_getBlockByNumber":
			result = map[string]string{"number": "0x1388", "hash": hexKey(blockHash)}
		case "eth_getLogs":
			data := words(word(5), word(3), make([]byte, 32), word(10), word(0), make([]byte, 32), make([]byte, 32))
			result = []map[string]any{{"address": hexAddr(contract), "removed": false, "data": data,
				"topics": []string{hexKey(settledTopic), hexKey(nonce), hexKey(protocol.Bytes32{}), "0x" + hex.EncodeToString(word(1))}}}
		case "eth_call":
			var tx map[string]string
			json.Unmarshal(req.Params[0], &tx)
			if string(req.Params[1]) == `"latest"` {
				latestCalls++
				if tx["from"] == "" {
					t.Error("simulation without sender")
				}
				result = "0x"
				break
			}
			var pin map[string]any
			json.Unmarshal(req.Params[1], &pin)
			if pin["blockHash"] != hexKey(blockHash) || pin["requireCanonical"] != true {
				t.Errorf("unpinned call %s", req.Params[1])
			}
			result = views[tx["data"][2:10]]
		}
		json.NewEncoder(w).Encode(map[string]any{"jsonrpc": "2.0", "id": 1, "result": result})
	}))
	defer srv.Close()
	r, err := NewRPC(srv.URL, 31337, contract, protocol.Address{0x22}, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	head, err := r.Finalized(ctx)
	if err != nil || head.Number != 5000 || head.Hash != blockHash {
		t.Fatalf("head %+v %v", head, err)
	}
	logs, err := r.Settlements(ctx, 1, 10)
	if err != nil || len(logs) != 1 || logs[0] != (Settlement{Nonce: nonce, SellerID: 1, BondID: 5, ProfileID: 3, Epoch: 0}) {
		t.Fatalf("logs %+v %v", logs, err)
	}
	tm, err := r.Timing(ctx, head, 3)
	if err != nil || tm != (Timing{EpochOrigin: 1000, EpochBlocks: 300, AnchorBlocks: 100, OpenBlocks: 200, FreezeOnInitialFail: true}) {
		t.Fatalf("timing %+v %v", tm, err)
	}
	p, err := r.Purchase(ctx, head, nonce)
	if err != nil || p != (Purchase{ClaimUntil: 3000, ReleaseBlock: 4000, RetainUntil: 4100, FinancialState: 1}) {
		t.Fatalf("purchase %+v %v", p, err)
	}
	c, err := r.Case(ctx, head, nonce)
	if err != nil || c.State != caseJudging || c.JudgeDue != 3500 || c.AssignedVerifierID != 7 || c.Stage != 1 {
		t.Fatalf("case %+v %v", c, err)
	}
	a, err := r.Anchor(ctx, head, 1, 0)
	if err != nil || a != (Anchor{State: 2, RandomBlock: 2469, SealDeadline: 2669}) {
		t.Fatalf("anchor %+v %v", a, err)
	}
	b, err := r.Bond(ctx, head, 5)
	if err != nil || b != (Bond{FreezeState: 2, FreezeBlock: 4500, ClaimUntilBlock: 6000}) {
		t.Fatalf("bond %+v %v", b, err)
	}
	if e, k, err := r.Sampled(ctx, head, nonce); err != nil || !e || !k {
		t.Fatal("sampled")
	}
	if ps, err := r.PurchaseState(ctx, head, nonce); err != nil || ps != 1 {
		t.Fatal("purchase state")
	}
	if err := r.Simulate(ctx, []byte{1, 2, 3, 4}); err != nil || latestCalls != 1 {
		t.Fatalf("simulate %v", err)
	}
	if _, err := r.Purchase(ctx, head, nonceOf("other")); err == nil {
		t.Fatal("accepted a purchase view for another nonce")
	}
}

func TestRPCSurfacesRevert(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"jsonrpc":"2.0","id":1,"error":{"code":3,"message":"execution reverted"}}`))
	}))
	defer srv.Close()
	r, _ := NewRPC(srv.URL, 1, protocol.Address{1}, protocol.Address{2}, time.Second)
	if err := r.Simulate(context.Background(), []byte{0, 0, 0, 0}); err == nil || !strings.Contains(err.Error(), "reverted") {
		t.Fatalf("revert hidden: %v", err)
	}
}

func TestConfig(t *testing.T) {
	good := `{"rpcUrl":"http://127.0.0.1:8545","chainId":31337,"contract":"0x1111111111111111111111111111111111111111",
"from":"0x2222222222222222222222222222222222222222","gas":3000000,"stateFile":"k.json","pollIntervalMs":500,
"rpcTimeoutMs":5000,"maxLogRange":1000,"resendAfterBlocks":5,"actions":["timeoutServe"]}`
	c, err := ParseConfig([]byte(good))
	if err != nil || !c.EnabledActions()[ActTimeoutServe] || len(c.EnabledActions()) != 1 {
		t.Fatalf("config %+v %v", c, err)
	}
	for _, bad := range []string{
		strings.Replace(good, "http://127.0.0.1", "http://example.test", 1),
		strings.Replace(good, `"timeoutServe"`, `"judge"`, 1),
		strings.Replace(good, `"gas":3000000`, `"gas":0`, 1),
		strings.Replace(good, `"resendAfterBlocks":5`, `"resendAfterBlocks":0`, 1),
		strings.Replace(good, "0x1111111111111111111111111111111111111111", "0x0000000000000000000000000000000000000000", 1),
		strings.Replace(good, `"gas"`, `"extra":1,"gas"`, 1),
	} {
		if _, err := ParseConfig([]byte(bad)); err == nil {
			t.Fatalf("accepted %s", bad)
		}
	}
}
