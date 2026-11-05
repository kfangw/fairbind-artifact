// Package verifier authenticates predicate inputs. READY is not a content verdict.
package verifier

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"strings"

	"example.org/fairbind/protocol"
)

type CanonicalRequest struct{ Method, Path, Query, Headers, Body []byte }

func RequestHash(r CanonicalRequest, canon protocol.Bytes32) protocol.Bytes32 {
	words := []byte{}
	words = append(words, canon[:]...)
	for _, b := range [][]byte{r.Method, r.Path, r.Query, r.Headers, r.Body} {
		h := protocol.Keccak256(b)
		words = append(words, h[:]...)
	}
	return protocol.Keccak256(words)
}

// Snapshot MUST come from a trusted finalized ledger/profile adapter, never the
// untrusted response bundle. This package does not implement that adapter.
type Snapshot struct {
	ChainID                                                   uint64
	Contract, Buyer, SellerKey                                protocol.Address
	SellerID, ProfileID, Epoch                                uint32
	KeyID, Nonce, RequestHash, ClaimsHash                     protocol.Bytes32
	ClassID                                                   uint8
	PredicateID, CanonID                                      protocol.Bytes32
	SourceSetHash, TolerancePolicyHash, ModelHash, ConfigHash protocol.Bytes32
	MaxRequestBytes, MaxResponseBytes, MaxClaimsBytes         int
}
type Preimage struct {
	ReferenceTime                           uint64
	SourceSetHash, TolerancePolicyHash      protocol.Bytes32
	ToplocCommitment, ModelHash, ConfigHash protocol.Bytes32
}
type Bundle struct {
	Key                         protocol.Bytes16
	Request                     CanonicalRequest
	Response, Claims, Signature []byte
	Receipt                     protocol.Receipt
	Preimage                    Preimage
}
type Status string

const (
	Ready        Status = "READY"
	Inconclusive Status = "INCONCLUSIVE"
	Fail         Status = "FAIL"
)

type Result struct {
	Status Status
	Reason string
}

func inc(reason string) Result { return Result{Inconclusive, reason} }

var canonV1 = protocol.Keccak256([]byte("fairbind/http-canon/v1"))
var dataPredicate = mustHash("0xb1659e2eda6c17f24434be64972e5ce19d44b5b4154752bbe83418276831812f")

// ExperimentalDataPredicate is a separate user-authorized comparison policy,
// not the normative DATA_API_REFERENCE_V1 decision procedure.
var ExperimentalDataPredicate = mustHash("0x1a320b649fe0216a2d3ed2e6692f214cc0784cd6ec04bf3ef6cd230418f3ddd7")

var inferencePredicate = mustHash("0xdc77e562812ea60a876f258021aea1da480f6035092b70aa11ca0f5ae1dae9ad")

func mustHash(s string) protocol.Bytes32 {
	h, e := parseHash(s)
	if e != nil {
		panic(e)
	}
	return h
}
func parseHash(s string) (h protocol.Bytes32, err error) {
	if len(s) != 66 || !strings.HasPrefix(s, "0x") {
		return h, fmt.Errorf("invalid bytes32")
	}
	b, e := hex.DecodeString(s[2:])
	if e != nil {
		return h, e
	}
	copy(h[:], b)
	return h, nil
}
func Commitment(class uint8, p Preimage) protocol.Bytes32 {
	var words []byte
	if class == 1 {
		d := protocol.Keccak256([]byte("fairbind/data-commitment/v1"))
		words = append(words, d[:]...)
		var t [32]byte
		binary.BigEndian.PutUint64(t[24:], p.ReferenceTime)
		words = append(words, t[:]...)
		words = append(words, p.SourceSetHash[:]...)
		words = append(words, p.TolerancePolicyHash[:]...)
	} else if class == 2 {
		d := protocol.Keccak256([]byte("fairbind/open-weights-commitment/v1"))
		words = append(words, d[:]...)
		words = append(words, p.ToplocCommitment[:]...)
		words = append(words, p.ModelHash[:]...)
		words = append(words, p.ConfigHash[:]...)
	} else {
		return protocol.Bytes32{}
	}
	return protocol.Keccak256(words)
}

// Check never receives a caller-supplied signature-valid flag. The concrete
// verifier performs recovery with the pinned executable; no network is used.
func Check(ctx context.Context, s Snapshot, b Bundle, v CastVerifier) Result {
	if s.ChainID == 0 || s.Contract == (protocol.Address{}) || s.SellerKey == (protocol.Address{}) || s.Buyer == (protocol.Address{}) || s.SellerID == 0 || s.ProfileID == 0 || s.Epoch > 0xffffff {
		return inc("invalid_snapshot")
	}
	if s.CanonID != canonV1 || (s.ClassID != 1 && s.ClassID != 2) || (s.ClassID == 1 && s.PredicateID != dataPredicate && s.PredicateID != ExperimentalDataPredicate) || (s.ClassID == 2 && s.PredicateID != inferencePredicate) {
		return inc("unsupported_profile")
	}
	if s.MaxRequestBytes <= 0 || s.MaxResponseBytes <= 0 || s.MaxClaimsBytes <= 0 {
		return inc("invalid_limits")
	}
	remaining := s.MaxRequestBytes
	for _, p := range [][]byte{b.Request.Method, b.Request.Path, b.Request.Query, b.Request.Headers, b.Request.Body} {
		if len(p) > remaining {
			return inc("request_limit")
		}
		remaining -= len(p)
	}
	if len(b.Response) > s.MaxResponseBytes || len(b.Claims) > s.MaxClaimsBytes {
		return inc("object_limit")
	}
	if RequestHash(b.Request, s.CanonID) != s.RequestHash {
		return inc("request_binding")
	}
	if protocol.DeriveKeyID(s.ChainID, s.Contract, s.SellerID, s.Buyer, b.Key) != s.KeyID || protocol.DeriveNonce(s.ChainID, s.Contract, s.SellerID, s.ProfileID, s.ClaimsHash, s.Buyer, b.Key, s.RequestHash) != s.Nonce {
		return inc("purchase_binding")
	}
	r := b.Receipt
	if r.Version != 1 || r.SellerID != s.SellerID || r.ProfileID != s.ProfileID || r.Epoch != s.Epoch || r.Nonce != s.Nonce || r.RequestHash != s.RequestHash || r.ClaimsHash != s.ClaimsHash {
		return inc("receipt_purchase_binding")
	}
	if err := v.Verify(ctx, s.SellerKey, protocol.ReceiptDigest(s.ChainID, s.Contract, r), b.Signature); err != nil {
		return inc("receipt_signature")
	}
	// A seller-signed receipt without the required predicate commitment is a
	// seller violation, not an evaluation that could not be completed.
	if r.PredicateCommitment == (protocol.Bytes32{}) {
		return Result{Fail, "empty_predicate_commitment"}
	}
	if protocol.ResponseHash(b.Response) != r.ResponseHash {
		return inc("response_binding")
	}
	if Commitment(s.ClassID, b.Preimage) != r.PredicateCommitment {
		return inc("preimage_binding")
	}
	if protocol.Keccak256(b.Claims) != s.ClaimsHash {
		return inc("claims_binding")
	}
	c, err := decodeClaims(b.Claims, s.ClassID)
	if err != nil {
		return inc("unsupported_claims_encoding")
	}
	if c.predicate != s.PredicateID || c.a != expectedA(s) || c.b != expectedB(s) {
		return inc("snapshot_claims_mismatch")
	}
	a, z := b.Preimage.SourceSetHash, b.Preimage.TolerancePolicyHash
	if s.ClassID == 2 {
		a, z = b.Preimage.ModelHash, b.Preimage.ConfigHash
	}
	if a != c.a || z != c.b {
		return Result{Fail, "authenticated_claims_contradiction"}
	}
	return Result{Ready, "bindings_authenticated_comparison_required"}
}
func expectedA(s Snapshot) protocol.Bytes32 {
	if s.ClassID == 1 {
		return s.SourceSetHash
	}
	return s.ModelHash
}
func expectedB(s Snapshot) protocol.Bytes32 {
	if s.ClassID == 1 {
		return s.TolerancePolicyHash
	}
	return s.ConfigHash
}

type claims struct{ predicate, a, b protocol.Bytes32 }

// The schema contains only ASCII field names, bytes32 strings and integers 1/2.
// Re-encoding the entire strict map therefore equals JCS for this narrow schema.
func decodeClaims(raw []byte, class uint8) (c claims, err error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var value map[string]any
	if err = dec.Decode(&value); err != nil {
		return c, err
	}
	var tail any
	if dec.Decode(&tail) != io.EOF {
		return c, fmt.Errorf("trailing input")
	}
	encoded, e := json.Marshal(value)
	if e != nil || !bytes.Equal(raw, encoded) {
		return c, fmt.Errorf("noncanonical or duplicate fields")
	}
	a, b := "sourceSetHash", "tolerancePolicyHash"
	if class == 2 {
		a, b = "modelHash", "configHash"
	}
	if len(value) != 5 || value["version"] != json.Number("1") || value["classId"] != json.Number(fmt.Sprint(class)) {
		return c, fmt.Errorf("claims schema")
	}
	for name, target := range map[string]*protocol.Bytes32{"predicateId": &c.predicate, a: &c.a, b: &c.b} {
		v, ok := value[name].(string)
		if !ok {
			return c, fmt.Errorf("claims schema")
		}
		*target, err = parseHash(v)
		if err != nil {
			return c, err
		}
	}
	return c, nil
}
