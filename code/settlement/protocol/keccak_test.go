package protocol

import (
	"encoding/hex"
	"testing"
)

// Vectors cross-checked against pycryptodome (Crypto.Hash.keccak,
// digest_bits=256) and foundry's `cast keccak` for input of the given
// length, where byte i of the input is i%256.
func TestKeccak256PaddingBoundaries(t *testing.T) {
	cases := []struct {
		name   string
		length int
		digest string
	}{
		{"empty", 0, "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"},
		{"one-byte", 1, "bc36789e7a1e281436464229828f817d6612f7b477d66591ff96a9e064bcc98a"},
		{"one-short-of-block", 135, "cbdfd9dee5faad3818d6b06f95a219fd290b0e1706f6a82e5a595b9ce9faca62"},
		{"exact-block", 136, "7ce759f1ab7f9ce437719970c26b0a66ff11fe3e38e17df89cf5d29c7d7f807e"},
		{"one-short-of-two-blocks", 271, "7c974895b2a88303ff2dc6b58f438ceb0b298cac91099ac0539cc0f477506191"},
		{"exact-two-blocks", 272, "fdf2ec49e749960d3c8521a0219af8d03e30e2b3bf19bd16150ee0eaf133d66e"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			input := make([]byte, tc.length)
			for i := range input {
				input[i] = byte(i % 256)
			}
			want, err := hex.DecodeString(tc.digest)
			if err != nil {
				t.Fatalf("bad test vector: %v", err)
			}
			got := keccak256(input)
			if hex.EncodeToString(got[:]) != hex.EncodeToString(want) {
				t.Fatalf("keccak256(len=%d) = %x, want %x", tc.length, got, want)
			}
		})
	}
}
