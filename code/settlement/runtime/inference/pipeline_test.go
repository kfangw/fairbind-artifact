package inference

import (
	"context"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/verifier"
)

func word(t *testing.T, s string) protocol.Bytes32 {
	t.Helper()
	var h protocol.Bytes32
	b, err := hex.DecodeString(strings.TrimPrefix(s, "0x"))
	if err != nil || len(b) != 32 {
		t.Fatalf("invalid bytes32 %q", s)
	}
	copy(h[:], b)
	return h
}

func sign(t *testing.T, s verifier.Snapshot, b *verifier.Bundle) {
	t.Helper()
	digest := protocol.ReceiptDigest(s.ChainID, s.Contract, b.Receipt)
	out, err := exec.Command("cast", "wallet", "sign", "--no-hash", "--private-key", "0x"+strings.Repeat("0", 63)+"1", fmt.Sprintf("0x%x", digest)).Output()
	if err != nil {
		t.Fatal("public-fixture signing unavailable: ", err)
	}
	if b.Signature, err = hex.DecodeString(strings.TrimPrefix(strings.TrimSpace(string(out)), "0x")); err != nil {
		t.Fatal(err)
	}
}

// signed builds a class-2 snapshot and seller-signed bundle for the given
// preimage and bodies.
func signed(t *testing.T, pre verifier.Preimage, request, response []byte) (verifier.Snapshot, verifier.Bundle) {
	t.Helper()
	keyraw, _ := hex.DecodeString("7e5f4552091a69125d5dfcb7b8c2659029395bdf")
	key, _ := protocol.ParseAddress(keyraw)
	s := verifier.Snapshot{ChainID: 31337, Contract: protocol.Address{1}, Buyer: protocol.Address{2}, SellerKey: key, SellerID: 7, ProfileID: 5, ClassID: 2,
		PredicateID: PredicateID, CanonID: protocol.Keccak256([]byte("fairbind/http-canon/v1")), ModelHash: pre.ModelHash, ConfigHash: pre.ConfigHash,
		MaxRequestBytes: 65536, MaxResponseBytes: 1 << 20, MaxClaimsBytes: 65536}
	claims, _ := json.Marshal(map[string]any{"version": 1, "classId": 2, "predicateId": hex32(PredicateID), "modelHash": hex32(pre.ModelHash), "configHash": hex32(pre.ConfigHash)})
	s.ClaimsHash = protocol.Keccak256(claims)
	b := verifier.Bundle{Key: protocol.Bytes16{6}, Claims: claims, Response: response, Preimage: pre,
		Request: verifier.CanonicalRequest{Method: []byte("POST"), Path: []byte("/v1/generate"), Body: request}}
	s.RequestHash = verifier.RequestHash(b.Request, s.CanonID)
	s.KeyID = protocol.DeriveKeyID(s.ChainID, s.Contract, s.SellerID, s.Buyer, b.Key)
	s.Nonce = protocol.DeriveNonce(s.ChainID, s.Contract, s.SellerID, s.ProfileID, s.ClaimsHash, s.Buyer, b.Key, s.RequestHash)
	b.Receipt = protocol.Receipt{Version: 1, SellerID: s.SellerID, ProfileID: s.ProfileID, Nonce: s.Nonce, RequestHash: s.RequestHash,
		ResponseHash: protocol.ResponseHash(response), ClaimsHash: s.ClaimsHash, PredicateCommitment: verifier.Commitment(2, pre), IssuedAt: 1}
	sign(t, s, &b)
	return s, b
}

func canonical(t *testing.T, v any) []byte {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

// fixtureBundle uses the committed Python-built binding fixture: its config and
// trace, with a request and response in the evaluate.py layouts.
func fixtureBundle(t *testing.T) (verifier.Snapshot, verifier.Bundle, []byte) {
	t.Helper()
	raw, err := os.ReadFile("testdata/binding-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var fx struct {
		Config, Trace string
		Preimage      map[string]string
	}
	if err = json.Unmarshal(raw, &fx); err != nil {
		t.Fatal(err)
	}
	pre := verifier.Preimage{ToplocCommitment: word(t, fx.Preimage["toplocCommitment"]), ModelHash: word(t, fx.Preimage["modelHash"]), ConfigHash: word(t, fx.Preimage["configHash"])}
	req := canonical(t, map[string]any{"format": "fairbind/experimental/inference-request/v1", "version": 1, "promptIds": []int{1, 17, 300, 42}})
	resp := canonical(t, map[string]any{"format": "fairbind/experimental/inference-response/v1", "version": 1, "outputIds": []int{5, 6}, "trace": fx.Trace})
	s, b := signed(t, pre, req, resp)
	return s, b, []byte(fx.Config)
}

func pipeline(t *testing.T) Pipeline {
	t.Helper()
	py, err := exec.LookPath("python3")
	if err != nil {
		t.Fatal("python3 is required for the inference pipeline tests")
	}
	script, _ := filepath.Abs("evaluate.py")
	return Pipeline{Python: py, Script: script}
}

func TestPipelineGateFailureIsNotJudged(t *testing.T) {
	s, b, config := fixtureBundle(t)
	// A missing interpreter proves the subprocess is never started.
	p := Pipeline{Python: "/nonexistent/python3", Script: "/nonexistent/evaluate.py"}
	prof := Profile{Snapshot: s, Configs: map[protocol.Bytes32][]byte{s.ConfigHash: config}}
	b.Response = append([]byte(nil), b.Response...)
	b.Response[len(b.Response)-3] ^= 1 // not covered by the signed receipt
	v, ev, err := p.Evaluate(context.Background(), b, prof)
	if !errors.Is(err, ErrNotJudged) || v != "" || ev.Raw != nil {
		t.Fatal(v, err)
	}
	s, b, _ = fixtureBundle(t)
	b.Preimage.ModelHash[0] ^= 1 // preimage does not open the signed commitment
	if _, _, err = p.Evaluate(context.Background(), b, Profile{Snapshot: s}); !errors.Is(err, ErrNotJudged) {
		t.Fatal(err)
	}
}

func TestPipelineMissingCommitmentFails(t *testing.T) {
	s, b, config := fixtureBundle(t)
	b.Receipt.PredicateCommitment = protocol.Bytes32{}
	sign(t, s, &b)
	v, ev, err := pipeline(t).Evaluate(context.Background(), b, Profile{Snapshot: s, Configs: map[protocol.Bytes32][]byte{s.ConfigHash: config}})
	if err != nil || v != Fail || ev.Reason != "empty_predicate_commitment" {
		t.Fatal(v, ev.Reason, err)
	}
	if ev.Hash != protocol.Keccak256(ev.Raw) || ev.ReexecutedOutputHash != hex32(protocol.Bytes32{}) {
		t.Fatalf("%+v", ev)
	}
}

func TestPipelineModelUnavailableIsInconclusive(t *testing.T) {
	s, b, config := fixtureBundle(t)
	v, ev, err := pipeline(t).Evaluate(context.Background(), b, Profile{Snapshot: s, Configs: map[protocol.Bytes32][]byte{s.ConfigHash: config}})
	if err != nil || v != Inconclusive {
		t.Fatal(v, ev.Reason, err)
	}
	t.Log("reason:", ev.Reason)
	// With the pinned runtime the reason is the missing weights; without it,
	// the runtime itself is unavailable. Neither re-executes anything.
	if ev.Reason != "committed weights unavailable to verifier" && ev.Reason != "re-execution runtime unavailable" && ev.Reason != "runtime versions differ from the verifier environment" {
		t.Fatal(ev.Reason)
	}
	if ev.ModelHash != hex32(s.ModelHash) || ev.InputHash != hex32(protocol.Keccak256(b.Request.Body)) || ev.ReproducedCommitment != hex32(protocol.Bytes32{}) {
		t.Fatalf("%+v", ev)
	}
}

func TestPipelineReexecutionPassAndTamperedOutputFail(t *testing.T) {
	p := pipeline(t)
	dir := t.TempDir()
	out, err := exec.Command(p.Python, "testdata/serve_synthetic.py", dir).Output()
	var exit *exec.ExitError
	if errors.As(err, &exit) && exit.ExitCode() == 3 {
		t.Skip("requires the pinned torch, transformers and TOPLOC CPU environment")
	}
	if err != nil {
		t.Fatal(err)
	}
	var fx struct {
		ModelDir, Config, Request, Response, TamperedResponse string
		Preimage                                              map[string]string
	}
	if err = json.Unmarshal(out, &fx); err != nil {
		t.Fatal(err)
	}
	dec := func(s string) []byte { b, _ := base64.StdEncoding.DecodeString(s); return b }
	pre := verifier.Preimage{ToplocCommitment: word(t, fx.Preimage["toplocCommitment"]), ModelHash: word(t, fx.Preimage["modelHash"]), ConfigHash: word(t, fx.Preimage["configHash"])}
	for _, c := range []struct {
		response string
		want     Verdict
	}{{fx.Response, Pass}, {fx.TamperedResponse, Fail}} {
		s, b := signed(t, pre, dec(fx.Request), dec(c.response))
		prof := Profile{Snapshot: s, Configs: map[protocol.Bytes32][]byte{pre.ConfigHash: dec(fx.Config)}, Models: map[protocol.Bytes32]string{pre.ModelHash: fx.ModelDir}}
		v, ev, err := p.Evaluate(context.Background(), b, prof)
		if err != nil || v != c.want {
			t.Fatal(v, ev.Reason, err)
		}
		reproducedMatches := ev.ReproducedCommitment == ev.ToplocCommitment
		outputsMatch := ev.ReexecutedOutputHash == ev.SellerOutputHash
		if (c.want == Pass) != reproducedMatches || (c.want == Pass) != outputsMatch || ev.RecordHash != hex32(protocol.Keccak256(ev.Record)) {
			t.Fatalf("%+v", ev)
		}
	}
}
