package protocol

import (
	"encoding/hex"
	"testing"
)

func TestIdentifierVector(t *testing.T) {
	contract := mustAddress(t, "1111111111111111111111111111111111111111")
	buyer := mustAddress(t, "f39fd6e51aad88f6f4ce6ab8827279cfffb92266")
	key := must16(t, "00112233445566778899aabbccddeeff")
	claims := must32(t, "a17e50616e113c008c12499c061238d6ffac56c9396f4532ab080688f15ab4cf")
	request := must32(t, "6e6717945809f177d93714f3750a01da09d79ca8245518f15a475df062373246")

	keyID := DeriveKeyID(31337, contract, 7, buyer, key)
	nonce := DeriveNonce(31337, contract, 7, 3, claims, buyer, key, request)

	wantKey := must32(t, "60f593c6957ce4344a3cfd34999d975e2d30057a7bd2df9e3bb0c836edbbb7e7")
	wantNonce := must32(t, "756eab6ff2c296fb7c9062d26fb7b473805da0509b1ac8e0331e7479d96f6d42")
	if keyID != wantKey || nonce != wantNonce {
		t.Fatalf("vector mismatch: key=%x nonce=%x", keyID, nonce)
	}
}

func mustAddress(t *testing.T, value string) Address {
	t.Helper()
	raw, err := hex.DecodeString(value)
	if err != nil {
		t.Fatal(err)
	}
	out, err := ParseAddress(raw)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

func must16(t *testing.T, value string) Bytes16 {
	t.Helper()
	var out Bytes16
	raw, err := hex.DecodeString(value)
	if err != nil || len(raw) != len(out) {
		t.Fatalf("invalid bytes16: %v", err)
	}
	copy(out[:], raw)
	return out
}

func must32(t *testing.T, value string) Bytes32 {
	t.Helper()
	var out Bytes32
	raw, err := hex.DecodeString(value)
	if err != nil || len(raw) != len(out) {
		t.Fatalf("invalid bytes32: %v", err)
	}
	copy(out[:], raw)
	return out
}
