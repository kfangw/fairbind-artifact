package verifier

import (
	"context"
	"encoding/binary"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/evidence"
	"example.org/fairbind/runtime/ledger"
	"example.org/fairbind/services/internal/directive"
)

// Worst-path directive (experiments/controller/worstpath.py, verifier block).
//
// On a case opened by sampling every assignment of this verifier requests
// serve at its judge deadline and escalates the served bundle at the challenge
// deadline; after the seller publishes, the judge deadline is renewed. Then:
//   - initial stage: every assignment delivers the initial verdict at the
//     renewed judge deadline; the last one (attempt max_replaced_assignments)
//     discloses its evidence at the evidence deadline when the seller requests
//     it, the others never do, so the keeper voids them;
//   - party review and tiebreak: the last assignment delivers the stage verdict
//     at the renewed judge deadline; the others leave the case to time out.
//
// Calls are timed to the block that includes them: a call sent while the
// latest block is h lands in h + 1 (a local node that mines each transaction
// in its own block). The case is read at the latest block for timing; the
// verdict is still prepared and submitted through the outbox from the
// finalized assignment.

// Case states of contract-interface-v1 section 2 the directive reads.
const (
	caseServeConfirm   uint8 = 2
	caseInitialVerdict uint8 = 6
	triggerSample      uint8 = 1
)

// CaseView is the part of getCase the directive reads at the latest block.
type CaseView struct {
	Requester                             protocol.Address
	EvidenceHash                          protocol.Bytes32
	ChallengeUntil, JudgeDue, EvidenceDue uint64
	AssignedVerifierID                    uint32
	Trigger, State, Stage, Attempt        uint8
}

// DirectedChain reads a case at the latest block.
type DirectedChain interface {
	LatestCase(ctx context.Context, nonce protocol.Bytes32) (CaseView, error)
}

// Directed configures the worst-path directive of a worker.
type Directed struct {
	Path  *directive.WorstPath
	Chain DirectedChain
	// Contract receives the serve, escalation and disclosure calls, sent
	// through Worker.Sender from From, the verifier owner (the relay account).
	Contract, From protocol.Address
	// Objects holds the evidence envelopes the outbox stored; a disclosure
	// sends the envelope whose hash the verdict committed.
	Objects *evidence.Store
}

func judgingState(state, stage uint8) bool {
	want := map[uint8]uint8{1: 5, 2: 7, 3: 8, 4: 9}
	s, ok := want[stage]
	return ok && state == s
}

// directedStep is the verifier's next call on a sampled worst-path case whose
// next block is next, for its own assignment e.
type directedStep int

const (
	stepNone directedStep = iota
	stepRequestServe
	stepEscalate
	stepJudge
	stepDisclose
	stepLeaveToTimeout
)

func (d *Directed) step(cv CaseView, e *Entry, next uint64) directedStep {
	switch {
	case judgingState(cv.State, cv.Stage):
		if !e.ServeRequested {
			if next == cv.JudgeDue {
				return stepRequestServe
			}
			return stepNone
		}
		if cv.Stage != 1 && cv.Attempt < d.Path.MaxReplacedAssignments {
			return stepLeaveToTimeout
		}
		if d.Path.StageVerdict(cv.Stage) == "" {
			return stepNone
		}
		return stepJudge
	case cv.State == caseServeConfirm:
		if e.ServeRequested && !e.Escalated && cv.Requester == d.From && next == cv.ChallengeUntil {
			return stepEscalate
		}
	case cv.State == caseInitialVerdict && cv.Stage == 1:
		if cv.EvidenceDue != 0 && cv.Attempt >= d.Path.MaxReplacedAssignments && !e.Disclosed && next == cv.EvidenceDue {
			return stepDisclose
		}
	}
	return stepNone
}

// processDirected handles one watched nonce under the worst-path directive.
func (w *Worker) processDirected(ctx context.Context, nonce protocol.Bytes32, head uint64) {
	log := w.log().With("nonce", hex32(nonce))
	d := w.Directed
	cv, err := d.Chain.LatestCase(ctx, nonce)
	if err != nil {
		log.Warn("latest case read failed", "err", err)
		return
	}
	if cv.Trigger != triggerSample {
		w.process(ctx, nonce, head)
		return
	}
	cur, err := w.Source.Read(ctx, nonce, ledger.ManifestBindings{})
	if err != nil {
		log.Warn("finalized read failed", "err", err)
		return
	}
	pending := false
	for _, e := range w.State.entriesFor(nonce) {
		if e.Status.inFlight() {
			w.reconcile(ctx, log, e, cur)
		}
		if e.Status.inFlight() || e.Status == StatusPrepared {
			pending = true
		}
	}
	if cv.AssignedVerifierID != w.Opts.VerifierID {
		if !pending {
			w.State.unwatch(nonce)
		}
		return
	}
	key := entryKey(nonce, cv.Stage, cv.Attempt, w.Opts.VerifierID)
	e := w.State.S.Entries[key]
	if e == nil {
		e = &Entry{Nonce: hex32(nonce), Stage: cv.Stage, Attempt: cv.Attempt, VerifierID: w.Opts.VerifierID, JudgeDue: cv.JudgeDue, FromBlock: cur.BlockNumber}
		w.State.S.Entries[key] = e
	}
	log = log.With("stage", cv.Stage, "attempt", cv.Attempt)
	switch d.step(cv, e, head+1) {
	case stepRequestServe:
		if tx, err := w.Sender.Send(ctx, d.Contract, nonceCall("requestServe(bytes32)", nonce)); err != nil {
			log.Warn("requestServe failed", "err", err)
		} else {
			e.ServeRequested = true
			log.Info("serve requested at the judge deadline", "judgeDue", cv.JudgeDue, "tx", hex32(tx))
		}
	case stepEscalate:
		if tx, err := w.Sender.Send(ctx, d.Contract, nonceCall("escalate(bytes32)", nonce)); err != nil {
			log.Warn("escalate failed", "err", err)
		} else {
			e.Escalated = true
			log.Info("served bundle escalated at the challenge deadline", "challengeUntil", cv.ChallengeUntil, "tx", hex32(tx))
		}
	case stepDisclose:
		raw, err := d.Objects.Get(cv.EvidenceHash)
		if err != nil {
			log.Error("evidence to disclose is not in the object store", "evidenceHash", hex32(cv.EvidenceHash), "err", err)
			return
		}
		if tx, err := w.Sender.Send(ctx, d.Contract, discloseCall(nonce, cv.Stage, cv.Attempt, raw)); err != nil {
			log.Warn("discloseEvidence failed", "err", err)
		} else {
			e.Disclosed = true
			log.Info("evidence disclosed at the evidence deadline", "evidenceDue", cv.EvidenceDue, "tx", hex32(tx))
		}
	case stepLeaveToTimeout:
		if e.Status == "" {
			e.Status, e.Note = StatusSkipped, "worst-path directive: not the last assignment of a review stage; left to time out"
			log.Info("assignment left to time out")
		}
	case stepJudge:
		w.judgeDirected(ctx, log, e, nonce, cur.Snapshot.ProfileID, cv, head)
	}
}

// judgeDirected prepares the stage verdict of the directive as soon as the
// finalized ledger shows the renewed assignment and submits it so that it
// lands at the judge deadline.
func (w *Worker) judgeDirected(ctx context.Context, log *slog.Logger, e *Entry, nonce protocol.Bytes32, profileID uint32, cv CaseView, head uint64) {
	if e.Status.terminal() || e.Status.inFlight() {
		return
	}
	bindings, ok := w.Opts.Bindings[profileID]
	if !ok {
		e.Status, e.Note = StatusSkipped, fmt.Sprintf("profile %d not configured", profileID)
		log.Warn("assignment skipped", "reason", e.Note)
		return
	}
	a, err := w.Source.Read(ctx, nonce, bindings)
	if err != nil {
		log.Warn("finalized read failed", "err", err)
		return
	}
	if a.VerifierID != w.Opts.VerifierID || a.Stage != cv.Stage || a.Attempt != cv.Attempt || !judging(a) || a.JudgeDue != cv.JudgeDue {
		return // the finalized ledger has not reached the renewed assignment yet
	}
	e.JudgeDue = a.JudgeDue
	p, attempted, err := w.Outbox.Load(ctx, a)
	switch {
	case err == nil && attempted:
		e.Status, e.Verdict, e.EvidenceHash = StatusUncertain, p.Verdict.Verdict, hex32(p.Verdict.EvidenceHash)
		w.reconcile(ctx, log, e, a)
		return
	case err == nil:
		e.Status, e.Verdict, e.EvidenceHash = StatusPrepared, p.Verdict.Verdict, hex32(p.Verdict.EvidenceHash)
	case errors.Is(err, fs.ErrNotExist):
		if head+1 > a.JudgeDue {
			e.Status, e.Note = StatusExpired, fmt.Sprintf("head %d past judgeDue %d", head, a.JudgeDue)
			return
		}
		if p, err = w.prepareWith(ctx, a, w.Directed.Path.StageVerdict(a.Stage)); err != nil {
			log.Warn("verdict not prepared; will retry", "err", err)
			return
		}
		e.Status, e.Verdict, e.EvidenceHash = StatusPrepared, p.Verdict.Verdict, hex32(p.Verdict.EvidenceHash)
		if err = w.State.Save(); err != nil {
			log.Error("state save failed", "err", err)
			return
		}
	default:
		log.Error("outbox record unusable; operator attention required", "err", err)
		return
	}
	switch {
	case head+1 < a.JudgeDue:
		return // held until the judge deadline
	case head+1 > a.JudgeDue:
		e.Status, e.Note = StatusExpired, fmt.Sprintf("head %d past judgeDue %d", head, a.JudgeDue)
		log.Warn("judge deadline passed before the directed verdict was sent")
		return
	}
	tx, err := w.Outbox.Submit(ctx, p, w.Source, w.Sender)
	if tx != (protocol.Bytes32{}) {
		e.Tx = hex32(tx)
	}
	if err == nil {
		e.Status = StatusSubmitted
		log.Info("verdict submitted at the judge deadline", "tx", e.Tx, "verdict", p.Verdict.Verdict, "judgeDue", a.JudgeDue)
		return
	}
	if _, attempted, lerr := w.Outbox.Load(ctx, p.Assignment); lerr == nil && attempted {
		e.Status = StatusUncertain
		log.Warn("broadcast outcome uncertain; will reconcile, never resend", "err", err, "tx", e.Tx)
		return
	}
	log.Warn("submission refused before broadcast; will retry", "err", err)
}

// nonceCall encodes a call that takes one bytes32.
func nonceCall(signature string, nonce protocol.Bytes32) []byte {
	sel := protocol.Keccak256([]byte(signature))
	return append(append([]byte{}, sel[:4]...), nonce[:]...)
}

// discloseCall encodes discloseEvidence(bytes32,uint8,uint8,bytes).
func discloseCall(nonce protocol.Bytes32, stage, attempt uint8, evidence []byte) []byte {
	sel := protocol.Keccak256([]byte("discloseEvidence(bytes32,uint8,uint8,bytes)"))
	word := func(v uint64) []byte {
		w := make([]byte, 32)
		binary.BigEndian.PutUint64(w[24:], v)
		return w
	}
	out := append([]byte{}, sel[:4]...)
	out = append(out, nonce[:]...)
	out = append(out, word(uint64(stage))...)
	out = append(out, word(uint64(attempt))...)
	out = append(out, word(4*32)...)
	out = append(out, word(uint64(len(evidence)))...)
	out = append(out, evidence...)
	return append(out, make([]byte, (32-len(evidence)%32)%32)...)
}
