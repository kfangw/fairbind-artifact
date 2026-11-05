package c1collect

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"strings"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/dataworker"
	"example.org/fairbind/runtime/dataworker/refsource"
	"example.org/fairbind/runtime/verifier"
)

// Policy frame of the collection plan: the decimal-median policy without its
// reference time. FrameHash is the SHA-256 of its sorted, whitespace-free
// JSON encoding and must equal policy_frame_sha256 in c1-config.json.
const FrameHash = "12213e3d7aadc69813dfe249f01776a4fc00579b20a30e7f5c76c88feb11b458"

// PolicyAt returns the per-judgment policy for one grid time.
func PolicyAt(referenceTime uint64) dataworker.Policy {
	return dataworker.Policy{
		Sources:       []string{refsource.CoinbaseTicker{Product: "BTC-USD"}.ID(), refsource.KrakenTicker{Pair: "XBTUSD"}.ID()},
		Quorum:        2,
		ReferenceTime: referenceTime,
		MaxSkew:       10,
		Fields:        map[string]dataworker.Field{"price": {Unit: "USD", Absolute: "0", Relative: "0.0025", Spread: "250"}},
	}
}

// ReferenceOrder is the registered reference set in policy order.
func ReferenceOrder() []string { return PolicyAt(0).Sources }

// FrameJSON returns the frame encoding whose SHA-256 is FrameHash.
func FrameJSON() ([]byte, error) {
	p := PolicyAt(0)
	var m map[string]any
	b, _ := json.Marshal(p)
	if e := json.Unmarshal(b, &m); e != nil {
		return nil, e
	}
	delete(m, "reference_time")
	return json.Marshal(m) // map keys are sorted by encoding/json
}

// ComputeFrameHash returns the SHA-256 hex of FrameJSON.
func ComputeFrameHash() (string, error) {
	b, e := FrameJSON()
	if e != nil {
		return "", e
	}
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:]), nil
}

// Test seller identity. The private key is the public test key 1; bundles are
// signed only so that the input gate passes and the comparison is reached.
const (
	TestSellerPrivateKey = "0x0000000000000000000000000000000000000000000000000000000000000001"
	testSellerAddress    = "7e5f4552091a69125d5dfcb7b8c2659029395bdf"
)

// Case is one response to judge: the trusted snapshot and the seller bundle.
type Case struct {
	ResponseID string            `json:"response_id"`
	Snapshot   verifier.Snapshot `json:"snapshot"`
	Bundle     verifier.Bundle   `json:"bundle"`
}

// Signer signs a receipt digest without hashing it again.
type Signer func(ctx context.Context, digest protocol.Bytes32) ([]byte, error)

// CastSigner signs with the pinned cast build.
func CastSigner(path string) Signer {
	if path == "" {
		path = "cast"
	}
	return func(ctx context.Context, d protocol.Bytes32) ([]byte, error) {
		ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
		defer cancel()
		out, e := exec.CommandContext(ctx, path, "wallet", "sign", "--no-hash", "--private-key", TestSellerPrivateKey, fmt.Sprintf("0x%x", d)).Output()
		if e != nil {
			return nil, fmt.Errorf("cast wallet sign: %w", e)
		}
		return hex.DecodeString(strings.TrimPrefix(strings.TrimSpace(string(out)), "0x"))
	}
}

// BuildCase wraps a seller-role response body in a signed class-1 bundle bound
// to the policy at referenceTime.
func BuildCase(ctx context.Context, responseID string, response []byte, referenceTime uint64, sign Signer) (Case, error) {
	if responseID == "" || len(response) == 0 {
		return Case{}, errors.New("empty response")
	}
	p := PolicyAt(referenceTime)
	set := dataworker.SourceSet{Sources: p.Sources}
	ph, e := dataworker.ObjectHash(p)
	if e != nil {
		return Case{}, e
	}
	sh, e := dataworker.ObjectHash(set)
	if e != nil {
		return Case{}, e
	}
	keyraw, _ := hex.DecodeString(testSellerAddress)
	key, _ := protocol.ParseAddress(keyraw)
	s := verifier.Snapshot{ChainID: 31337, Contract: protocol.Address{1}, Buyer: protocol.Address{2}, SellerKey: key, SellerID: 7, ProfileID: 4, ClassID: 1,
		PredicateID: dataworker.PolicyID, CanonID: protocol.Keccak256([]byte("fairbind/http-canon/v1")), SourceSetHash: sh, TolerancePolicyHash: ph,
		MaxRequestBytes: 65536, MaxResponseBytes: 65536, MaxClaimsBytes: 65536}
	claims, e := dataworker.CanonicalObject(map[string]any{"version": 1, "classId": 1, "predicateId": fmt.Sprintf("0x%x", dataworker.PolicyID), "sourceSetHash": fmt.Sprintf("0x%x", sh), "tolerancePolicyHash": fmt.Sprintf("0x%x", ph)})
	if e != nil {
		return Case{}, e
	}
	s.ClaimsHash = protocol.Keccak256(claims)
	var k protocol.Bytes16
	kh := sha256.Sum256([]byte("fairbind/c1-collect/purchase-key/v1\x00" + responseID))
	copy(k[:], kh[:16])
	b := verifier.Bundle{Key: k, Claims: claims, Response: append([]byte(nil), response...),
		Request:  verifier.CanonicalRequest{Method: []byte("GET"), Path: []byte("/v1/price"), Query: []byte("pair=BTC-USD")},
		Preimage: verifier.Preimage{ReferenceTime: referenceTime, SourceSetHash: sh, TolerancePolicyHash: ph}}
	s.RequestHash = verifier.RequestHash(b.Request, s.CanonID)
	s.KeyID = protocol.DeriveKeyID(s.ChainID, s.Contract, s.SellerID, s.Buyer, b.Key)
	s.Nonce = protocol.DeriveNonce(s.ChainID, s.Contract, s.SellerID, s.ProfileID, s.ClaimsHash, s.Buyer, b.Key, s.RequestHash)
	b.Receipt = protocol.Receipt{Version: 1, SellerID: s.SellerID, ProfileID: s.ProfileID, Nonce: s.Nonce, RequestHash: s.RequestHash,
		ResponseHash: protocol.ResponseHash(b.Response), ClaimsHash: s.ClaimsHash, PredicateCommitment: verifier.Commitment(1, b.Preimage), IssuedAt: referenceTime}
	sig, e := sign(ctx, protocol.ReceiptDigest(s.ChainID, s.Contract, b.Receipt))
	if e != nil {
		return Case{}, e
	}
	b.Signature = sig
	return Case{ResponseID: responseID, Snapshot: s, Bundle: b}, nil
}
