package ledger

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"example.org/fairbind/protocol"
)

func fixture(t *testing.T, mode string) (*Client, protocol.Bytes32, *int) {
	t.Helper()
	nonce := protocol.Keccak256([]byte("purchase"))
	blockHash := protocol.Keccak256([]byte("block"))
	claims := protocol.Keccak256([]byte("claims"))
	calls := 0
	blocks := 0
	words := func(n int) []protocol.Bytes32 { return make([]protocol.Bytes32, n) }
	p := words(15)
	p[0] = nonce
	p[2] = idArg(1)
	p[3] = idArg(2)
	p[4][31] = 3
	p[7] = claims
	p[13] = idArg(999)
	s := words(9)
	s[0] = idArg(1)
	s[1] = idArg(2)
	s[3][31] = 4
	s[4] = claims
	f := words(48)
	f[0] = idArg(2)
	f[1] = idArg(1)
	f[3] = idArg(1)
	f[18] = idArg(100)
	f[19] = idArg(200)
	f[20] = idArg(300)
	k := words(23)
	k[0] = nonce
	k[10] = idArg(500)
	k[12] = idArg(7)
	k[14] = idArg(2)
	k[15] = idArg(6)
	k[19] = idArg(1)
	k[20] = idArg(2)
	v := words(9)
	v[0] = idArg(7)
	v[2][31] = 9
	anchor := words(12)
	anchor[0] = claims
	anchor[9] = idArg(2)
	anchor[10] = idArg(1)
	if mode == "sample" {
		k[14] = idArg(1)
	}
	table := map[string][]protocol.Bytes32{}
	for sig, data := range map[string][]protocol.Bytes32{"getPurchase(bytes32)": p, "getSeller(uint32)": s, "getServiceProfile(uint32)": f, "getCase(bytes32)": k, "getVerifier(uint32)": v, "getAnchor(uint32,uint24)": anchor} {
		h := protocol.Keccak256([]byte(sig))
		table["0x"+hex.EncodeToString(h[:4])] = data
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Method string            `json:"method"`
			Params []json.RawMessage `json:"params"`
		}
		if e := json.NewDecoder(r.Body).Decode(&req); e != nil {
			t.Error(e)
			return
		}
		var result any
		switch req.Method {
		case "eth_chainId":
			result = "0x1"
			if mode == "chain" {
				result = "0x2"
			}
		case "eth_getBlockByNumber":
			blocks++
			bh := hexHash(blockHash)
			if mode == "reorg" && blocks == 2 {
				bh = hexHash(nonce)
			}
			result = map[string]string{"number": "0x64", "hash": bh}
		case "eth_call":
			calls++
			var pin struct {
				BlockHash        string `json:"blockHash"`
				RequireCanonical bool   `json:"requireCanonical"`
			}
			json.Unmarshal(req.Params[1], &pin)
			if pin.BlockHash != hexHash(blockHash) || !pin.RequireCanonical {
				t.Error("call is not hash pinned")
			}
			var call map[string]string
			json.Unmarshal(req.Params[0], &call)
			if call["to"] != "0x0000000000000000000000000000000000000001" {
				t.Error("wrong allowlisted contract")
			}
			data := table[call["data"][:10]]
			raw := []byte{}
			for _, word := range data {
				raw = append(raw, word[:]...)
			}
			if mode == "truncate" {
				raw = raw[:len(raw)-1]
			}
			if mode == "width" {
				raw[64] = 1
			}
			if mode == "relationship" && calls == 2 {
				raw[31] = 9
			}
			result = "0x" + hex.EncodeToString(raw)
		default:
			t.Errorf("unexpected method %s", req.Method)
		}
		if mode == "rpcerror" {
			fmt.Fprint(w, `{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"unsupported finalized"}}`)
			return
		}
		if mode == "oversize" {
			fmt.Fprint(w, strings.Repeat(" ", 10000))
			return
		}
		if mode == "wrongid" {
			fmt.Fprint(w, `{"jsonrpc":"2.0","id":2,"result":"0x1"}`)
			return
		}
		json.NewEncoder(w).Encode(map[string]any{"jsonrpc": "2.0", "id": 1, "result": result})
	}))
	t.Cleanup(srv.Close)
	var contract protocol.Address
	contract[19] = 1
	c, e := New(Config{URL: srv.URL, ChainID: 1, Contract: contract, Timeout: time.Second, MaxResponseBytes: 4096, MaxClaimsBytes: 100})
	if e != nil {
		t.Fatal(e)
	}
	return c, nonce, &calls
}
func TestFinalizedAssignmentPinsEveryCall(t *testing.T) {
	c, n, calls := fixture(t, "")
	a, e := c.Read(context.Background(), n, ManifestBindings{})
	if e != nil {
		t.Fatal(e)
	}
	if *calls != 5 || a.Snapshot.SellerID != 1 || a.Snapshot.ProfileID != 2 || a.Snapshot.MaxRequestBytes != 100 || a.Snapshot.MaxResponseBytes != 200 || a.MaxEvidenceBytes != 300 || a.Stage != 1 || a.Attempt != 2 || a.VerifierID != 7 || a.VerifierKey[19] != 9 || a.Trigger != 2 || a.RetainUntil != 999 || a.BlockNumber != 100 {
		t.Fatalf("bad assignment %+v", a)
	}
}
func TestRejectUntrustedSnapshotResponses(t *testing.T) {
	for _, mode := range []string{"chain", "reorg", "truncate", "width", "relationship", "rpcerror", "oversize", "wrongid"} {
		t.Run(mode, func(t *testing.T) {
			c, n, _ := fixture(t, mode)
			if _, e := c.Read(context.Background(), n, ManifestBindings{}); e == nil {
				t.Fatal("accepted invalid snapshot")
			}
		})
	}
}
func TestRejectUnsafeConfiguration(t *testing.T) {
	for _, u := range []string{"http://example.com", "file:///tmp/rpc", "https://user:secret@example.com", "https://example.com/#fragment"} {
		if _, e := New(Config{URL: u}); e == nil {
			t.Fatal(u)
		}
	}
}

func TestSampleReadsPinnedAnchor(t *testing.T) {
	c, n, calls := fixture(t, "sample")
	a, e := c.Read(context.Background(), n, ManifestBindings{})
	if e != nil {
		t.Fatal(e)
	}
	if *calls != 6 || a.AnchorCount != 1 || a.AnchorRoot == (protocol.Bytes32{}) {
		t.Fatal("missing anchor")
	}
}

func TestCanceledReadFails(t *testing.T) {
	c, n, _ := fixture(t, "")
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, e := c.Read(ctx, n, ManifestBindings{}); e == nil {
		t.Fatal("canceled context accepted")
	}
}
