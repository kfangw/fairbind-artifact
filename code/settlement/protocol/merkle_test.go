package protocol

import "testing"

func TestReceiptMerkleVector(t *testing.T) {
	entries := []ReceiptEntry{
		{must32(t, "0000000000000000000000000000000000000000000000000000000000000050"), must32(t, "a92aa3c109a64b75827620efd7ec7aef1dbd7e02f6e8bd15df81a39b6e031a3b")},
		{must32(t, "0000000000000000000000000000000000000000000000000000000000000010"), must32(t, "d0d879d3e6036e918857021e097d5a13b213974d6fcba3756efbd512d0ce1a27")},
		{must32(t, "0000000000000000000000000000000000000000000000000000000000000030"), must32(t, "9e19446555a83d5e12578fee5fdc10a13e1d57272f8fd65730f16cd65fb03caf")},
	}
	root, err := ReceiptRoot(entries)
	if err != nil {
		t.Fatal(err)
	}
	want := must32(t, "b0e5ce6b84df6db5f7e3847d05560064b749bdc676f4ad8ff9338ca0a71bf28a")
	if root != want {
		t.Fatalf("root mismatch: %x", root)
	}

	proof := ReceiptProof{Index: 1, Count: 3, Siblings: []Bytes32{
		must32(t, "64ce93f4153134d24dbf6c330cfa72e9c632bbabdcbcaec00fd49fb5fe14d6a1"),
		must32(t, "41633787219e7ebc73e866c9453e8e5d15dcc07828db7040acc4d8a3c7917df0"),
	}}
	if !VerifyReceiptProof(root, entries[2], proof) {
		t.Fatal("valid proof rejected")
	}
}

func TestReceiptMerkleRejectsDuplicate(t *testing.T) {
	nonce := must32(t, "0000000000000000000000000000000000000000000000000000000000000010")
	_, err := ReceiptRoot([]ReceiptEntry{{nonce, Bytes32{1}}, {nonce, Bytes32{2}}})
	if err == nil {
		t.Fatal("duplicate nonce accepted")
	}
}
