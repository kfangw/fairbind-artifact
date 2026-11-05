package protocol

import (
	"encoding/hex"
	"testing"
)

func TestReceiptDigestVector(t *testing.T) {
	response, err := hex.DecodeString("7b227072696365223a223132332e3435222c2273796d626f6c223a224554482d555344227d0a")
	if err != nil {
		t.Fatal(err)
	}
	receipt := Receipt{
		Version:             1,
		SellerID:            7,
		ProfileID:           3,
		Nonce:               must32(t, "756eab6ff2c296fb7c9062d26fb7b473805da0509b1ac8e0331e7479d96f6d42"),
		RequestHash:         must32(t, "6e6717945809f177d93714f3750a01da09d79ca8245518f15a475df062373246"),
		ResponseHash:        ResponseHash(response),
		ClaimsHash:          must32(t, "a17e50616e113c008c12499c061238d6ffac56c9396f4532ab080688f15ab4cf"),
		PredicateCommitment: must32(t, "84faff9ee10d7f8d69984f348605f4046eb6750d482bbfc69bb70842fcc3fb1c"),
		Epoch:               14,
		IssuedAt:            1788480000,
	}
	digest := ReceiptDigest(31337, mustAddress(t, "1111111111111111111111111111111111111111"), receipt)
	if digest != must32(t, "18429398246ed4f6fc3d2d1da31841f15dedc549143b22976e87f50638b8a0b2") {
		t.Fatalf("digest mismatch: %x", digest)
	}
}

func TestResponseHashUsesPositionalChunks(t *testing.T) {
	body := make([]byte, ResponseChunkBytes+17)
	for i := range body {
		body[i] = byte(i)
	}
	first := Keccak256(body[:ResponseChunkBytes])
	second := Keccak256(body[ResponseChunkBytes:])
	want := Keccak256(ResponseNodeDomain[:], first[:], second[:])
	if got := ResponseHash(body); got != want {
		t.Fatalf("response root mismatch: %x", got)
	}
}
