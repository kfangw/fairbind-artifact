// Package directive reads the directive file the scenario controller writes for
// each process (experiments/controller/README.md, "Processes and manifest") and
// validates the parts the services act on: the worst-path block
// (experiments/controller/worstpath.py) and the keeper delay budget.
//
// The worst-path block is descriptive: every value names a deadline or a
// verdict. Each role accepts exactly the keys and values worstpath.py writes for
// it, so a directive the services would not carry out is rejected at start
// instead of silently running the default path.
package directive

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"sort"
)

// Roles that read a worst-path block.
const (
	RoleVerifier = "verifier"
	RoleSeller   = "seller"
	RoleKeeper   = "keeper"
	RoleBuyer    = "buyer"
)

// AppliesTo is the scope worstpath.py gives every block. The services apply the
// block to every case opened by sampling (trigger SAMPLE).
const AppliesTo = "every sampled bad sale"

// KeeperDelaySpentOn names the one keeper call that spends the per-case budget.
const KeeperDelaySpentOn = "last keeper call before the confirmed failure of each case"

// File is one process's directive file.
type File struct {
	Seed        json.RawMessage `json:"seed,omitempty"`
	Kind        *string         `json:"kind"`
	Parameters  map[string]any  `json:"parameters,omitempty"`
	Randomness  map[string]any  `json:"randomness,omitempty"`
	WorstPath   *WorstPath      `json:"-"`
	KeeperDelay *KeeperDelay    `json:"-"`
	// FiniteAttack is the seller's finite-attack block (finite.go).
	FiniteAttack *FiniteAttack `json:"-"`
}

// WorstPath holds the parsed worst-path block of one role.
type WorstPath struct {
	Role        string
	CaseHorizon uint64
	// Verifier: verdicts of the initial, party review and tiebreak stages, and
	// the number of assignments of a stage that are replaced before its last.
	InitialVerdict, PartyReviewVerdict, TiebreakVerdict string
	MaxReplacedAssignments                              uint8
}

// KeeperDelay is the keeper's per-case delay budget (kappa).
type KeeperDelay struct {
	BudgetBlocks uint64
}

// expected lists the fixed values each role accepts; nil means the key is
// parsed separately.
var expected = map[string]map[string]any{
	RoleVerifier: {
		"initial_non_last_assignments": "deliver FAIL at the judge deadline; voided by timeoutEvidence in the block after the evidence deadline",
		"review_non_last_assignments":  "time out at the judge deadline",
		"request_serve_at":             "judge_deadline",
		"escalate_at":                  "challenge_deadline",
		"verdict_at":                   "judge_deadline",
		"disclose_evidence_on_initial_non_last_assignments": false,
		"disclose_evidence_on_initial_last_assignment_at":   "evidence_deadline",
		"initial_verdict":          nil,
		"party_review_verdict":     nil,
		"tiebreak_verdict":         nil,
		"max_replaced_assignments": nil,
	},
	RoleSeller: {
		"anchor_at":              "anchor_deadline",
		"redeliver_at":           "serve_deadline",
		"publish_at":             "publication_deadline",
		"request_evidence_at":    "appeal_deadline",
		"appeal_initial_fail_at": "renewed_appeal_deadline",
	},
	RoleKeeper: {
		"review_seal":    "let the first seal window of every review stage lapse, then seal the reopened stage",
		"call_at":        "deadline",
		"open_sample_at": "open_window_end",
	},
	RoleBuyer: {
		"dispute_sampled_sale": false,
		"claim_at":             "after_case_final",
	},
}

// Load reads a directive file for role. An empty path returns nil: the process
// runs its default behavior.
func Load(path, role string) (*File, error) {
	if path == "" {
		return nil, nil
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return Parse(raw, role)
}

// Parse decodes and validates a directive file for role.
func Parse(raw []byte, role string) (*File, error) {
	if _, ok := expected[role]; !ok {
		return nil, fmt.Errorf("directive: unknown role %q", role)
	}
	var top map[string]json.RawMessage
	if err := strictDecode(raw, &top); err != nil {
		return nil, fmt.Errorf("directive: %w", err)
	}
	f := &File{}
	for k, v := range top {
		var err error
		switch k {
		case "seed":
			f.Seed = v
		case "kind":
			err = json.Unmarshal(v, &f.Kind)
		case "parameters":
			err = json.Unmarshal(v, &f.Parameters)
		case "randomness":
			err = json.Unmarshal(v, &f.Randomness)
		case "worst_path":
			f.WorstPath, err = parseWorstPath(v, role)
		case "finite_attack":
			if role != RoleSeller {
				err = fmt.Errorf("only the seller takes a finite_attack block")
			} else {
				f.FiniteAttack, err = parseFiniteAttack(v)
			}
		case "keeper_delay":
			if role != RoleKeeper {
				err = fmt.Errorf("only the keeper takes a keeper_delay block")
			} else {
				f.KeeperDelay, err = parseKeeperDelay(v)
			}
		default:
			err = fmt.Errorf("unknown field")
		}
		if err != nil {
			return nil, fmt.Errorf("directive %s: %w", k, err)
		}
	}
	if f.KeeperDelay != nil && f.WorstPath == nil {
		return nil, fmt.Errorf("directive: keeper_delay needs the worst_path block that names the call it delays")
	}
	return f, nil
}

func strictDecode(raw []byte, v any) error {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err := dec.Decode(v); err != nil {
		return err
	}
	if dec.More() {
		return fmt.Errorf("trailing data")
	}
	return nil
}

func parseWorstPath(raw json.RawMessage, role string) (*WorstPath, error) {
	var m map[string]any
	if err := strictDecode(raw, &m); err != nil {
		return nil, err
	}
	w := &WorstPath{Role: role}
	want := expected[role]
	common := map[string]bool{"judgment_path": true, "applies_to": true, "case_horizon": true}
	var missing []string
	for k := range want {
		if _, ok := m[k]; !ok {
			missing = append(missing, k)
		}
	}
	for k := range common {
		if _, ok := m[k]; !ok {
			missing = append(missing, k)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		return nil, fmt.Errorf("missing %v", missing)
	}
	for k, v := range m {
		switch {
		case k == "judgment_path":
			if v != "worst" {
				return nil, fmt.Errorf("judgment_path %v, want worst", v)
			}
		case k == "applies_to":
			if v != AppliesTo {
				return nil, fmt.Errorf("applies_to %q, want %q", v, AppliesTo)
			}
		case k == "case_horizon":
			n, err := uintValue(v)
			if err != nil || n == 0 {
				return nil, fmt.Errorf("case_horizon must be a positive integer")
			}
			w.CaseHorizon = n
		default:
			fixed, ok := want[k]
			if !ok {
				return nil, fmt.Errorf("unknown key %q for the %s", k, role)
			}
			if fixed != nil {
				if v != fixed {
					return nil, fmt.Errorf("%s = %v, the %s carries out only %v", k, v, role, fixed)
				}
				continue
			}
			if err := w.setVerifier(k, v); err != nil {
				return nil, err
			}
		}
	}
	return w, nil
}

func (w *WorstPath) setVerifier(k string, v any) error {
	switch k {
	case "max_replaced_assignments":
		n, err := uintValue(v)
		if err != nil || n > 254 {
			return fmt.Errorf("max_replaced_assignments must be an integer in 0..254")
		}
		w.MaxReplacedAssignments = uint8(n)
		return nil
	}
	s, ok := v.(string)
	if !ok || (s != "PASS" && s != "FAIL" && s != "INCONCLUSIVE") {
		return fmt.Errorf("%s must be PASS, FAIL or INCONCLUSIVE", k)
	}
	switch k {
	case "initial_verdict":
		w.InitialVerdict = s
	case "party_review_verdict":
		w.PartyReviewVerdict = s
	case "tiebreak_verdict":
		w.TiebreakVerdict = s
	}
	return nil
}

func parseKeeperDelay(raw json.RawMessage) (*KeeperDelay, error) {
	var m map[string]any
	if err := strictDecode(raw, &m); err != nil {
		return nil, err
	}
	d := &KeeperDelay{}
	seen := map[string]bool{}
	for k, v := range m {
		seen[k] = true
		switch k {
		case "budget_blocks":
			n, err := uintValue(v)
			if err != nil {
				return nil, fmt.Errorf("budget_blocks must be a non-negative integer")
			}
			d.BudgetBlocks = n
		case "per":
			if v != "case" {
				return nil, fmt.Errorf("per %v, want case", v)
			}
		case "spent_on":
			if v != KeeperDelaySpentOn {
				return nil, fmt.Errorf("spent_on %v, want %q", v, KeeperDelaySpentOn)
			}
		case "other_calls":
			if v != "prompt" {
				return nil, fmt.Errorf("other_calls %v, want prompt", v)
			}
		case "expected_kappa_sigma":
		default:
			return nil, fmt.Errorf("unknown key %q", k)
		}
	}
	for _, k := range []string{"budget_blocks", "per", "spent_on", "other_calls"} {
		if !seen[k] {
			return nil, fmt.Errorf("missing %s", k)
		}
	}
	if v, ok := m["expected_kappa_sigma"]; ok {
		n, err := uintValue(v)
		if err != nil || n != d.BudgetBlocks {
			return nil, fmt.Errorf("expected_kappa_sigma must equal budget_blocks")
		}
	}
	return d, nil
}

func uintValue(v any) (uint64, error) {
	n, ok := v.(json.Number)
	if !ok {
		return 0, fmt.Errorf("not a number")
	}
	var out uint64
	if _, err := fmt.Sscan(n.String(), &out); err != nil || n.String() != fmt.Sprint(out) {
		return 0, fmt.Errorf("not a non-negative integer")
	}
	return out, nil
}

// StageVerdict returns the verdict the verifier block assigns to a stage
// (1 initial, 2 party review, 4 tiebreak), or "" when the block names none.
func (w *WorstPath) StageVerdict(stage uint8) string {
	switch stage {
	case 1:
		return w.InitialVerdict
	case 2:
		return w.PartyReviewVerdict
	case 4:
		return w.TiebreakVerdict
	}
	return ""
}
