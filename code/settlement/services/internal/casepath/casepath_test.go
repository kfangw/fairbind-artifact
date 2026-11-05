package casepath

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

type fakeChain struct {
	logs  map[string][]Log // by signature
	cases map[string][]uint64
	txs   map[string]uint64
}

func (f *fakeChain) Logs(_ context.Context, sig string, topics ...*string) ([]Log, error) {
	var out []Log
	for _, l := range f.logs[sig] {
		ok := true
		for i, t := range topics {
			if t != nil && (i+1 >= len(l.Topics) || l.Topics[i+1] != *t) {
				ok = false
			}
		}
		if ok {
			out = append(out, l)
		}
	}
	return out, nil
}
func (f *fakeChain) Case(_ context.Context, n string) ([]uint64, error) {
	if w, ok := f.cases[n]; ok {
		return w, nil
	}
	return make([]uint64, 23), nil
}
func (f *fakeChain) MaxAssignments(context.Context, uint32) (uint64, error) { return 3, nil }
func (f *fakeChain) TxBlock(_ context.Context, tx string) (uint64, error) {
	b, ok := f.txs[tx]
	if !ok {
		return 0, ErrReverted
	}
	return b, nil
}

func (f *fakeChain) add(sig string, block uint64, topics []string, data ...uint64) {
	if f.logs == nil {
		f.logs = map[string][]Log{}
	}
	f.logs[sig] = append(f.logs[sig], Log{Block: block, Topics: append([]string{"0xsig"}, topics...), Data: data})
}

// worstCase records the events of one case on the worst path for m = 3.
func worstCase(f *fakeChain, nonce string, settled, confirmed uint64) {
	seller := word(1)
	f.add(evSettled, settled, []string{nonce, "0xkey", seller}, 5, 3, ^uint64(0), 10000, 1)
	f.add(evCaseOpened, settled+1868, []string{nonce}, 1, ^uint64(0), 10000)
	for _, st := range []uint64{1, 2, 4} {
		for a := uint64(0); a < 3; a++ {
			f.add(evVerifierAssigned, settled+2000, []string{nonce, word(7)}, st, a, 0)
			f.add(evServeRequested, settled+2000, []string{nonce, "0xreq"}, 0, 0)
		}
	}
	for a := uint64(0); a < 3; a++ {
		f.add(evEvidenceRequested, settled+3000, []string{nonce}, 1, a, 0)
		f.add(evVerdictSubmitted, settled+3000, []string{nonce, word(7)}, 1, verdictFail, 0)
	}
	f.add(evEvidenceDisclosed, settled+9000, []string{nonce}, 1, 2, 0)
	f.add(evReviewResealed, settled+16000, []string{nonce}, 2, 0)
	f.add(evReviewResealed, settled+23000, []string{nonce}, 4, 0)
	f.add(evVerdictSubmitted, settled+22000, []string{nonce, word(7)}, 2, verdictPass, 0)
	f.add(evVerdictSubmitted, confirmed, []string{nonce, word(7)}, 4, verdictFail, 0)
	f.add(evCaseFinalized, confirmed, []string{nonce}, verdictFail, 3)
	w := make([]uint64, 23)
	w[15], w[22] = caseFinal, verdictFail
	f.cases[nonce] = w
}

func TestCollectWorstPathCase(t *testing.T) {
	f := &fakeChain{cases: map[string][]uint64{}, txs: map[string]uint64{"0xa": 1300, "0xb": 11101, "0xc": 30000, "0xd": 1400}}
	worstCase(f, "0x01", 1300, 1300+29780)
	// A settled purchase whose case never opened, and a PASS case: not effective detections.
	f.add(evSettled, 1400, []string{"0x02", "0xkey", word(1)}, 5, 3, 0, 10000, 1)
	calls := []KeeperCall{
		{Action: "seal", Tx: "0xa", Due: 1300, Epoch: "1:1"},                 // before the settlement block of the case: not on its path
		{Action: "timeoutJudge", Tx: "0xb", Due: 11001, Nonce: "0x01"},       // delayed by 100
		{Action: "timeoutJudge", Tx: "0xc", Due: 30000, Nonce: "0x01"},       // prompt
		{Action: "timeoutEvidence", Tx: "0xreverted", Due: 5, Nonce: "0x01"}, // reverted: skipped
		{Action: "openSample", Tx: "0xd", Due: 1400, Nonce: "0x02"},          // another case
	}
	cases, err := Collect(context.Background(), f, 1, calls)
	if err != nil {
		t.Fatal(err)
	}
	if len(cases) != 1 {
		t.Fatalf("%d cases", len(cases))
	}
	c := cases[0]
	if c.CasePathBlocks != 29780 || c.KeeperDelaySum != 100 || c.CasePathMinusKeeper != 29680 || !c.WorstPath || c.Outcome != "FAIL" {
		t.Fatalf("case %+v", c)
	}
	if len(c.KeeperCalls) != 3 {
		t.Fatalf("keeper calls on the path %+v", c.KeeperCalls)
	}
	var buf bytes.Buffer
	if err := WriteRows(&buf, Rows("run-1", cases, true)); err != nil {
		t.Fatal(err)
	}
	want := map[string]string{"case_path_blocks": "[29780]", "keeper_delay_sum_blocks": "[100]",
		"case_path_minus_keeper": "[29680]", "worst_path_case_blocks": "[29680]"}
	for _, line := range strings.Split(strings.TrimSpace(buf.String()), "\n") {
		var r struct {
			Metric string          `json:"metric"`
			Value  json.RawMessage `json:"value"`
			ID     string          `json:"observation_id"`
		}
		if err := json.Unmarshal([]byte(line), &r); err != nil {
			t.Fatal(err)
		}
		if w, ok := want[r.Metric]; ok {
			if string(r.Value) != w || r.ID != "run-1" {
				t.Fatalf("%s = %s (%s), want %s", r.Metric, r.Value, r.ID, w)
			}
			delete(want, r.Metric)
		}
	}
	if len(want) != 0 {
		t.Fatalf("missing rows %v", want)
	}
}

func TestWorstPathMismatchNamesTheDifference(t *testing.T) {
	f := &fakeChain{cases: map[string][]uint64{}}
	worstCase(f, "0x01", 1300, 25000)
	f.logs[evEvidenceDisclosed] = nil // nobody disclosed: the case would have ended INCONCLUSIVE on the contract
	f.logs[evReviewResealed] = f.logs[evReviewResealed][:1]
	cases, err := Collect(context.Background(), f, 1, nil)
	if err != nil {
		t.Fatal(err)
	}
	c := cases[0]
	if c.WorstPath || fmt.Sprint(c.WorstPathMismatch) != "[evidence disclosures: 0, want 1 review reseals: 1, want 2]" {
		t.Fatalf("mismatch %v", c.WorstPathMismatch)
	}
	if rows := Rows("r", cases, true); fmt.Sprint(rows[len(rows)-1].Value) != "[]" {
		t.Fatalf("worst_path_case_blocks %v", rows[len(rows)-1].Value)
	}
}

func TestParseKeeperLog(t *testing.T) {
	log := `{"action":"seal","status":"sent","tx":"0xAB","due":10,"epoch":"1:0","nonce":""}
{"action":"timeoutJudge","status":"rejected","tx":"","due":11}
not json
{"error":"rpc"}
{"action":"timeoutJudge","status":"sent","tx":"0xcd","due":12,"nonce":"0xEF","event":"call_sent"}`
	calls, err := ParseKeeperLog(strings.NewReader(log))
	if err != nil {
		t.Fatal(err)
	}
	if len(calls) != 2 || calls[0].Tx != "0xab" || calls[1].Nonce != "0xef" || calls[1].Due != 12 {
		t.Fatalf("%+v", calls)
	}
}
