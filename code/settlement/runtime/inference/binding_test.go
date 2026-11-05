package inference

import (
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/verifier"
)

// The fixture is written by the Python seller path. This test checks that the
// Go gate opens the same class-2 commitment from the same bytes.
func TestPythonBindingFixture(t *testing.T) {
	raw, err := os.ReadFile("testdata/binding-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var fx struct {
		Config, Trace       string
		WeightManifest      map[string]any
		Preimage            map[string]string
		PredicateCommitment string
	}
	if err = json.Unmarshal(raw, &fx); err != nil {
		t.Fatal(err)
	}
	word := func(s string) protocol.Bytes32 {
		var h protocol.Bytes32
		b, e := hex.DecodeString(s[2:])
		if e != nil || len(b) != 32 {
			t.Fatalf("invalid bytes32 %q", s)
		}
		copy(h[:], b)
		return h
	}
	// Go's encoder sorts keys and emits compact ASCII, which equals JCS here.
	manifest, err := json.Marshal(fx.WeightManifest)
	if err != nil {
		t.Fatal(err)
	}
	p := verifier.Preimage{ToplocCommitment: word(fx.Preimage["toplocCommitment"]), ModelHash: word(fx.Preimage["modelHash"]), ConfigHash: word(fx.Preimage["configHash"])}
	checks := []struct {
		name      string
		got, want protocol.Bytes32
	}{
		{"toplocCommitment", protocol.Keccak256([]byte(fx.Trace)), p.ToplocCommitment},
		{"configHash", protocol.Keccak256([]byte(fx.Config)), p.ConfigHash},
		{"modelHash", protocol.Keccak256(manifest), p.ModelHash},
		{"predicateCommitment", verifier.Commitment(2, p), word(fx.PredicateCommitment)},
	}
	for _, c := range checks {
		if c.got != c.want {
			t.Errorf("%s: got %x want %x", c.name, c.got, c.want)
		}
	}
}
