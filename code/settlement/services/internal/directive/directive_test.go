package directive

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// Blocks as experiments/controller/worstpath.py writes them for data-api-fast-v1.
const (
	verifierBlock = `{"applies_to": "every sampled bad sale", "case_horizon": 31073,
 "disclose_evidence_on_initial_last_assignment_at": "evidence_deadline",
 "disclose_evidence_on_initial_non_last_assignments": false,
 "escalate_at": "challenge_deadline",
 "initial_non_last_assignments": "deliver FAIL at the judge deadline; voided by timeoutEvidence in the block after the evidence deadline",
 "initial_verdict": "FAIL", "judgment_path": "worst", "max_replaced_assignments": 2,
 "party_review_verdict": "PASS", "request_serve_at": "judge_deadline",
 "review_non_last_assignments": "time out at the judge deadline", "tiebreak_verdict": "FAIL",
 "verdict_at": "judge_deadline"}`
	sellerBlock = `{"anchor_at": "anchor_deadline", "appeal_initial_fail_at": "renewed_appeal_deadline",
 "applies_to": "every sampled bad sale", "case_horizon": 31073, "judgment_path": "worst",
 "publish_at": "publication_deadline", "redeliver_at": "serve_deadline", "request_evidence_at": "appeal_deadline"}`
	keeperBlock = `{"applies_to": "every sampled bad sale", "call_at": "deadline", "case_horizon": 31073,
 "judgment_path": "worst", "open_sample_at": "open_window_end",
 "review_seal": "let the first seal window of every review stage lapse, then seal the reopened stage"}`
	buyerBlock = `{"applies_to": "every sampled bad sale", "case_horizon": 31073, "claim_at": "after_case_final",
 "dispute_sampled_sale": false, "judgment_path": "worst"}`
	delayBlock = `{"budget_blocks": 100, "expected_kappa_sigma": 100, "other_calls": "prompt", "per": "case",
 "spent_on": "last keeper call before the confirmed failure of each case"}`
)

func TestParseRoles(t *testing.T) {
	v, err := Parse([]byte(`{"seed": 7, "kind": null, "parameters": {}, "worst_path": `+verifierBlock+`}`), RoleVerifier)
	if err != nil {
		t.Fatal(err)
	}
	w := v.WorstPath
	if w == nil || w.CaseHorizon != 31073 || w.MaxReplacedAssignments != 2 {
		t.Fatalf("verifier block %+v", w)
	}
	if w.StageVerdict(1) != "FAIL" || w.StageVerdict(2) != "PASS" || w.StageVerdict(4) != "FAIL" || w.StageVerdict(3) != "" {
		t.Fatalf("stage verdicts %q %q %q", w.StageVerdict(1), w.StageVerdict(2), w.StageVerdict(4))
	}
	for role, block := range map[string]string{RoleSeller: sellerBlock, RoleKeeper: keeperBlock, RoleBuyer: buyerBlock} {
		f, err := Parse([]byte(`{"kind": "hold_period_grid", "parameters": {"scale_factor": 1}, "worst_path": `+block+`}`), role)
		if err != nil || f.WorstPath == nil || f.WorstPath.Role != role {
			t.Fatalf("%s: %v %+v", role, err, f)
		}
	}
	k, err := Parse([]byte(`{"kind": null, "worst_path": `+keeperBlock+`, "keeper_delay": `+delayBlock+`}`), RoleKeeper)
	if err != nil || k.KeeperDelay == nil || k.KeeperDelay.BudgetBlocks != 100 {
		t.Fatalf("keeper delay: %v %+v", err, k)
	}
}

func TestParseDefaultsWithoutBlocks(t *testing.T) {
	f, err := Parse([]byte(`{"seed": 1, "kind": null, "parameters": {"retries": 3}}`), RoleSeller)
	if err != nil || f.WorstPath != nil || f.KeeperDelay != nil {
		t.Fatalf("%v %+v", err, f)
	}
	if f, err := Load("", RoleKeeper); f != nil || err != nil {
		t.Fatalf("empty path: %v %v", f, err)
	}
}

func TestParseRejects(t *testing.T) {
	cases := map[string]struct{ role, doc, want string }{
		"another role's block":  {RoleSeller, `{"worst_path": ` + keeperBlock + `}`, "missing"},
		"extra key":             {RoleSeller, `{"worst_path": ` + strings.Replace(sellerBlock, `"anchor_at"`, `"call_at": "deadline", "anchor_at"`, 1) + `}`, "unknown key"},
		"changed timing":        {RoleSeller, `{"worst_path": ` + strings.Replace(sellerBlock, `"serve_deadline"`, `"serve_start"`, 1) + `}`, "carries out only"},
		"missing key":           {RoleBuyer, `{"worst_path": ` + strings.Replace(buyerBlock, `"claim_at": "after_case_final",`, ``, 1) + `}`, "missing"},
		"other judgment path":   {RoleKeeper, `{"worst_path": ` + strings.Replace(keeperBlock, `"judgment_path": "worst"`, `"judgment_path": "best"`, 1) + `}`, "judgment_path"},
		"verdict name":          {RoleVerifier, `{"worst_path": ` + strings.Replace(verifierBlock, `"tiebreak_verdict": "FAIL"`, `"tiebreak_verdict": "fail"`, 1) + `}`, "PASS, FAIL or INCONCLUSIVE"},
		"negative budget":       {RoleKeeper, `{"worst_path": ` + keeperBlock + `, "keeper_delay": ` + strings.Replace(strings.Replace(delayBlock, "100", "-5", 1), "100", "-5", 1) + `}`, "budget_blocks"},
		"kappa sigma mismatch":  {RoleKeeper, `{"worst_path": ` + keeperBlock + `, "keeper_delay": ` + strings.Replace(delayBlock, `"expected_kappa_sigma": 100`, `"expected_kappa_sigma": 99`, 1) + `}`, "expected_kappa_sigma"},
		"delay without path":    {RoleKeeper, `{"keeper_delay": ` + delayBlock + `}`, "needs the worst_path"},
		"delay for the seller":  {RoleSeller, `{"worst_path": ` + sellerBlock + `, "keeper_delay": ` + delayBlock + `}`, "only the keeper"},
		"unknown top-level key": {RoleBuyer, `{"worst_paths": {}}`, "unknown field"},
		"trailing data":         {RoleBuyer, `{} {}`, "trailing"},
		"unknown role":          {"facilitator", `{}`, "unknown role"},
	}
	for name, c := range cases {
		_, err := Parse([]byte(c.doc), c.role)
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: error %v, want it to mention %q", name, err, c.want)
		}
	}
}

func TestWriteProgress(t *testing.T) {
	path := filepath.Join(t.TempDir(), "progress.json")
	if err := WriteProgress(path, 41); err != nil {
		t.Fatal(err)
	}
	if err := WriteProgress(path, 42); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil || string(raw) != "{\"head\":42}\n" {
		t.Fatalf("%q %v", raw, err)
	}
	if err := WriteProgress("", 1); err != nil {
		t.Fatal(err)
	}
}
