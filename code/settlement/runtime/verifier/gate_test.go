package verifier

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"strings"
	"testing"

	"example.org/fairbind/protocol"
)

// Public deterministic test key 1, never a funded/production identity.
func sign(t *testing.T, s Snapshot, b *Bundle) {
	t.Helper()
	d := protocol.ReceiptDigest(s.ChainID, s.Contract, b.Receipt)
	cmd := exec.Command("cast", "wallet", "sign", "--no-hash", "--private-key", "0x"+strings.Repeat("0", 63)+"1", "0x"+hex.EncodeToString(d[:]))
	out, e := cmd.Output()
	if e != nil {
		t.Fatal("test fixture signing failed")
	}
	b.Signature, e = hex.DecodeString(strings.TrimPrefix(strings.TrimSpace(string(out)), "0x"))
	if e != nil {
		t.Fatal(e)
	}
}
func fixture(t *testing.T) (Snapshot, Bundle) {
	t.Helper()
	s := Snapshot{ChainID: 31337, SellerID: 7, ProfileID: 3, Epoch: 1, ClassID: 1, CanonID: canonV1, PredicateID: dataPredicate, MaxRequestBytes: 65536, MaxResponseBytes: 65536, MaxClaimsBytes: 4096}
	s.Contract[19] = 1
	s.Buyer[19] = 2
	key, _ := hex.DecodeString("7e5f4552091a69125d5dfcb7b8c2659029395bdf")
	copy(s.SellerKey[:], key)
	s.SourceSetHash = protocol.Keccak256([]byte("sources"))
	s.TolerancePolicyHash = protocol.Keccak256([]byte("tolerance"))
	b := Bundle{Request: CanonicalRequest{Method: []byte("GET"), Path: []byte("/quote")}, Response: []byte("42"), Preimage: Preimage{ReferenceTime: 123, SourceSetHash: s.SourceSetHash, TolerancePolicyHash: s.TolerancePolicyHash}}
	b.Key[15] = 7
	b.Claims, _ = json.Marshal(map[string]any{"classId": 1, "version": 1, "predicateId": "0x" + hex.EncodeToString(s.PredicateID[:]), "sourceSetHash": "0x" + hex.EncodeToString(s.SourceSetHash[:]), "tolerancePolicyHash": "0x" + hex.EncodeToString(s.TolerancePolicyHash[:])})
	s.ClaimsHash = protocol.Keccak256(b.Claims)
	s.RequestHash = RequestHash(b.Request, s.CanonID)
	s.KeyID = protocol.DeriveKeyID(s.ChainID, s.Contract, s.SellerID, s.Buyer, b.Key)
	s.Nonce = protocol.DeriveNonce(s.ChainID, s.Contract, s.SellerID, s.ProfileID, s.ClaimsHash, s.Buyer, b.Key, s.RequestHash)
	b.Receipt = protocol.Receipt{Version: 1, SellerID: s.SellerID, ProfileID: s.ProfileID, Epoch: s.Epoch, Nonce: s.Nonce, RequestHash: s.RequestHash, ClaimsHash: s.ClaimsHash, ResponseHash: protocol.ResponseHash(b.Response), PredicateCommitment: Commitment(1, b.Preimage)}
	sign(t, s, &b)
	return s, b
}
func TestGateAuthenticatesWithoutContentVerdict(t *testing.T) {
	s, b := fixture(t)
	r := Check(context.Background(), s, b, CastVerifier{})
	if r.Status != Ready {
		t.Fatal(r)
	}
}
func TestGateRejectsUntrustedMutations(t *testing.T) {
	for _, tc := range []struct {
		name   string
		mutate func(*Snapshot, *Bundle)
	}{
		{"signature", func(s *Snapshot, b *Bundle) { b.Signature[0] ^= 1 }},
		{"high-s", func(s *Snapshot, b *Bundle) { b.Signature[32] = 255 }},
		{"recovery-id", func(s *Snapshot, b *Bundle) { b.Signature[64] = 0 }},
		{"other-purchase", func(s *Snapshot, b *Bundle) { b.Key[0] ^= 1 }},
		{"other-chain", func(s *Snapshot, b *Bundle) { s.ChainID++ }},
		{"other-contract", func(s *Snapshot, b *Bundle) { s.Contract[0] ^= 1 }},
		{"request-body", func(s *Snapshot, b *Bundle) { b.Request.Body = []byte("tampered") }},
		{"response-body", func(s *Snapshot, b *Bundle) { b.Response = []byte("tampered") }},
		{"preimage", func(s *Snapshot, b *Bundle) { b.Preimage.ReferenceTime++ }},
		{"claims", func(s *Snapshot, b *Bundle) { b.Claims = append(b.Claims, ' ') }},
		{"response-limit", func(s *Snapshot, b *Bundle) { s.MaxResponseBytes = 1 }},
		{"request-limit", func(s *Snapshot, b *Bundle) { s.MaxRequestBytes = 1 }},
		{"claims-limit", func(s *Snapshot, b *Bundle) { s.MaxClaimsBytes = 1 }},
		{"snapshot-key", func(s *Snapshot, b *Bundle) { s.SellerKey[0] ^= 1 }},
		{"predicate", func(s *Snapshot, b *Bundle) { s.PredicateID[0] ^= 1 }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			s, b := fixture(t)
			tc.mutate(&s, &b)
			r := Check(context.Background(), s, b, CastVerifier{})
			if r.Status != Inconclusive {
				t.Fatal(r)
			}
		})
	}
}
func TestAuthenticatedClaimsContradiction(t *testing.T) {
	s, b := fixture(t)
	b.Preimage.SourceSetHash[0] ^= 1
	b.Receipt.PredicateCommitment = Commitment(1, b.Preimage)
	sign(t, s, &b)
	r := Check(context.Background(), s, b, CastVerifier{})
	if r.Status != Fail {
		t.Fatal(r)
	}
}
func TestSignedEmptyCommitmentFails(t *testing.T) {
	s, b := fixture(t)
	b.Receipt.PredicateCommitment = protocol.Bytes32{}
	sign(t, s, &b)
	r := Check(context.Background(), s, b, CastVerifier{})
	if r.Status != Fail || r.Reason != "empty_predicate_commitment" {
		t.Fatal(r)
	}
	// An unsigned empty commitment stays unauthenticated.
	b.Signature[0] ^= 1
	if r = Check(context.Background(), s, b, CastVerifier{}); r.Status != Inconclusive {
		t.Fatal(r)
	}
}
func TestSignatureBindsDomain(t *testing.T) {
	s, b := fixture(t)
	other := s
	other.ChainID++
	sign(t, other, &b)
	if r := Check(context.Background(), s, b, CastVerifier{}); r.Reason != "receipt_signature" {
		t.Fatal(r)
	}
}
func TestClaimsStrictCanonicalSubset(t *testing.T) {
	s, b := fixture(t)
	_ = s
	for _, raw := range [][]byte{append(append([]byte{}, b.Claims...), ' '), []byte(strings.Replace(string(b.Claims), `"version":1`, `"version":1,"version":1`, 1)), []byte(strings.Replace(string(b.Claims), `"version":1`, `"version":1,"unknown":1`, 1)), []byte(strings.Replace(string(b.Claims), `"version":1`, `"version":1.0`, 1))} {
		if _, e := decodeClaims(raw, 1); e == nil {
			t.Fatal("accepted unsupported/noncanonical claims")
		}
	}
}
func TestExistingPredicateVectors(t *testing.T) {
	raw, e := os.ReadFile("../../test-vectors/predicate-v1.json")
	if e != nil {
		t.Fatal(e)
	}
	var v struct {
		Claims struct {
			Value      map[string]any
			ClaimsHash string
		}
		DataAPICommitment struct {
			ReferenceTime                                           string
			SourceSetHash, TolerancePolicyHash, PredicateCommitment string
		}
		OpenWeightsCommitment struct{ ToplocCommitment, ModelHash, ConfigHash, PredicateCommitment string }
	}
	if e = json.Unmarshal(raw, &v); e != nil {
		t.Fatal(e)
	}
	c, _ := json.Marshal(v.Claims.Value)
	if protocol.Keccak256(c) != mustHash(v.Claims.ClaimsHash) {
		t.Fatal("claims vector")
	}
	p := Preimage{ReferenceTime: 1725400000, SourceSetHash: mustHash(v.DataAPICommitment.SourceSetHash), TolerancePolicyHash: mustHash(v.DataAPICommitment.TolerancePolicyHash)}
	if Commitment(1, p) != mustHash(v.DataAPICommitment.PredicateCommitment) {
		t.Fatal("data commitment")
	}
	p = Preimage{ToplocCommitment: mustHash(v.OpenWeightsCommitment.ToplocCommitment), ModelHash: mustHash(v.OpenWeightsCommitment.ModelHash), ConfigHash: mustHash(v.OpenWeightsCommitment.ConfigHash)}
	if Commitment(2, p) != mustHash(v.OpenWeightsCommitment.PredicateCommitment) {
		t.Fatal("inference commitment")
	}
}
func TestExistingRequestVectors(t *testing.T) {
	raw, e := os.ReadFile("../../test-vectors/canonicalization-v1.json")
	if e != nil {
		t.Fatal(e)
	}
	var v struct {
		CanonID  string
		Positive []struct {
			Normalized struct{ Method, Path, Query, HeaderBlockHex string }
			Input      struct{ BodyHex string }
			Hashes     struct{ RequestHash string }
		}
	}
	if e = json.Unmarshal(raw, &v); e != nil {
		t.Fatal(e)
	}
	for _, p := range v.Positive {
		headers, _ := hex.DecodeString(strings.TrimPrefix(p.Normalized.HeaderBlockHex, "0x"))
		body, _ := hex.DecodeString(strings.TrimPrefix(p.Input.BodyHex, "0x"))
		r := CanonicalRequest{[]byte(p.Normalized.Method), []byte(p.Normalized.Path), []byte(p.Normalized.Query), headers, body}
		if RequestHash(r, mustHash(v.CanonID)) != mustHash(p.Hashes.RequestHash) {
			t.Fatal("request vector")
		}
	}
}

func TestOpenWeightsAndExperimentalBindings(t *testing.T) {
	for _, class := range []uint8{1, 2} {
		t.Run(string(rune('0'+class)), func(t *testing.T) {
			s, b := fixture(t)
			if class == 1 {
				s.PredicateID = ExperimentalDataPredicate
			} else {
				s.ClassID = 2
				s.PredicateID = inferencePredicate
				s.ModelHash = protocol.Keccak256([]byte("model"))
				s.ConfigHash = protocol.Keccak256([]byte("config"))
				b.Preimage = Preimage{ToplocCommitment: protocol.Keccak256([]byte("trace")), ModelHash: s.ModelHash, ConfigHash: s.ConfigHash}
			}
			c := map[string]any{"classId": class, "version": 1, "predicateId": "0x" + hex.EncodeToString(s.PredicateID[:])}
			if class == 1 {
				c["sourceSetHash"] = "0x" + hex.EncodeToString(s.SourceSetHash[:])
				c["tolerancePolicyHash"] = "0x" + hex.EncodeToString(s.TolerancePolicyHash[:])
			} else {
				c["modelHash"] = "0x" + hex.EncodeToString(s.ModelHash[:])
				c["configHash"] = "0x" + hex.EncodeToString(s.ConfigHash[:])
			}
			b.Claims, _ = json.Marshal(c)
			s.ClaimsHash = protocol.Keccak256(b.Claims)
			s.Nonce = protocol.DeriveNonce(s.ChainID, s.Contract, s.SellerID, s.ProfileID, s.ClaimsHash, s.Buyer, b.Key, s.RequestHash)
			b.Receipt.Nonce = s.Nonce
			b.Receipt.ClaimsHash = s.ClaimsHash
			b.Receipt.PredicateCommitment = Commitment(class, b.Preimage)
			sign(t, s, &b)
			if r := Check(context.Background(), s, b, CastVerifier{}); r.Status != Ready {
				t.Fatal(r)
			}
			if class == 2 {
				b.Preimage.ModelHash[0] ^= 1
				b.Receipt.PredicateCommitment = Commitment(class, b.Preimage)
				sign(t, s, &b)
				if r := Check(context.Background(), s, b, CastVerifier{}); r.Status != Fail {
					t.Fatal(r)
				}
			}
		})
	}
}
