package directive

import (
	"strings"
	"testing"
)

// The block experiments/controller/finiteattack.py writes for three cheated sales.
const finiteBlock = `{"after": "%s", "cheat_sales": 3, "counts": "sales in the order the seller accepts their payments"}`

func TestParseFiniteAttack(t *testing.T) {
	for _, after := range []string{AfterServeHonestly, AfterStopSelling, AfterRequestExit} {
		f, err := Parse([]byte(`{"kind": null, "finite_attack": `+strings.Replace(finiteBlock, "%s", after, 1)+`}`), RoleSeller)
		if err != nil || f.FiniteAttack == nil || f.FiniteAttack.CheatSales != 3 || f.FiniteAttack.After != after {
			t.Fatalf("%s: %v %+v", after, err, f)
		}
		if f.FiniteAttack.StopsSelling() != (after != AfterServeHonestly) {
			t.Fatalf("%s: StopsSelling %v", after, f.FiniteAttack.StopsSelling())
		}
	}
	// It combines with the worst-path block.
	f, err := Parse([]byte(`{"kind": null, "worst_path": `+sellerBlock+`, "finite_attack": `+strings.Replace(finiteBlock, "%s", AfterStopSelling, 1)+`}`), RoleSeller)
	if err != nil || f.WorstPath == nil || f.FiniteAttack == nil {
		t.Fatalf("combined: %v", err)
	}
}

func TestRejectFiniteAttack(t *testing.T) {
	good := strings.Replace(finiteBlock, "%s", AfterServeHonestly, 1)
	for name, c := range map[string]struct{ role, block string }{
		"verifier role":  {RoleVerifier, good},
		"zero sales":     {RoleSeller, strings.Replace(good, `"cheat_sales": 3`, `"cheat_sales": 0`, 1)},
		"negative sales": {RoleSeller, strings.Replace(good, `"cheat_sales": 3`, `"cheat_sales": -1`, 1)},
		"unknown after":  {RoleSeller, strings.Replace(finiteBlock, "%s", "vanish", 1)},
		"other counting": {RoleSeller, strings.Replace(good, "accepts their payments", "settles them", 1)},
		"missing counts": {RoleSeller, `{"after": "serve_honestly", "cheat_sales": 3}`},
		"unknown key":    {RoleSeller, strings.Replace(good, `"cheat_sales": 3`, `"cheat_sales": 3, "rate": 1`, 1)},
	} {
		if _, err := Parse([]byte(`{"kind": null, "finite_attack": `+c.block+`}`), c.role); err == nil {
			t.Errorf("%s accepted", name)
		}
	}
}
