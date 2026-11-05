package ethkey

import (
	"encoding/hex"
	"encoding/json"
	"math/big"
	"os"
	"os/exec"
	"strings"
	"testing"

	"example.org/fairbind/protocol"
)

func hexBytes(t *testing.T, s string) []byte {
	t.Helper()
	b, err := hex.DecodeString(strings.TrimPrefix(s, "0x"))
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func digest(t *testing.T, s string) (d protocol.Bytes32) {
	copy(d[:], hexBytes(t, s))
	return
}

type vectors struct {
	Fixtures struct {
		BuyerPrivateKey, Buyer, SellerPrivateKey, SellerSigningKey string
	}
	PaymentAuthorization struct{ Digest, Signature string }
	Receipt              struct{ Digest, Signature string }
}

func load(t *testing.T) vectors {
	raw, err := os.ReadFile("../../../../test-vectors/cryptography-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var v vectors
	if err = json.Unmarshal(raw, &v); err != nil {
		t.Fatal(err)
	}
	return v
}

func TestVectorSignaturesAreReproduced(t *testing.T) {
	v := load(t)
	cases := []struct{ key, addr, digest, sig string }{
		{v.Fixtures.BuyerPrivateKey, v.Fixtures.Buyer, v.PaymentAuthorization.Digest, v.PaymentAuthorization.Signature},
		{v.Fixtures.SellerPrivateKey, v.Fixtures.SellerSigningKey, v.Receipt.Digest, v.Receipt.Signature},
	}
	for _, c := range cases {
		k, err := ParsePrivateKey(c.key)
		if err != nil {
			t.Fatal(err)
		}
		if got := "0x" + hexAddr(k.Address()); got != c.addr {
			t.Fatalf("address %s, want %s", got, c.addr)
		}
		sig := k.Sign(digest(t, c.digest))
		if "0x"+hex.EncodeToString(sig) != c.sig {
			t.Fatalf("signature mismatch:\n got %x\nwant %s", sig, c.sig)
		}
		if err := Verify(k.Address(), digest(t, c.digest), hexBytes(t, c.sig)); err != nil {
			t.Fatal(err)
		}
	}
}

func TestRecoverRejectsMalleableAndWrongSigner(t *testing.T) {
	v := load(t)
	d := digest(t, v.Receipt.Digest)
	sig := hexBytes(t, v.Receipt.Signature)
	k, _ := ParsePrivateKey(v.Fixtures.BuyerPrivateKey)
	if Verify(k.Address(), d, sig) == nil {
		t.Fatal("wrong signer accepted")
	}
	bad := append([]byte(nil), sig...)
	bad[64] = 29
	if _, err := Recover(d, bad); err == nil {
		t.Fatal("v=29 accepted")
	}
	// high-s twin: s' = n - s, v flipped
	high := append([]byte(nil), sig...)
	s := new(big.Int).SetBytes(sig[32:64])
	s.Sub(curveN, s)
	s.FillBytes(high[32:64])
	if _, err := Recover(d, high); err == nil {
		t.Fatal("high s accepted")
	}
}

func TestCastCrossCheck(t *testing.T) {
	cast, err := exec.LookPath("cast") // cast from PATH
	if err != nil {
		t.Skip("cast not available")
	}
	k, _ := ParsePrivateKey("0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d")
	d := protocol.Keccak256([]byte("cross check"))
	out, err := exec.Command(cast, "wallet", "sign", "--no-hash", "--private-key", "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d", "0x"+hex.EncodeToString(d[:])).Output()
	if err != nil {
		t.Skip("cast failed: ", err)
	}
	if strings.TrimSpace(string(out)) != "0x"+hex.EncodeToString(k.Sign(d)) {
		t.Fatalf("cast %s, ours %x", out, k.Sign(d))
	}
}

func hexAddr(a protocol.Address) string { return hex.EncodeToString(a[:]) }
