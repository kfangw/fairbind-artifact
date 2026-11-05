package directive

import (
	"encoding/json"
	"fmt"
	"sort"
)

// Finite-attack block (experiments/controller/finiteattack.py, seller only).
// The seller cheats on its first CheatSales sales, counted in the order it
// accepts their payments, and then follows After:
//   - AfterServeHonestly: keeps selling and serves every later sale honestly;
//   - AfterStopSelling: refuses every new purchase and keeps serving the ones it
//     already accepted (redelivery, publication, anchors);
//   - AfterRequestExit: stops selling as above and, once its last cheated sale
//     is delivered, requests the exit of its registration and of its bond
//     account, and finalizes each as soon as the contract admits it.
const (
	AfterServeHonestly = "serve_honestly"
	AfterStopSelling   = "stop_selling"
	AfterRequestExit   = "request_exit"
)

// FiniteAttackCounts names how the seller counts its sales.
const FiniteAttackCounts = "sales in the order the seller accepts their payments"

// FiniteAttack is the parsed finite-attack block.
type FiniteAttack struct {
	CheatSales uint64
	After      string
}

// StopsSelling reports whether the seller refuses new purchases once its
// cheated sales are made.
func (a *FiniteAttack) StopsSelling() bool {
	return a != nil && (a.After == AfterStopSelling || a.After == AfterRequestExit)
}

func parseFiniteAttack(raw json.RawMessage) (*FiniteAttack, error) {
	var m map[string]any
	if err := strictDecode(raw, &m); err != nil {
		return nil, err
	}
	a := &FiniteAttack{}
	var missing []string
	for _, k := range []string{"cheat_sales", "after", "counts"} {
		if _, ok := m[k]; !ok {
			missing = append(missing, k)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		return nil, fmt.Errorf("missing %v", missing)
	}
	for k, v := range m {
		switch k {
		case "cheat_sales":
			n, err := uintValue(v)
			if err != nil || n == 0 {
				return nil, fmt.Errorf("cheat_sales must be a positive integer")
			}
			a.CheatSales = n
		case "after":
			switch v {
			case AfterServeHonestly, AfterStopSelling, AfterRequestExit:
				a.After = v.(string)
			default:
				return nil, fmt.Errorf("after %v, want %s, %s or %s", v, AfterServeHonestly, AfterStopSelling, AfterRequestExit)
			}
		case "counts":
			if v != FiniteAttackCounts {
				return nil, fmt.Errorf("counts %v, want %q", v, FiniteAttackCounts)
			}
		default:
			return nil, fmt.Errorf("unknown key %q", k)
		}
	}
	return a, nil
}
