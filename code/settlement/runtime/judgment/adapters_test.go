package judgment

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/verifier"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoopbackRelayAndChainGuard(t *testing.T) {
	calls := 0
	chain := "0x7a69"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Method string
			Params []json.RawMessage
		}
		json.NewDecoder(r.Body).Decode(&req)
		value := chain
		if req.Method == "eth_sendTransaction" {
			calls++
			value = "0x" + strings.Repeat("1", 64)
			var tx map[string]string
			json.Unmarshal(req.Params[0], &tx)
			if tx["data"] != "0x0102" {
				t.Error("wrong calldata")
			}
		}
		json.NewEncoder(w).Encode(map[string]any{"jsonrpc": "2.0", "id": 1, "result": value})
	}))
	defer server.Close()
	relay := LocalRelay{URL: server.URL, ChainID: 31337, Contract: protocol.Address{1}, From: protocol.Address{2}, Gas: 1000000}
	if _, e := relay.Send(context.Background(), relay.Contract, []byte{1, 2}); e != nil || calls != 1 {
		t.Fatal(e)
	}
	chain = "0x1"
	if _, e := relay.Send(context.Background(), relay.Contract, []byte{1, 2}); e == nil || calls != 1 {
		t.Fatal("chain mismatch sent")
	}
	relay.URL = "https://example.com"
	if _, e := relay.Send(context.Background(), relay.Contract, nil); e == nil {
		t.Fatal("remote relay")
	}
}
func TestKeystoreSignerMissingConfiguration(t *testing.T) {
	if _, e := (KeystoreSigner{}).SignDigest(context.Background(), protocol.Bytes32{}); e == nil {
		t.Fatal("missing signer accepted")
	}
}

func TestEncryptedFixtureKeystoreSigning(t *testing.T) {
	dir := t.TempDir()
	cmd := exec.Command("cast", "wallet", "import", "fixture", "--keystore-dir", dir, "--private-key", "0x"+strings.Repeat("0", 63)+"1", "--unsafe-password", "public-fixture-only")
	if _, e := cmd.Output(); e != nil {
		t.Fatal("test key import failed", e)
	}
	pw := filepath.Join(dir, "password")
	if e := os.WriteFile(pw, []byte("public-fixture-only"), 0600); e != nil {
		t.Fatal(e)
	}
	signer := KeystoreSigner{CastPath: "cast", KeystorePath: filepath.Join(dir, "fixture"), PasswordFile: pw}
	h := protocol.Keccak256([]byte("verdict fixture"))
	sig, e := signer.SignDigest(context.Background(), h)
	if e != nil {
		t.Fatal(e)
	}
	b, _ := hex.DecodeString("7e5f4552091a69125d5dfcb7b8c2659029395bdf")
	key, _ := protocol.ParseAddress(b)
	if e = (verifier.CastVerifier{}).Verify(context.Background(), key, h, sig); e != nil {
		t.Fatal(e)
	}
}
