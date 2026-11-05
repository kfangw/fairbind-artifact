package seller

import (
	"context"
	"errors"
	"fmt"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402/chain"
)

// Worst-path directive (experiments/controller/worstpath.py, seller block).
// Every call is timed to the block that includes it: a call sent while the
// latest block is b lands in b + 1 (a local node that mines each transaction
// in its own block). On a case opened by sampling the seller serves at the
// serve deadline, publishes at the publication deadline, requests the evidence
// of every initial FAIL at the appeal deadline and appeals the initial FAIL
// whose evidence was disclosed at the renewed appeal deadline. Every epoch is
// anchored at its anchor deadline.

// DirectedProgress records the seller's review calls on one case.
type DirectedProgress struct {
	// EvidenceRequested lists "stage:attempt" of the assignments whose
	// evidence the seller requested.
	EvidenceRequested []string `json:"evidenceRequested,omitempty"`
	Appealed          bool     `json:"appealed,omitempty"`
}

func (p *DirectedProgress) requested(stage, attempt uint8) bool {
	if p == nil {
		return false
	}
	k := fmt.Sprintf("%d:%d", stage, attempt)
	for _, r := range p.EvidenceRequested {
		if r == k {
			return true
		}
	}
	return false
}

// Review calls of the seller on the worst path.
const (
	reviewNone            = ""
	reviewRequestEvidence = "requestEvidence"
	reviewAppeal          = "appeal"
)

// reviewStep decides the seller's review call for a case whose next block is
// next. The seller requests the evidence of an initial FAIL in the last block
// of its appeal window; once that evidence is disclosed (the request is
// recorded and no evidence deadline is pending) it appeals in the last block of
// the renewed window. A pending request waits: the verifier discloses it, or
// the keeper voids the assignment after the evidence deadline.
func reviewStep(d chain.CaseDetail, requested, appealed bool, next uint64) string {
	if d.State != chain.CaseInitialVerdict || d.Stage != chain.StageInitial || d.InitialVerdict != chain.VerdictFail ||
		d.ReviewPath != 0 || d.EvidenceDue != 0 || appealed || next != d.AppealUntil {
		return reviewNone
	}
	if !requested {
		return reviewRequestEvidence
	}
	return reviewAppeal
}

// publicationCalls is the number of transactions a publication takes: one
// call up to one chunk, otherwise begin, one per chunk and finalize.
func publicationCalls(bodyLen int) uint64 {
	if bodyLen <= protocol.ResponseChunkBytes {
		return 1
	}
	return uint64((bodyLen+protocol.ResponseChunkBytes-1)/protocol.ResponseChunkBytes) + 2
}

// directed reports whether the worst-path directive applies to a case.
func (s *Seller) directed(cs chain.Case) bool {
	return s.opt.WorstPath && cs.Trigger == chain.TriggerSample
}

// answerDirected answers one sampled case on the worst path; b is the latest block.
func (s *Seller) answerDirected(ctx context.Context, nonce protocol.Bytes32, rec *Record, cs chain.Case, b uint64) error {
	next := b + 1
	switch cs.State {
	case chain.CaseServeWait:
		if next != cs.ServeDue {
			return nil
		}
		return s.served(ctx, nonce, cs)
	case chain.CasePublishing:
		body := 0
		if rec.Response != nil {
			body = len(rec.Response.Body)
		}
		// The last transaction of the publication lands at the publication deadline.
		if rec.Chunks == nil && b+publicationCalls(body) != cs.PublishDue {
			return nil
		}
		return s.publish(ctx, nonce)
	case chain.CaseInitialVerdict:
		rv, ok := s.chain.(chain.Reviewer)
		if !ok {
			return errors.New("the worst-path directive needs a chain client with review calls")
		}
		d, err := rv.CaseDetail(ctx, nonce)
		if err != nil {
			return err
		}
		unlock := s.lock(nonce)
		defer unlock()
		if rec, err = s.getRecord(nonce); err != nil || rec == nil {
			return err
		}
		switch reviewStep(d, rec.Directed.requested(d.Stage, d.Attempt), rec.Directed != nil && rec.Directed.Appealed, next) {
		case reviewRequestEvidence:
			if _, err = rv.RequestEvidence(ctx, nonce, d.Stage, d.Attempt); err != nil {
				return err
			}
			if rec.Directed == nil {
				rec.Directed = &DirectedProgress{}
			}
			rec.Directed.EvidenceRequested = append(rec.Directed.EvidenceRequested, fmt.Sprintf("%d:%d", d.Stage, d.Attempt))
			s.opt.Log.Printf("case %x: evidence of stage %d attempt %d requested at the appeal deadline %d", nonce, d.Stage, d.Attempt, d.AppealUntil)
			return s.putRecord(rec)
		case reviewAppeal:
			if _, err = rv.Appeal(ctx, nonce); err != nil {
				return err
			}
			rec.Directed.Appealed = true
			s.opt.Log.Printf("case %x: initial FAIL appealed at the renewed appeal deadline %d", nonce, d.AppealUntil)
			return s.putRecord(rec)
		}
	}
	return nil
}
