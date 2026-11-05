package keeper

import (
	"context"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"example.org/fairbind/protocol"
)

type fakeChain struct {
	head       uint64
	logs       map[uint64][]Settlement
	logQueries [][2]uint64
	timing     Timing
	purchases  map[protocol.Bytes32]Purchase
	states     map[protocol.Bytes32]uint8
	cases      map[protocol.Bytes32]Case
	sampled    map[protocol.Bytes32]bool
	anchors    map[string]Anchor
	bonds      map[uint32]Bond
	reject     func([]byte) error
}

func newFake() *fakeChain {
	return &fakeChain{
		logs:      map[uint64][]Settlement{},
		timing:    Timing{EpochOrigin: 1000, EpochBlocks: 300, AnchorBlocks: 100, OpenBlocks: 200, FreezeOnInitialFail: true},
		purchases: map[protocol.Bytes32]Purchase{}, states: map[protocol.Bytes32]uint8{},
		cases: map[protocol.Bytes32]Case{}, sampled: map[protocol.Bytes32]bool{},
		anchors: map[string]Anchor{}, bonds: map[uint32]Bond{},
	}
}

func (f *fakeChain) Finalized(context.Context) (Block, error) {
	return Block{Number: f.head, Hash: protocol.Keccak256([]byte(fmt.Sprint(f.head)))}, nil
}
func (f *fakeChain) Settlements(_ context.Context, from, to uint64) ([]Settlement, error) {
	f.logQueries = append(f.logQueries, [2]uint64{from, to})
	var out []Settlement
	for b := from; b <= to; b++ {
		out = append(out, f.logs[b]...)
	}
	return out, nil
}
func (f *fakeChain) Timing(context.Context, Block, uint32) (Timing, error) { return f.timing, nil }
func (f *fakeChain) Purchase(_ context.Context, _ Block, n protocol.Bytes32) (Purchase, error) {
	return f.purchases[n], nil
}
func (f *fakeChain) PurchaseState(_ context.Context, _ Block, n protocol.Bytes32) (uint8, error) {
	return f.states[n], nil
}
func (f *fakeChain) Case(_ context.Context, _ Block, n protocol.Bytes32) (Case, error) {
	return f.cases[n], nil
}
func (f *fakeChain) Sampled(_ context.Context, _ Block, n protocol.Bytes32) (bool, bool, error) {
	return f.sampled[n], true, nil
}
func (f *fakeChain) Anchor(_ context.Context, _ Block, s, e uint32) (Anchor, error) {
	return f.anchors[epochKey(s, e)], nil
}
func (f *fakeChain) Bond(_ context.Context, _ Block, id uint32) (Bond, error) {
	return f.bonds[id], nil
}
func (f *fakeChain) Simulate(_ context.Context, data []byte) error {
	if f.reject != nil {
		return f.reject(data)
	}
	return nil
}

type fakeSender struct {
	sent [][]byte
	fail error
}

func (s *fakeSender) Send(_ context.Context, to protocol.Address, data []byte) (protocol.Bytes32, error) {
	if s.fail != nil {
		return protocol.Bytes32{}, s.fail
	}
	s.sent = append(s.sent, append([]byte{}, data...))
	return protocol.Keccak256(data, []byte(fmt.Sprint(len(s.sent)))), nil
}

func (s *fakeSender) names() []string {
	var out []string
	for _, d := range s.sent {
		out = append(out, selectorName(d))
	}
	return out
}

func selectorName(data []byte) string {
	for name, sig := range signatures {
		sel := protocol.Keccak256([]byte(sig))
		if hex.EncodeToString(sel[:4]) == hex.EncodeToString(data[:4]) {
			return name
		}
	}
	return "unknown:" + hex.EncodeToString(data[:4])
}

var contract = protocol.Address{0x11}

func nonceOf(s string) protocol.Bytes32 { return protocol.Keccak256([]byte(s)) }

// settle registers one settled purchase at block 1100 in epoch 0 of seller 1.
func (f *fakeChain) settle(name string) protocol.Bytes32 {
	n := nonceOf(name)
	f.logs[1100] = append(f.logs[1100], Settlement{Nonce: n, SellerID: 1, BondID: 5, ProfileID: 3, Epoch: 0})
	f.purchases[n] = Purchase{ClaimUntil: 3000, ReleaseBlock: 4000, RetainUntil: 4100, FinancialState: finDeferred}
	f.states[n] = finDeferred
	return n
}

func newKeeper(t *testing.T, f *fakeChain, s *fakeSender, path string) *Keeper {
	t.Helper()
	store, err := OpenStore(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	return &Keeper{Chain: f, Sender: s, Contract: contract, Store: store, ResendAfter: 10, MaxLogRange: 500, StartBlock: 1000}
}

func tick(t *testing.T, k *Keeper) Report {
	t.Helper()
	rep, err := k.Tick(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	return rep
}

func equal(t *testing.T, got []string, want ...string) {
	t.Helper()
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("sent %v, want %v", got, want)
	}
}

func TestTimeoutAnchorOnlyAfterInclusiveDeadline(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	f.settle("a")
	k := newKeeper(t, f, s, "")
	deadline := f.timing.AnchorDeadline(0)
	if deadline != 1000+2*300-1+100 {
		t.Fatalf("anchor deadline %d", deadline)
	}
	f.head = deadline
	tick(t, k)
	equal(t, s.names())
	f.head = deadline + 1
	tick(t, k)
	equal(t, s.names(), ActTimeoutAnchor)
	want, _ := CallData(ActTimeoutAnchor, word(1), word(0))
	if hex.EncodeToString(s.sent[0]) != hex.EncodeToString(want) || len(want) != 4+64 {
		t.Fatalf("calldata %x", s.sent[0])
	}
}

func TestIdempotentAndResendAfterWindow(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	f.settle("a")
	k := newKeeper(t, f, s, "")
	f.head = f.timing.AnchorDeadline(0) + 1
	tick(t, k)
	rep := tick(t, k)
	equal(t, s.names(), ActTimeoutAnchor)
	if rep.Outcomes[0].Status != "pending" {
		t.Fatalf("status %s", rep.Outcomes[0].Status)
	}
	f.head += 9
	tick(t, k)
	equal(t, s.names(), ActTimeoutAnchor)
	f.head++ // the transaction was dropped and the state did not move
	tick(t, k)
	equal(t, s.names(), ActTimeoutAnchor, ActTimeoutAnchor)
	f.anchors[epochKey(1, 0)] = Anchor{State: epochFailed}
	tick(t, k)
	if len(k.Store.State().Sent) != 0 || len(k.Store.State().Epochs) != 0 {
		t.Fatalf("stale state kept: %+v", k.Store.State())
	}
}

func TestLatestStateRejectionIsNotSent(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	f.settle("a")
	f.reject = func([]byte) error { return fmt.Errorf("execution reverted: InvalidTransition") }
	k := newKeeper(t, f, s, "")
	f.head = f.timing.AnchorDeadline(0) + 1
	rep := tick(t, k)
	equal(t, s.names())
	if rep.Outcomes[0].Status != "rejected" || len(k.Store.State().Sent) != 0 {
		t.Fatalf("rejected action recorded: %+v", rep)
	}
}

func TestRestartKeepsCursorAndInFlightActions(t *testing.T) {
	path := filepath.Join(t.TempDir(), "keeper.json")
	f, s := newFake(), &fakeSender{}
	f.settle("a")
	f.head = f.timing.AnchorDeadline(0) + 1
	k := newKeeper(t, f, s, path)
	tick(t, k)
	k.Store.Close()

	// A second process with the same file must not rescan or resend.
	f.logQueries = nil
	f.head += 2
	k2 := newKeeper(t, f, s, path)
	tick(t, k2)
	equal(t, s.names(), ActTimeoutAnchor)
	if len(f.logQueries) != 1 || f.logQueries[0][0] != f.head-1 {
		t.Fatalf("rescanned %v", f.logQueries)
	}
	if _, err := OpenStore(path); err == nil {
		t.Fatal("second keeper opened a locked state file")
	}
}

func TestIntentIsRecordedBeforeBroadcast(t *testing.T) {
	f, s := newFake(), &fakeSender{fail: fmt.Errorf("connection reset")}
	f.settle("a")
	f.head = f.timing.AnchorDeadline(0) + 1
	k := newKeeper(t, f, s, "")
	rep := tick(t, k)
	if rep.Outcomes[0].Status != "error" {
		t.Fatalf("status %+v", rep.Outcomes)
	}
	s.fail = nil
	rep = tick(t, k)
	if rep.Outcomes[0].Status != "pending" || len(s.sent) != 0 {
		t.Fatalf("uncertain broadcast resent at once: %+v", rep.Outcomes)
	}
	f.head += 10
	tick(t, k)
	equal(t, s.names(), ActTimeoutAnchor)
}

func TestSealWindowAndTimeoutSeal(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	f.settle("a")
	f.anchors[epochKey(1, 0)] = Anchor{State: epochAnchored, RandomBlock: 2469, SealDeadline: 2669}
	k := newKeeper(t, f, s, "")
	f.head = 2469
	tick(t, k)
	equal(t, s.names())
	f.head = 2470
	tick(t, k)
	equal(t, s.names(), ActSeal)
	// Past sealDeadline the keeper still delivers the value (rule D2-16,
	// ADR 0029); once the hash is no longer served it tries the
	// checkpoint-shortage exit.
	f.head = 2670
	tick(t, k)
	if names := s.names(); len(names) == 0 || names[len(names)-1] != ActSeal {
		t.Fatalf("late seal not scheduled: %v", names)
	}
	f.head = 2469 + 257
	tick(t, k)
	if names := s.names(); names[len(names)-1] != ActTimeoutSeal {
		t.Fatalf("timeoutSeal not scheduled after the hash window: %v", names)
	}
}

func TestSampledPurchaseIsOpenedNotReleased(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	n := f.settle("a")
	f.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2669}
	f.sampled[n] = true
	f.head = 5000
	k := newKeeper(t, f, s, "")
	tick(t, k)
	equal(t, s.names(), ActOpenSample)
	f.cases[n] = Case{State: caseAssigning, Stage: 1}
	tick(t, k)
	equal(t, s.names(), ActOpenSample, ActAssignVerifier)
}

func TestReassignmentAndKeeperServePath(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	n := f.settle("a")
	f.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2669}
	f.states[n] = finHeld
	f.cases[n] = Case{State: caseJudging, Stage: 1, Attempt: 0, AssignedVerifierID: 7, JudgeDue: 3000}
	k := newKeeper(t, f, s, "")
	f.head = 3000
	tick(t, k)
	equal(t, s.names())
	f.head = 3001
	tick(t, k)
	equal(t, s.names(), ActTimeoutJudge)
	// The contract replaced the verifier: a new attempt is a new action.
	f.cases[n] = Case{State: caseJudging, Stage: 1, Attempt: 1, AssignedVerifierID: 8, JudgeDue: 3001}
	f.head = 3002
	tick(t, k)
	equal(t, s.names(), ActTimeoutJudge, ActTimeoutJudge)
	// Final attempt timed out on a sampled case: the keeper serve path.
	f.cases[n] = Case{State: caseServeWait, Stage: 1, Attempt: 2, ServeDue: 3300}
	f.head = 3300
	tick(t, k)
	f.head = 3301
	tick(t, k)
	equal(t, s.names(), ActTimeoutJudge, ActTimeoutJudge, ActTimeoutServe)
	// If the seller serves, the keeper never accepts or escalates; it
	// finalizes once the challenge deadline has passed.
	f.cases[n] = Case{State: caseServeConfirm, Stage: 1, Attempt: 2, ChallengeUntil: 3600}
	f.head = 3600
	tick(t, k)
	f.head = 3601
	tick(t, k)
	equal(t, s.names(), ActTimeoutJudge, ActTimeoutJudge, ActTimeoutServe, ActFinalizeServed)
	f.cases[n] = Case{State: casePublishing, PublishDue: 3700}
	f.head = 3701
	tick(t, k)
	equal(t, s.names(), ActTimeoutJudge, ActTimeoutJudge, ActTimeoutServe, ActFinalizeServed, ActTimeoutServe)
}

func TestReviewProgress(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	n := f.settle("a")
	f.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2669}
	f.states[n] = finHeld
	k := newKeeper(t, f, s, "")
	f.cases[n] = Case{State: caseInitialVerdict, Stage: 1, InitialVerdict: verdictFail, RandomBlock: 4001}
	f.head = 4000
	// Under a profile that freezes only at the confirmed failure, an initial
	// FAIL proposes nothing (ADR 0020).
	f.timing.FreezeOnInitialFail = false
	tick(t, k)
	equal(t, s.names())
	f.timing.FreezeOnInitialFail = true
	tick(t, k)
	// An initial FAIL that is not yet terminal freezes the seller's bond
	// account, with this case's own nonce as the trigger.
	equal(t, s.names(), ActFreezeSellerDeferred)
	f.head = 4001 // appealUntil has passed
	tick(t, k)
	equal(t, s.names(), ActFreezeSellerDeferred, ActFinalizeCase)
	f.cases[n] = Case{State: caseInitialVerdict, Stage: 1, InitialVerdict: verdictPass, RandomBlock: 4001}
	tick(t, k)
	equal(t, s.names(), ActFreezeSellerDeferred, ActFinalizeCase)
	f.head = 4002
	tick(t, k)
	equal(t, s.names(), ActFreezeSellerDeferred, ActFinalizeCase, ActOpenAutoRecheck)
	// An initial INCONCLUSIVE takes the same recheck gate, one block after its candidate block.
	f.cases[n] = Case{State: caseInitialVerdict, Stage: 1, InitialVerdict: verdictInconclusive, RandomBlock: 4050}
	f.head = 4050
	tick(t, k)
	equal(t, s.names(), ActFreezeSellerDeferred, ActFinalizeCase, ActOpenAutoRecheck)
	f.head = 4051
	tick(t, k)
	equal(t, s.names(), ActFreezeSellerDeferred, ActFinalizeCase, ActOpenAutoRecheck, ActOpenAutoRecheck)
	f.cases[n] = Case{State: casePartyReview, Stage: 2, RandomBlock: 4100}
	f.head = 4101
	tick(t, k)
	equal(t, s.names(), ActFreezeSellerDeferred, ActFinalizeCase, ActOpenAutoRecheck, ActOpenAutoRecheck, ActSealReviewRandomness)
	f.cases[n] = Case{State: caseInitialVerdict, Stage: 1, Attempt: 0, EvidenceDue: 4200, RandomBlock: 4300}
	f.head = 4201
	tick(t, k)
	equal(t, s.names(), ActFreezeSellerDeferred, ActFinalizeCase, ActOpenAutoRecheck, ActOpenAutoRecheck, ActSealReviewRandomness, ActTimeoutEvidence)
	if last := s.sent[len(s.sent)-1]; len(last) != 4+3*32 {
		t.Fatalf("timeoutEvidence calldata length %d", len(last))
	}
}

// A review seal that found no randomness reopens on the next block (ADR 0021):
// the case keeps its state with a new randomBlock, and the keeper seals again
// once the new block has passed, instead of treating the stage as done.
func TestReviewSealReopened(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	n := f.settle("a")
	f.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2669}
	f.states[n] = finHeld
	k := newKeeper(t, f, s, "")
	f.cases[n] = Case{State: casePartyReview, Stage: 2, RandomBlock: 4100}
	f.head = 4400 // past the seal window: the contract reopens instead of ending the case
	tick(t, k)
	equal(t, s.names(), ActSealReviewRandomness)
	f.cases[n] = Case{State: casePartyReview, Stage: 2, RandomBlock: 4401}
	tick(t, k)
	equal(t, s.names(), ActSealReviewRandomness)
	f.head = 4402
	tick(t, k)
	equal(t, s.names(), ActSealReviewRandomness, ActSealReviewRandomness)
	// The recheck gate of an unappealed PASS reopens the same way.
	f.cases[n] = Case{State: caseInitialVerdict, Stage: 1, InitialVerdict: verdictPass, RandomBlock: 4500}
	f.head = 4800
	tick(t, k)
	f.cases[n] = Case{State: caseInitialVerdict, Stage: 1, InitialVerdict: verdictPass, RandomBlock: 4801}
	f.head = 4802
	tick(t, k)
	equal(t, s.names(), ActSealReviewRandomness, ActSealReviewRandomness, ActOpenAutoRecheck, ActOpenAutoRecheck)
}

func TestReleaseWaitsForEveryCondition(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	n := f.settle("a")
	f.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2669}
	f.purchases[n] = Purchase{ClaimUntil: 3000, ReleaseBlock: 4000, RetainUntil: 4100, FinancialState: finDeferred}
	k := newKeeper(t, f, s, "")
	for _, h := range []uint64{2869, 3000, 3999, 4099} {
		f.head = h
		tick(t, k)
	}
	equal(t, s.names())
	f.head = 4100
	tick(t, k)
	equal(t, s.names(), ActReleasePurchase)
	f.states[n], f.purchases[n] = finReleased, Purchase{FinancialState: finReleased}
	tick(t, k)
	if st := k.Store.State(); len(st.Purchases) != 0 {
		t.Fatalf("released purchase still tracked")
	}
}

func TestReleaseAfterCaseAndSkipsRefundable(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	a, b := f.settle("a"), f.settle("b")
	f.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2669}
	f.cases[a] = Case{State: caseDelivered}
	f.cases[b] = Case{State: caseUnserved}
	f.states[b] = finRefundable
	f.head = 5000
	k := newKeeper(t, f, s, "")
	tick(t, k)
	equal(t, s.names(), ActReleasePurchase)
	if s.sent[0][4+31] != a[31] {
		t.Fatal("released the wrong purchase")
	}
}

// A sampled purchase whose non-delivery dispute ended as delivered is opened
// as a sample case, not released (ADR 0024); an unsampled one is released.
func TestDeliveredDisputeOpensItsSampleCase(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	a, b := f.settle("a"), f.settle("b")
	f.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2669}
	f.cases[a] = Case{State: caseDelivered, Trigger: triggerNonDelivery}
	f.cases[b] = Case{State: caseDelivered, Trigger: triggerNonDelivery}
	f.sampled[a] = true
	f.head = 5000
	k := newKeeper(t, f, s, "")
	tick(t, k)
	equal(t, s.names(), ActOpenSample, ActReleasePurchase)
	if s.sent[0][4+31] != a[31] || s.sent[1][4+31] != b[31] {
		t.Fatal("opened or released the wrong purchase")
	}
}

func TestFrozenEntriesWaitAndPoolIsForfeitedAfterWindow(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	n := f.settle("a")
	f.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2669}
	f.states[n] = finFrozenClaimable
	f.bonds[5] = Bond{FreezeState: freezeClaimOpen, ClaimUntilBlock: 6000}
	k := newKeeper(t, f, s, "")
	f.head = 6000
	tick(t, k)
	equal(t, s.names())
	f.head = 6001
	tick(t, k)
	equal(t, s.names(), ActForfeitUnclaimed)
	// After the window the purchase reports FORFEITED while its stored state is
	// still DEFERRED; release settles only its finished case deposits.
	f.bonds[5] = Bond{FreezeState: 3}
	f.states[n] = finForfeited
	f.head = 6002
	tick(t, k)
	equal(t, s.names(), ActForfeitUnclaimed, ActReleasePurchase)
}

func TestFreezeSellerDeferredWhenInitialFailIsNotYetTerminal(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	n := f.settle("a")
	f.cases[n] = Case{State: caseJudging, InitialVerdict: verdictFail}
	k := newKeeper(t, f, s, "")
	f.head = 1100
	tick(t, k)
	equal(t, s.names(), ActFreezeSellerDeferred)
	want, _ := CallData(ActFreezeSellerDeferred, n[:])
	if hex.EncodeToString(s.sent[0]) != hex.EncodeToString(want) {
		t.Fatalf("calldata %x", s.sent[0])
	}
}

func TestFreezeSellerDeferredSkipsAnAlreadyFrozenBond(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	n := f.settle("a")
	f.cases[n] = Case{State: caseJudging, InitialVerdict: verdictFail}
	f.bonds[5] = Bond{FreezeState: freezeFrozen, FreezeBlock: 1}
	k := newKeeper(t, f, s, "")
	f.head = 1100
	tick(t, k)
	// The freeze is skipped (one is already in place); the bond loop proposes
	// its release instead, which only the contract can decide is premature.
	equal(t, s.names(), ActReleaseFrozen)
}

func TestFreezeSellerDeferredSkipsATerminalCase(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	f.settle("a")
	f.cases[nonceOf("a")] = Case{State: caseDelivered, InitialVerdict: verdictFail}
	k := newKeeper(t, f, s, "")
	f.head = 1100
	tick(t, k)
	equal(t, s.names())
}

func TestReleaseFrozenWhenBondCarriesAFreeze(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	f.settle("a")
	f.bonds[5] = Bond{FreezeState: freezeFrozen, FreezeBlock: 900}
	k := newKeeper(t, f, s, "")
	f.head = 1100
	tick(t, k)
	equal(t, s.names(), ActReleaseFrozen)
	want, _ := CallData(ActReleaseFrozen, word(5))
	if hex.EncodeToString(s.sent[0]) != hex.EncodeToString(want) {
		t.Fatalf("calldata %x", s.sent[0])
	}
	// The contract is the one that actually decides: a freeze whose trigger
	// case has not ended is rejected without being recorded as sent.
	f.reject = func(data []byte) error {
		if selectorName(data) == ActReleaseFrozen {
			return fmt.Errorf("execution reverted: FreezeStillOpen")
		}
		return nil
	}
	f.bonds[5] = Bond{FreezeState: freezeFrozen, FreezeBlock: 1500}
	f.head = 1600
	rep := tick(t, k)
	equal(t, s.names(), ActReleaseFrozen)
	if rep.Outcomes[len(rep.Outcomes)-1].Status != "rejected" {
		t.Fatalf("outcomes %+v", rep.Outcomes)
	}
	// A claim-open bond forfeits instead of releasing.
	f.bonds[5] = Bond{FreezeState: freezeClaimOpen, ClaimUntilBlock: 1500}
	f.reject = nil
	f.head = 1601
	tick(t, k)
	equal(t, s.names(), ActReleaseFrozen, ActForfeitUnclaimed)
}

func TestDisabledActionsAreNotSent(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	f.settle("a")
	k := newKeeper(t, f, s, "")
	k.Enabled = map[string]bool{ActTimeoutServe: true}
	f.head = f.timing.AnchorDeadline(0) + 1
	rep := tick(t, k)
	equal(t, s.names())
	if rep.Outcomes[0].Status != "disabled" {
		t.Fatalf("status %+v", rep.Outcomes)
	}
}

func TestFinalizedRegressionIsAnError(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	f.settle("a")
	k := newKeeper(t, f, s, "")
	f.head = 2000
	tick(t, k)
	f.head = 1500
	if _, err := k.Tick(context.Background()); err == nil {
		t.Fatal("accepted a finalized block below the scanned block")
	}
}

func TestLogScanIsChunked(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	f.settle("a")
	k := newKeeper(t, f, s, "")
	k.MaxLogRange = 400
	f.head = 1999
	tick(t, k)
	if fmt.Sprint(f.logQueries) != "[[1000 1399] [1400 1799] [1800 1999]]" {
		t.Fatalf("queries %v", f.logQueries)
	}
	if len(k.Store.State().Purchases) != 1 || k.Store.State().Scanned != 1999 {
		t.Fatalf("state %+v", k.Store.State())
	}
}

func TestNoVerdictOrResultCalls(t *testing.T) {
	for name, sig := range signatures {
		for _, forbidden := range []string{"judge(", "appeal(", "acceptServe(", "escalate(", "dispute(", "served(", "claimRefund("} {
			if len(sig) >= len(forbidden) && sig[:len(forbidden)] == forbidden {
				t.Fatalf("%s maps to a discretionary call %s", name, sig)
			}
		}
	}
	if len(signatures) != len(AllActions) {
		t.Fatal("action list and signatures differ")
	}
}

type receiptList map[protocol.Bytes32]SignedReceipt

func (l receiptList) SampleReceipt(_ context.Context, n protocol.Bytes32) (SignedReceipt, bool, error) {
	r, ok := l[n]
	return r, ok, nil
}

func signedReceipt(n protocol.Bytes32) SignedReceipt {
	sig := make([]byte, 65)
	sig[64] = 27
	return SignedReceipt{
		Receipt:   protocol.Receipt{Version: 1, SellerID: 1, ProfileID: 3, Nonce: n, Epoch: 0, IssuedAt: 7},
		Signature: sig,
		Proof:     protocol.ReceiptProof{Index: 1, Count: 3, Siblings: []protocol.Bytes32{{0xaa}, {0xbb}}},
	}
}

// Rule D2-17: with the published receipt list the keeper puts an open sample
// case's receipt on chain before its deadline, once per deadline; after the
// deadline it calls timeoutSampleReceipt in the first block it is due.
func TestSampleReceiptSubmittedThenTimedOut(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	n := f.settle("a")
	f.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2000}
	f.states[n] = finHeld
	f.cases[n] = Case{State: caseJudging, Trigger: triggerSample, AssignedVerifierID: 3, JudgeDue: 2800, SampleReceiptDue: 2500}
	k := newKeeper(t, f, s, "")
	k.Receipts = receiptList{n: signedReceipt(n)}
	f.head = 2400
	tick(t, k)
	equal(t, s.names(), ActSubmitSampleReceipt)
	data := s.sent[0]
	// selector, nonce, ten receipt words, two offsets, signature (length and
	// three words), proof (index, count, offset, length, two siblings).
	if len(data) != 4+32*(1+10+2+4+6) {
		t.Fatalf("calldata length %d", len(data))
	}
	if hex.EncodeToString(data[4+32*11:4+32*13]) != hex.EncodeToString(append(word(13*32), word(17*32)...)) {
		t.Fatalf("offsets %x", data[4+32*11:4+32*13])
	}
	f.head = 2405
	tick(t, k)
	equal(t, s.names(), ActSubmitSampleReceipt)
	// Nobody put it on chain (the transaction was dropped): past the deadline
	// the case is UNSERVED.
	f.head = 2501
	rep := tick(t, k)
	equal(t, s.names(), ActSubmitSampleReceipt, ActTimeoutSampleReceipt)
	if lastDue(t, rep, ActTimeoutSampleReceipt) != 2501 {
		t.Fatal("timeout due")
	}
	// A receipt already on chain leaves the case alone.
	f.cases[n] = Case{State: caseJudging, Trigger: triggerSample, AssignedVerifierID: 3, JudgeDue: 2800}
	f.head = 2700
	tick(t, k)
	equal(t, s.names(), ActSubmitSampleReceipt, ActTimeoutSampleReceipt)
}

// Without a receipt list the keeper still ends the case after the deadline.
func TestSampleReceiptTimeoutWithoutList(t *testing.T) {
	f, s := newFake(), &fakeSender{}
	n := f.settle("a")
	f.anchors[epochKey(1, 0)] = Anchor{State: epochSealed, SealDeadline: 2000}
	f.states[n] = finHeld
	f.cases[n] = Case{State: caseJudging, Trigger: triggerSample, AssignedVerifierID: 3, JudgeDue: 2800, SampleReceiptDue: 2500}
	k := newKeeper(t, f, s, "")
	f.head = 2500
	tick(t, k)
	equal(t, s.names())
	f.head = 2501
	tick(t, k)
	equal(t, s.names(), ActTimeoutSampleReceipt)
	want, _ := CallData(ActTimeoutSampleReceipt, n[:])
	if hex.EncodeToString(s.sent[0]) != hex.EncodeToString(want) {
		t.Fatalf("calldata %x", s.sent[0])
	}
}

func TestDirReceiptListReadsPublishedReceipts(t *testing.T) {
	dir := t.TempDir()
	n := nonceOf("a")
	l := DirReceiptList{Dir: dir}
	if _, ok, err := l.SampleReceipt(context.Background(), n); ok || err != nil {
		t.Fatalf("missing file: %v %v", ok, err)
	}
	sig := "0x" + hex.EncodeToString(append(make([]byte, 64), 28))
	body := fmt.Sprintf(`{"receipt":{"version":1,"chainId":"31337","contractAddress":"0x1100000000000000000000000000000000000000","sellerId":1,"profileId":3,"nonce":"%s","requestHash":"0x%064x","responseHash":"0x%064x","claimsHash":"0x%064x","predicateCommitment":"0x%064x","epoch":0,"issuedAt":"7","signature":"%s"},"receiptProof":{"index":0,"count":1,"siblings":[]}}`,
		hexKey(n), 1, 2, 3, 4, sig)
	if err := os.WriteFile(filepath.Join(dir, hexKey(n)+".json"), []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	r, ok, err := l.SampleReceipt(context.Background(), n)
	if err != nil || !ok || r.Receipt.Nonce != n || len(r.Signature) != 65 || r.Proof.Count != 1 {
		t.Fatalf("read %+v %v %v", r, ok, err)
	}
}
