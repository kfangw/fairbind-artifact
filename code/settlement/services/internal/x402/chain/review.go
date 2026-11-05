package chain

import (
	"context"
	"fmt"
)

// Case states and stages beyond those the Case view names, from
// contract-interface-v1 section 2.
const (
	TriggerSample      uint8 = 1
	CaseInitialVerdict uint8 = 6
	StageInitial       uint8 = 1
	VerdictFail        uint8 = 2

	sigRequestEvidence = "requestEvidence(bytes32,uint8,uint8)"
	sigAppeal          = "appeal(bytes32)"
	sigGetReview       = "getReview(bytes32)"
)

// CaseDetail is the part of getCase and getReview the seller reads to follow
// the review procedure of a case on the worst-path directive.
type CaseDetail struct {
	Case
	Stage, Attempt, InitialVerdict, FinalVerdict, ReviewPath uint8
	JudgeDue, EvidenceDue, RandomBlock, AppealUntil          uint64
	EvidenceHash                                             Hash
}

// Reviewer is the seller's side of the review procedure: evidence requests
// and appeals (contract-interface-v1 section 9).
type Reviewer interface {
	CaseDetail(ctx context.Context, nonce Hash) (CaseDetail, error)
	RequestEvidence(ctx context.Context, nonce Hash, stage, attempt uint8) (Hash, error)
	Appeal(ctx context.Context, nonce Hash) (Hash, error)
}

func (r *RPC) CaseDetail(ctx context.Context, nonce Hash) (CaseDetail, error) {
	c, err := r.GetCase(ctx, nonce)
	if err != nil {
		return CaseDetail{}, err
	}
	// getCase words: 4 evidenceHash, 9 randomBlock, 10 judgeDue, 11 evidenceDue,
	// 17 reviewPath, 19 stage, 20 attempt, 21 initialVerdict, 22 finalVerdict.
	d, err := r.viewWords(ctx, 23, sigGetCase, st(nonce[:]))
	if err != nil {
		return CaseDetail{}, err
	}
	out := CaseDetail{Case: c, Stage: d.u8(19), Attempt: d.u8(20), InitialVerdict: d.u8(21), FinalVerdict: d.u8(22),
		ReviewPath: d.u8(17), JudgeDue: d.u64(10), EvidenceDue: d.u64(11), RandomBlock: d.u64(9), EvidenceHash: d.h(4)}
	if d.err != nil {
		return CaseDetail{}, d.err
	}
	// getReview words: 0 appealUntil, 1 autoVerdict, 2 appellant, 3 deposit.
	rv, err := r.viewWords(ctx, 4, sigGetReview, st(nonce[:]))
	if err != nil {
		return CaseDetail{}, err
	}
	out.AppealUntil = rv.u64(0)
	return out, rv.err
}

func (r *RPC) RequestEvidence(ctx context.Context, nonce Hash, stage, attempt uint8) (Hash, error) {
	return r.send(ctx, call(sigRequestEvidence, st(nonce[:]), st(u(uint64(stage))), st(u(uint64(attempt)))))
}

func (r *RPC) Appeal(ctx context.Context, nonce Hash) (Hash, error) {
	return r.nonceCall(ctx, sigAppeal, nonce)
}

// SetCaseDetailForTest sets the review fields of a case the fake does not
// model (stage, attempt, verdicts, evidence and appeal deadlines).
func (f *Fake) SetCaseDetailForTest(nonce Hash, d CaseDetail) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.details == nil {
		f.details = map[Hash]CaseDetail{}
	}
	f.details[nonce] = d
}

func (c *fakeClient) CaseDetail(_ context.Context, nonce Hash) (CaseDetail, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	d := c.f.details[nonce]
	d.Case = c.f.cases[nonce]
	return d, nil
}

// RequestEvidence and Appeal check the caller, state and deadline and set the
// evidence request or the review path; the fake models no review stage.
func (c *fakeClient) RequestEvidence(_ context.Context, nonce Hash, stage, attempt uint8) (Hash, error) {
	f := c.f
	return f.tx("RequestEvidence", func() error {
		d, ok := f.details[nonce]
		p := f.purchases[nonce]
		if f.sellers[p.SellerID].Owner != c.from && p.Buyer != c.from {
			return revert("Unauthorized")
		}
		if !ok || f.cases[nonce].State != CaseInitialVerdict || d.Stage != stage || d.Attempt != attempt || d.EvidenceDue != 0 {
			return revert("InvalidTransition")
		}
		if f.block > d.AppealUntil {
			return revert("DeadlinePassed")
		}
		d.EvidenceDue = f.block + uint64(f.profiles[p.ProfileID].Deadlines.EvidenceBlocks)
		f.details[nonce] = d
		return nil
	})
}

func (c *fakeClient) Appeal(_ context.Context, nonce Hash) (Hash, error) {
	f := c.f
	return f.tx("Appeal", func() error {
		d, ok := f.details[nonce]
		p := f.purchases[nonce]
		if f.sellers[p.SellerID].Owner != c.from {
			return revert("Unauthorized")
		}
		if !ok || f.cases[nonce].State != CaseInitialVerdict || d.ReviewPath != 0 || d.EvidenceDue != 0 || d.InitialVerdict != VerdictFail {
			return revert("InvalidTransition")
		}
		if f.block > d.AppealUntil {
			return revert("DeadlinePassed")
		}
		d.ReviewPath = 1
		f.details[nonce] = d
		return nil
	})
}

var _ Reviewer = (*RPC)(nil)
var _ Reviewer = (*fakeClient)(nil)

// String names a case detail in logs.
func (d CaseDetail) String() string {
	return fmt.Sprintf("state %d stage %d attempt %d evidenceDue %d appealUntil %d", d.State, d.Stage, d.Attempt, d.EvidenceDue, d.AppealUntil)
}
