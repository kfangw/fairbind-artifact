package verifier

import (
	"context"
	"encoding/hex"
	"sync"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/judgment"
	"example.org/fairbind/runtime/ledger"
	"example.org/fairbind/services/internal/directive"
)

type fakeLatest struct {
	mu sync.Mutex
	cv CaseView
}

func (f *fakeLatest) LatestCase(context.Context, protocol.Bytes32) (CaseView, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.cv, nil
}

// recSender records the selector of every call.
type recSender struct{ calls []string }

func (s *recSender) Send(_ context.Context, _ protocol.Address, data []byte) (protocol.Bytes32, error) {
	s.calls = append(s.calls, hex.EncodeToString(data[:4]))
	return protocol.Keccak256(data), nil
}

func selectorOf(sig string) string {
	h := protocol.Keccak256([]byte(sig))
	return hex.EncodeToString(h[:4])
}

var (
	selRequestServe = selectorOf("requestServe(bytes32)")
	selEscalate     = selectorOf("escalate(bytes32)")
	selDisclose     = selectorOf("discloseEvidence(bytes32,uint8,uint8,bytes)")
	selJudge        = selectorOf(judgment.JudgeSignature)
)

var worstVerifier = &directive.WorstPath{Role: directive.RoleVerifier, CaseHorizon: 31073, InitialVerdict: "FAIL",
	PartyReviewVerdict: "PASS", TiebreakVerdict: "FAIL", MaxReplacedAssignments: 2}

func TestDirectedStep(t *testing.T) {
	d := &Directed{Path: worstVerifier, From: protocol.Address{8}}
	judgingCase := CaseView{State: 5, Stage: 1, JudgeDue: 1000}
	cases := []struct {
		name string
		cv   CaseView
		e    Entry
		next uint64
		want directedStep
	}{
		{"serve before the judge deadline", judgingCase, Entry{}, 999, stepNone},
		{"serve at the judge deadline", judgingCase, Entry{}, 1000, stepRequestServe},
		{"initial verdict after the serve round", judgingCase, Entry{ServeRequested: true}, 1000, stepJudge},
		{"review, not the last assignment", CaseView{State: 7, Stage: 2, Attempt: 1, JudgeDue: 1000}, Entry{ServeRequested: true}, 1000, stepLeaveToTimeout},
		{"review, last assignment", CaseView{State: 7, Stage: 2, Attempt: 2, JudgeDue: 1000}, Entry{ServeRequested: true}, 1000, stepJudge},
		{"tiebreak, last assignment", CaseView{State: 9, Stage: 4, Attempt: 2, JudgeDue: 1000}, Entry{ServeRequested: true}, 1000, stepJudge},
		{"auto review has no directed verdict", CaseView{State: 8, Stage: 3, Attempt: 2}, Entry{ServeRequested: true}, 1000, stepNone},
		{"escalate at the challenge deadline", CaseView{State: 2, Stage: 1, Requester: protocol.Address{8}, ChallengeUntil: 1300}, Entry{ServeRequested: true}, 1300, stepEscalate},
		{"escalate once", CaseView{State: 2, Stage: 1, Requester: protocol.Address{8}, ChallengeUntil: 1300}, Entry{ServeRequested: true, Escalated: true}, 1300, stepNone},
		{"another requester", CaseView{State: 2, Stage: 1, Requester: protocol.Address{9}, ChallengeUntil: 1300}, Entry{ServeRequested: true}, 1300, stepNone},
		{"disclose on the last initial assignment", CaseView{State: 6, Stage: 1, Attempt: 2, EvidenceDue: 2000}, Entry{}, 2000, stepDisclose},
		{"no disclosure before the evidence deadline", CaseView{State: 6, Stage: 1, Attempt: 2, EvidenceDue: 2000}, Entry{}, 1999, stepNone},
		{"no disclosure on a replaced assignment", CaseView{State: 6, Stage: 1, Attempt: 1, EvidenceDue: 2000}, Entry{}, 2000, stepNone},
		{"no evidence requested", CaseView{State: 6, Stage: 1, Attempt: 2}, Entry{}, 0, stepNone},
	}
	for _, c := range cases {
		e := c.e
		if got := d.step(c.cv, &e, c.next); got != c.want {
			t.Errorf("%s: step %d, want %d", c.name, got, c.want)
		}
	}
}

func TestDiscloseCallEncoding(t *testing.T) {
	ev := make([]byte, 33)
	call := discloseCall(protocol.Bytes32{1}, 1, 2, ev)
	if hex.EncodeToString(call[:4]) != selDisclose || len(call) != 4+5*32+64 {
		t.Fatalf("calldata %x", call)
	}
	if call[4+1*32+31] != 1 || call[4+2*32+31] != 2 || call[4+3*32+31] != 128 || call[4+5*32-1] != 33 {
		t.Fatalf("head words %x", call[4:4+5*32])
	}
}

// The verifier requests serve at the judge deadline, escalates at the
// challenge deadline, prepares the directed verdict early and sends it so that
// it lands at the renewed judge deadline; the last initial assignment
// discloses its evidence at the evidence deadline.
func TestWorstPathVerifierSchedule(t *testing.T) {
	e := newEnv(t)
	w := e.worker(t)
	send := &recSender{}
	w.Sender = send
	latest := &fakeLatest{cv: CaseView{Trigger: triggerSample, State: 5, Stage: 1, AssignedVerifierID: 3, JudgeDue: 100}}
	w.Directed = &Directed{Path: worstVerifier, Chain: latest, Contract: protocol.Address{1}, From: protocol.Address{8}, Objects: e.objects}
	at := func(head uint64) {
		t.Helper()
		e.chain.head = head
		if !tick(t, w) {
			t.Fatal("tick did not complete")
		}
	}
	calls := func(want ...string) {
		t.Helper()
		if len(send.calls) != len(want) {
			t.Fatalf("calls %v, want %v", send.calls, want)
		}
		for i := range want {
			if send.calls[i] != want[i] {
				t.Fatalf("call %d is %s, want %s", i, send.calls[i], want[i])
			}
		}
	}
	at(20)
	at(98)
	calls()
	at(99)
	calls(selRequestServe)
	latest.cv.State = 1 // SERVE_WAIT: the seller serves
	at(120)
	latest.cv.State, latest.cv.Requester, latest.cv.ChallengeUntil = caseServeConfirm, protocol.Address{8}, 150
	at(148)
	calls(selRequestServe)
	at(149)
	calls(selRequestServe, selEscalate)
	// The seller published at 200: the case judges again with a renewed deadline.
	latest.cv.State, latest.cv.JudgeDue = 5, 800
	e.src.set(func(a *ledger.Assignment) { a.JudgeDue = 800; a.BlockNumber = 300 })
	at(300)
	calls(selRequestServe, selEscalate)
	if e.pred.calls != 1 {
		t.Fatalf("verdict not prepared early: %d predicate calls", e.pred.calls)
	}
	en := e.entry(t, w)
	if en.Status != StatusPrepared || en.Verdict != protocol.VerdictFail {
		t.Fatalf("entry %+v (the directive turns the predicate's PASS into FAIL)", en)
	}
	at(798)
	calls(selRequestServe, selEscalate)
	at(799)
	calls(selRequestServe, selEscalate, selJudge)
	if en = e.entry(t, w); en.Status != StatusSubmitted {
		t.Fatalf("entry %+v", en)
	}
	// The seller requested the evidence of this, the first assignment: it is
	// never disclosed, so the keeper voids it.
	latest.cv.State, latest.cv.EvidenceDue = caseInitialVerdict, 1100
	h, _ := parse32(en.EvidenceHash)
	latest.cv.EvidenceHash = h
	at(1099)
	calls(selRequestServe, selEscalate, selJudge)
	// The last initial assignment (attempt 2) discloses at its evidence deadline.
	latest.cv.Attempt, latest.cv.EvidenceDue = 2, 5000
	at(4998)
	calls(selRequestServe, selEscalate, selJudge)
	at(4999)
	calls(selRequestServe, selEscalate, selJudge, selDisclose)
	at(5000)
	calls(selRequestServe, selEscalate, selJudge, selDisclose)
	// A party review assignment that is not the last requests serve, then
	// leaves the case to time out.
	latest.cv = CaseView{Trigger: triggerSample, State: 7, Stage: 2, Attempt: 0, AssignedVerifierID: 3, JudgeDue: 6000}
	at(5999)
	calls(selRequestServe, selEscalate, selJudge, selDisclose, selRequestServe)
	latest.cv.JudgeDue = 6900
	at(6899)
	calls(selRequestServe, selEscalate, selJudge, selDisclose, selRequestServe)
	if got := w.State.S.Entries[entryKey(e.a.Snapshot.Nonce, 2, 0, 3)]; got == nil || got.Status != StatusSkipped {
		t.Fatalf("review entry %+v", got)
	}
	// Another verifier's assignment: once the submitted verdict is confirmed
	// nothing is pending and the nonce is dropped.
	e.chain.recorded = true
	latest.cv.AssignedVerifierID = 4
	at(7000)
	if len(w.State.S.Watch) != 0 {
		t.Fatalf("still watching %v", w.State.S.Watch)
	}
}

var _ judgment.Sender = (*recSender)(nil)
