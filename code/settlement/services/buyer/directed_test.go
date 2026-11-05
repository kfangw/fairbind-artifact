package buyer

import (
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/testworld"
)

func TestClaimAfterCase(t *testing.T) {
	for s := uint8(0); s <= chain.CaseFinal; s++ {
		want := s == chain.CaseNone || s == chain.CaseDelivered || s == chain.CaseUnserved || s == chain.CaseInconclusive || s == chain.CaseFinal
		if claimAfterCase(s) != want {
			t.Errorf("case state %d: claim %v, want %v", s, !want, want)
		}
	}
}

// Under the worst-path directive a frozen-bond claim waits until the
// purchase's own case has ended.
func TestWorstPathClaimWaitsForTheCase(t *testing.T) {
	h := newHarness(t)
	h.worst = true
	h.restart()
	r, _ := h.b.Buy(ctx, h.req())
	h.anchor(0)
	r = h.advance(r.Key.String())
	h.mustState(r, StateProven)
	nonce := protocol.Bytes32(*r.Nonce)
	h.w.Fake.OpenCaseForTest(nonce, chain.Case{State: chain.CaseJudging, Trigger: chain.TriggerSample})
	h.w.Fake.FreezeBond(testworld.BondID, 100)
	r = h.advance(r.Key.String())
	h.mustState(r, StateProven)
	if h.w.Fake.Calls("ClaimRefundWithReceipt") != 0 {
		t.Fatal("claimed while the case is open")
	}
	h.w.Fake.OpenCaseForTest(nonce, chain.Case{State: chain.CaseFinal, Trigger: chain.TriggerSample})
	r = h.advance(r.Key.String())
	h.mustState(r, StateRefunded)
}

// Under the worst-path directive an undelivered purchase opens no dispute.
func TestWorstPathOpensNoDispute(t *testing.T) {
	h := newHarness(t)
	h.worst = true
	h.restart()
	h.stub.setMode("withhold")
	r, _ := h.b.Buy(ctx, h.req())
	h.w.Fake.MineTo(h.w.Profile.EpochOrigin + uint64(h.w.Profile.Deadlines.ResponseBlocks) + 2)
	r = h.advance(r.Key.String())
	h.mustState(r, StateOffered)
	if h.w.Fake.Calls("Dispute") != 0 {
		t.Fatal("dispute opened")
	}
}
