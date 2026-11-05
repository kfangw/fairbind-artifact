package protocol

import (
	"encoding/json"
	"os"
	"strconv"
	"strings"
	"testing"
)

type verdictVectorFile struct {
	Fixtures struct {
		ChainID         string `json:"chainId"`
		ContractAddress string `json:"contractAddress"`
	} `json:"fixtures"`
	Verdict struct {
		TypeHash string `json:"typeHash"`
		Message  struct {
			Version      uint8  `json:"version"`
			Nonce        string `json:"nonce"`
			Stage        uint8  `json:"stage"`
			Attempt      uint8  `json:"attempt"`
			VerifierID   uint32 `json:"verifierId"`
			Verdict      uint8  `json:"verdict"`
			EvidenceHash string `json:"evidenceHash"`
		} `json:"message"`
		StructHash string `json:"structHash"`
		Digest     string `json:"digest"`
	} `json:"verdict"`
}

func loadVerdictVector(t *testing.T) (verdictVectorFile, uint64, Address, SignedVerdict) {
	t.Helper()
	raw, err := os.ReadFile("../test-vectors/cryptography-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var vector verdictVectorFile
	if err := json.Unmarshal(raw, &vector); err != nil {
		t.Fatal(err)
	}
	chainID, err := strconv.ParseUint(vector.Fixtures.ChainID, 10, 64)
	if err != nil {
		t.Fatal(err)
	}
	contract := mustAddress(t, strings.TrimPrefix(vector.Fixtures.ContractAddress, "0x"))
	m := vector.Verdict.Message
	verdict := SignedVerdict{
		Version: m.Version, Nonce: must32(t, strings.TrimPrefix(m.Nonce, "0x")),
		Stage: m.Stage, Attempt: m.Attempt, VerifierID: m.VerifierID,
		Verdict: m.Verdict, EvidenceHash: must32(t, strings.TrimPrefix(m.EvidenceHash, "0x")),
	}
	return vector, chainID, contract, verdict
}

func TestVerdictDigestVector(t *testing.T) {
	vector, chainID, contract, verdict := loadVerdictVector(t)
	checks := []struct {
		name string
		got  Bytes32
		want string
	}{
		{"typeHash", VerdictTypeHash, vector.Verdict.TypeHash},
		{"structHash", VerdictStructHash(verdict), vector.Verdict.StructHash},
		{"digest", VerdictDigest(chainID, contract, verdict), vector.Verdict.Digest},
	}
	for _, check := range checks {
		t.Run(check.name, func(t *testing.T) {
			if want := must32(t, strings.TrimPrefix(check.want, "0x")); check.got != want {
				t.Fatalf("%s mismatch: got %x, want %x", check.name, check.got, want)
			}
		})
	}
}

func TestVerdictDigestBindsAssignmentAndEvidence(t *testing.T) {
	_, chainID, contract, original := loadVerdictVector(t)
	originalDigest := VerdictDigest(chainID, contract, original)
	cases := []struct {
		name   string
		mutate func(*SignedVerdict)
	}{
		{"version", func(v *SignedVerdict) { v.Version++ }},
		{"nonce", func(v *SignedVerdict) { v.Nonce[0] ^= 1 }},
		{"stage", func(v *SignedVerdict) { v.Stage++ }},
		{"attempt", func(v *SignedVerdict) { v.Attempt++ }},
		{"verifierId", func(v *SignedVerdict) { v.VerifierID++ }},
		{"verdict", func(v *SignedVerdict) { v.Verdict++ }},
		{"evidenceHash", func(v *SignedVerdict) { v.EvidenceHash[0] ^= 1 }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			changed := original
			tc.mutate(&changed)
			if VerdictDigest(chainID, contract, changed) == originalDigest {
				t.Fatalf("digest did not bind %s", tc.name)
			}
		})
	}
	t.Run("chainId", func(t *testing.T) {
		if VerdictDigest(chainID+1, contract, original) == originalDigest {
			t.Fatal("digest did not bind chainId")
		}
	})
	t.Run("verifyingContract", func(t *testing.T) {
		changed := contract
		changed[0] ^= 1
		if VerdictDigest(chainID, changed, original) == originalDigest {
			t.Fatal("digest did not bind verifyingContract")
		}
	})
}
