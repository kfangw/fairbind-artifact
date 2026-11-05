package keeper

import (
	"context"
	"strings"
	"testing"

	"example.org/fairbind/protocol"
)

// directedChain adds the latest-block and reseal views of the worst-path
// directive to the fake. Under the directive the fake's head is the latest
// block and a call sent at head lands in head + 1.
type directedChain struct {
	*fakeChain
	reseals   map[protocol.Bytes32]uint8
	resealDue map[protocol.Bytes32]uint64
}

func (d *directedChain) Latest(ctx context.Context) (Block, error) { return d.Finalized(ctx) }
func (d *directedChain) ReviewReseals(_ context.Context, _ Block, n protocol.Bytes32) (uint8, error) {
	return d.reseals[n], nil
}
func (d *directedChain) ReviewResealDue(_ context.Context, _ Block, n protocol.Bytes32) (uint64, error) {
	return d.resealDue[n], nil
}

func directedKeeper(t *testing.T, delay uint64) (*directedChain, *fakeSender, *Keeper) {
	f := newFake()
	f.timing.SealBlocks, f.timing.MaxAssignments, f.timing.FreezeOnInitialFail = 200, 3, false
	d := &directedChain{fakeChain: f, reseals: map[protocol.Bytes32]uint8{}, resealDue: map[protocol.Bytes32]uint64{}}
	s := &fakeSender{}
	k := newKeeper(t, f, s, "")
	k.Chain, k.WorstPath, k.DelayBlocks = d, true, delay
	return d, s, k
}

func lastDue(t *testing.T, rep Report, name string) uint64 {
	t.Helper()
	for _, o := range rep.Outcomes {
		if o.Action.Name == name && o.Status == "sent" {
			return o.Action.Due
		}
	}
	t.Fatalf("no sent %s in %+v", name, rep.Outcomes)
	return 0
}

// The worst path seals in the last block of the seal window and opens the
// sample in the last block of the open window.
func TestWorstPathSealAndOpenAtWindowEnd(t *testing.T) {
	d, s, k := directedKeeper(t, 0)
	n := d.settle("a")
	d.anchors[epochKey(1, 0)] = Anchor{State: epochAnchored, RandomBlock: 1800, SealDeadline: 2000}
	d.head = 1998 // a call now lands in 1999
	tick(t, k)
	equal(t, s.names())
	d.head = 1999
	if due := lastDue(t, tick(t, k), ActSeal); due != 2000 {
		t.Fatalf("seal due %d", due)
	}
	d.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, RandomBlock: 1800, SealDeadline: 2000}
	d.sampled[n] = true
	d.head = 2198
	tick(t, k)
	equal(t, s.names(), ActSeal)
	d.head = 2199
	rep := tick(t, k)
	if due := lastDue(t, rep, ActOpenSample); due != 2200 {
		t.Fatalf("openSample due %d", due)
	}
	for _, o := range rep.Outcomes {
		if o.Action.Name == ActOpenSample && o.Action.Nonce != hexKey(n) {
			t.Fatalf("openSample names case %s", o.Action.Nonce)
		}
	}
}

// Timeouts land in the block after their deadline: the keeper reads the latest
// block and sends when the next block is past the deadline.
func TestWorstPathPromptTimeouts(t *testing.T) {
	d, s, k := directedKeeper(t, 0)
	n := d.settle("a")
	d.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2000}
	d.states[n] = finHeld
	d.cases[n] = Case{State: caseJudging, Trigger: triggerSample, Stage: 1, AssignedVerifierID: 4, JudgeDue: 3000}
	d.head = 2999
	tick(t, k)
	equal(t, s.names())
	d.head = 3000
	if due := lastDue(t, tick(t, k), ActTimeoutJudge); due != 3001 {
		t.Fatalf("timeoutJudge due %d", due)
	}
	d.cases[n] = Case{State: caseInitialVerdict, Trigger: triggerSample, Stage: 1, Attempt: 1, InitialVerdict: verdictFail, EvidenceDue: 3500, RandomBlock: 5000}
	d.head = 3499
	tick(t, k)
	d.head = 3500
	if due := lastDue(t, tick(t, k), ActTimeoutEvidence); due != 3501 {
		t.Fatalf("timeoutEvidence due %d", due)
	}
	equal(t, s.names(), ActTimeoutJudge, ActTimeoutEvidence)
}

// The first seal window of a review stage lapses: finalizeCase in the block
// after it reopens the seal with the same randomBlock, which is then sealed in
// the last block of the reopened window the contract recorded (ADR 0025). A
// case not opened by sampling keeps the default.
func TestWorstPathReviewSealLapsesOnce(t *testing.T) {
	d, s, k := directedKeeper(t, 0)
	n := d.settle("a")
	d.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2000}
	d.states[n] = finHeld
	d.cases[n] = Case{State: casePartyReview, Trigger: triggerSample, Stage: 2, RandomBlock: 4100}
	for _, h := range []uint64{4100, 4200, 4299} {
		d.head = h
		tick(t, k)
	}
	equal(t, s.names())
	d.head = 4300
	if due := lastDue(t, tick(t, k), ActFinalizeCase); due != 4301 {
		t.Fatalf("lapse due %d", due)
	}
	d.reseals[n] = 1 << 2
	d.resealDue[n] = 4301 + 1 + 200
	d.cases[n] = Case{State: casePartyReview, Trigger: triggerSample, Stage: 2, RandomBlock: 4100}
	d.head = 4500
	tick(t, k)
	equal(t, s.names(), ActFinalizeCase)
	d.head = 4501
	if due := lastDue(t, tick(t, k), ActSealReviewRandomness); due != 4502 {
		t.Fatalf("reopened seal due %d", due)
	}
	// A dispute-opened case (trigger WRONG_DELIVERY) is sealed as by default.
	d.cases[n] = Case{State: caseFinal}
	m := nonceOf("b")
	d.logs[4550] = []Settlement{{Nonce: m, SellerID: 1, BondID: 5, ProfileID: 3, Epoch: 0}}
	d.purchases[m] = Purchase{FinancialState: finHeld}
	d.states[m] = finHeld
	d.cases[m] = Case{State: casePartyReview, Trigger: 3, Stage: 2, RandomBlock: 4600}
	d.head = 4600
	rep := tick(t, k)
	for _, o := range rep.Outcomes {
		if o.Action.Nonce == hexKey(m) && o.Action.Name != ActSealReviewRandomness {
			t.Fatalf("dispute case got %s", o.Action.Name)
		}
	}
	if lastDue(t, rep, ActSealReviewRandomness) != 4601 {
		t.Fatal("dispute case not sealed at once")
	}
}

// The keeper delay budget is spent on the timeoutJudge that replaces the
// next-to-last tiebreak assignment; every other call is prompt.
func TestWorstPathKeeperDelayOnLastCall(t *testing.T) {
	d, s, k := directedKeeper(t, 100)
	n := d.settle("a")
	d.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2000}
	d.states[n] = finHeld
	// Party review, attempt 1 of 3: not the delayed call.
	d.cases[n] = Case{State: casePartyReview, Trigger: triggerSample, Stage: 2, Attempt: 1, AssignedVerifierID: 4, JudgeDue: 4000}
	d.head = 4000
	tick(t, k)
	equal(t, s.names(), ActTimeoutJudge)
	// Tiebreak, attempt 0: prompt.
	d.cases[n] = Case{State: caseTiebreak, Trigger: triggerSample, Stage: 4, Attempt: 0, AssignedVerifierID: 5, JudgeDue: 5000}
	d.head = 5000
	tick(t, k)
	equal(t, s.names(), ActTimeoutJudge, ActTimeoutJudge)
	// Tiebreak, attempt 1: the replacement of the last assignment, delayed by 100.
	d.cases[n] = Case{State: caseTiebreak, Trigger: triggerSample, Stage: 4, Attempt: 1, AssignedVerifierID: 6, JudgeDue: 6000}
	for _, h := range []uint64{6000, 6050, 6099} {
		d.head = h
		tick(t, k)
	}
	equal(t, s.names(), ActTimeoutJudge, ActTimeoutJudge)
	d.head = 6100 // lands in 6101 = due 6001 + 100
	if due := lastDue(t, tick(t, k), ActTimeoutJudge); due != 6001 {
		t.Fatalf("delayed call due %d", due)
	}
}

// With one assignment per stage the last keeper call is the reopened tiebreak seal.
func TestWorstPathKeeperDelaySingleAssignment(t *testing.T) {
	d, s, k := directedKeeper(t, 30)
	d.timing.MaxAssignments = 1
	n := d.settle("a")
	d.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2000}
	d.states[n] = finHeld
	d.reseals[n] = 1 << 4
	d.resealDue[n] = 7200
	d.cases[n] = Case{State: caseTiebreak, Trigger: triggerSample, Stage: 4, RandomBlock: 6799}
	d.head = 7199
	tick(t, k)
	d.head = 7228
	tick(t, k)
	equal(t, s.names())
	d.head = 7229
	if due := lastDue(t, tick(t, k), ActSealReviewRandomness); due != 7200 {
		t.Fatalf("seal due %d", due)
	}
}

func TestWorstPathNeedsLatestViews(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	k := newKeeper(t, f, s, "")
	k.WorstPath = true
	if _, err := k.Tick(context.Background()); err == nil || !strings.Contains(err.Error(), "latest-block") {
		t.Fatalf("error %v", err)
	}
}

// Under the directive without a receipt list the keeper leaves the receipt
// calls alone, so that the case stays on its worst path; with one it submits
// the receipt in the deadline block.
func TestWorstPathReceiptCallsNeedTheList(t *testing.T) {
	d, s, k := directedKeeper(t, 0)
	n := d.settle("a")
	d.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2000}
	d.states[n] = finHeld
	d.cases[n] = Case{State: caseJudging, Trigger: triggerSample, AssignedVerifierID: 3, JudgeDue: 2800, SampleReceiptDue: 2500}
	d.head = 2600
	tick(t, k)
	equal(t, s.names())
	d.cases[n] = Case{State: caseJudging, Trigger: triggerSample, AssignedVerifierID: 3, JudgeDue: 2800, SampleReceiptDue: 2700}
	k.Receipts = receiptList{n: signedReceipt(n)}
	d.head = 2698
	tick(t, k)
	equal(t, s.names())
	d.head = 2699 // lands in the deadline block
	tick(t, k)
	equal(t, s.names(), ActSubmitSampleReceipt)
}
