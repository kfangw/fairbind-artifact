package seller

import (
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/testworld"
)

func TestReviewStep(t *testing.T) {
	fail := chain.CaseDetail{Case: chain.Case{State: chain.CaseInitialVerdict}, Stage: 1, InitialVerdict: chain.VerdictFail, AppealUntil: 5000}
	cases := []struct {
		name                string
		d                   chain.CaseDetail
		requested, appealed bool
		next                uint64
		want                string
	}{
		{"before the appeal deadline", fail, false, false, 4999, reviewNone},
		{"request at the appeal deadline", fail, false, false, 5000, reviewRequestEvidence},
		{"after the appeal deadline", fail, false, false, 5001, reviewNone},
		{"appeal at the renewed deadline", fail, true, false, 5000, reviewAppeal},
		{"appealed already", fail, true, true, 5000, reviewNone},
		{"evidence pending", func() chain.CaseDetail { d := fail; d.EvidenceDue = 5300; return d }(), true, false, 5000, reviewNone},
		{"initial PASS", func() chain.CaseDetail { d := fail; d.InitialVerdict = 1; return d }(), false, false, 5000, reviewNone},
		{"review stage", func() chain.CaseDetail { d := fail; d.Stage = 2; return d }(), false, false, 5000, reviewNone},
		{"already on a review path", func() chain.CaseDetail { d := fail; d.ReviewPath = 1; return d }(), true, false, 5000, reviewNone},
		{"judging", func() chain.CaseDetail { d := fail; d.State = chain.CaseJudging; return d }(), false, false, 5000, reviewNone},
	}
	for _, c := range cases {
		if got := reviewStep(c.d, c.requested, c.appealed, c.next); got != c.want {
			t.Errorf("%s: %q, want %q", c.name, got, c.want)
		}
	}
	if publicationCalls(protocol.ResponseChunkBytes) != 1 || publicationCalls(protocol.ResponseChunkBytes+1) != 4 {
		t.Fatal("publication call count")
	}
}

// On the worst path the seller anchors at the anchor deadline, serves at the
// serve deadline, publishes at the publication deadline, requests evidence at
// the appeal deadline and appeals at the renewed one; a call made at block b
// lands in b + 1, so each is sent one block before its deadline.
func TestWorstPathSellerSchedule(t *testing.T) {
	h := &harness{t: t, w: testworld.New(), dir: t.TempDir(), worst: true}
	h.fac = &stubFacilitator{w: h.w}
	h.start()
	t.Cleanup(func() { h.stop() })
	p, resp, _ := h.buy("/v1/quote", protocol.Bytes16{40})
	if resp.StatusCode != 200 {
		t.Fatal(resp.StatusCode)
	}
	tickAt := func(b uint64) {
		t.Helper()
		h.w.Fake.MineTo(b)
		if err := h.s.Tick(ctx); err != nil {
			t.Fatal(err)
		}
	}
	calls := func(method string, want int) {
		t.Helper()
		if got := h.w.Fake.Calls(method); got != want {
			t.Fatalf("%s called %d times, want %d", method, got, want)
		}
	}
	deadline := h.w.Profile.AnchorDeadline(0)
	tickAt(h.w.Profile.AnchorBase(0))
	tickAt(deadline - 2)
	calls("Anchor", 0)
	tickAt(deadline - 1)
	calls("Anchor", 1)

	fake := h.w.Fake
	fake.OpenCaseForTest(p.nonce, chain.Case{State: chain.CaseServeWait, Trigger: chain.TriggerSample, ServeDue: deadline + 300})
	tickAt(deadline + 298)
	calls("Served", 0)
	tickAt(deadline + 299)
	calls("Served", 1)

	appeal := deadline + 2000
	fake.OpenCaseForTest(p.nonce, chain.Case{State: chain.CaseInitialVerdict, Trigger: chain.TriggerSample})
	fake.SetCaseDetailForTest(p.nonce, chain.CaseDetail{Stage: 1, Attempt: 2, InitialVerdict: chain.VerdictFail, AppealUntil: appeal})
	tickAt(appeal - 2)
	calls("RequestEvidence", 0)
	tickAt(appeal - 1)
	calls("RequestEvidence", 1)
	h.restart() // the request is persisted with the purchase record
	// The verifier disclosed the evidence: no evidence deadline, a renewed appeal window.
	renewed := appeal + 2100
	fake.SetCaseDetailForTest(p.nonce, chain.CaseDetail{Stage: 1, Attempt: 2, InitialVerdict: chain.VerdictFail, AppealUntil: renewed})
	tickAt(renewed - 2)
	calls("Appeal", 0)
	tickAt(renewed - 1)
	calls("Appeal", 1)
	calls("RequestEvidence", 1)
	rec, _ := h.s.Record(p.nonce)
	if rec.Directed == nil || !rec.Directed.Appealed || len(rec.Directed.EvidenceRequested) != 1 || rec.Directed.EvidenceRequested[0] != "1:2" {
		t.Fatalf("progress %+v", rec.Directed)
	}
	// A dispute-opened case keeps the default: served at once.
	fake.OpenCaseForTest(p.nonce, chain.Case{State: chain.CaseServeWait, Trigger: chain.TriggerNonDelivery, ServeDue: renewed + 300})
	tickAt(renewed + 1)
	calls("Served", 2)
	// Publication last: the fake ends the case as delivered, and the record is
	// then pruned.
	due := renewed + 600
	fake.OpenCaseForTest(p.nonce, chain.Case{State: chain.CasePublishing, Trigger: chain.TriggerSample, PublishDue: due})
	tickAt(due - 2)
	calls("Publish", 0)
	tickAt(due - 1)
	calls("Publish", 1)
}
