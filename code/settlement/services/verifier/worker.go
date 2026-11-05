package verifier

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/evidence"
	"example.org/fairbind/runtime/judgment"
	"example.org/fairbind/runtime/ledger"
	gate "example.org/fairbind/runtime/verifier"
	"example.org/fairbind/services/internal/directive"
)

// Predicate is trusted local code that evaluates an authenticated bundle and
// stores every object its evidence envelope references. It receives the gate
// result: when the gate reports FAIL the envelope verdict must be FAIL.
type Predicate interface {
	Evaluate(ctx context.Context, a ledger.Assignment, b gate.Bundle, g gate.Result) (evidence.Envelope, error)
}

// Registry dispatches to a predicate by service class.
type Registry map[uint8]Predicate

func (r Registry) Evaluate(ctx context.Context, a ledger.Assignment, b gate.Bundle, g gate.Result) (evidence.Envelope, error) {
	p, ok := r[a.Snapshot.ClassID]
	if !ok {
		return evidence.Envelope{}, fmt.Errorf("no predicate pipeline for class %d", a.Snapshot.ClassID)
	}
	return p.Evaluate(ctx, a, b, g)
}

// Options are the worker's policy parameters.
type Options struct {
	VerifierID uint32
	// Bindings supplies the manifest hashes the ledger adapter expects per profile.
	Bindings map[uint32]ledger.ManifestBindings
	// SubmitMarginBlocks is the number of blocks kept free before judgeDue. A
	// verdict is only prepared or broadcast while head+1+margin <= judgeDue.
	SubmitMarginBlocks uint64
	// StartBlock is the first block scanned for assignments on a fresh state.
	StartBlock uint64
}

// Worker runs the verifier loop. All adapters are interfaces so tests run
// without a chain, seller or predicate pipeline.
type Worker struct {
	Opts      Options
	Source    judgment.Source
	Chain     Chain
	Seller    Seller
	Predicate Predicate
	Outbox    judgment.Outbox
	Signer    judgment.Signer
	Sender    judgment.Sender
	State     *Store
	Log       *slog.Logger
	// Directed enables the worst-path directive (directed.go); nil runs the
	// default loop.
	Directed *Directed
	// ProgressFile, when set, receives the head block of every completed
	// pass (directive.WriteProgress).
	ProgressFile string
}

func judging(a ledger.Assignment) bool {
	want := map[uint8]uint8{1: 5, 2: 7, 3: 8, 4: 9}
	s, ok := want[a.Stage]
	return ok && a.VerifierID > 0 && a.CaseState == s
}

func (w *Worker) log() *slog.Logger {
	if w.Log == nil {
		return slog.Default()
	}
	return w.Log
}

// Run ticks until the context is cancelled. Tick errors are logged, not fatal.
func (w *Worker) Run(ctx context.Context, interval time.Duration) error {
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		if err := w.Tick(ctx); err != nil {
			w.log().Warn("tick failed", "err", err)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-t.C:
		}
	}
}

// Tick performs one discovery and processing pass and persists the state.
func (w *Worker) Tick(ctx context.Context) error {
	head, err := w.Chain.BlockNumber(ctx)
	if err != nil {
		return fmt.Errorf("head block: %w", err)
	}
	fin, err := w.Chain.FinalizedBlock(ctx)
	if err != nil {
		return fmt.Errorf("finalized block: %w", err)
	}
	s := w.State
	from := s.S.Cursor
	if from < w.Opts.StartBlock {
		from = w.Opts.StartBlock
	}
	if from <= fin {
		nonces, err := w.Chain.AssignedNonces(ctx, w.Opts.VerifierID, from, fin)
		if err != nil {
			return fmt.Errorf("assignment scan: %w", err)
		}
		for _, n := range nonces {
			s.watch(n)
		}
		s.S.Cursor = fin + 1
		if err = s.Save(); err != nil {
			return err
		}
	}
	for _, h := range append([]string(nil), s.S.Watch...) {
		nonce, err := parse32(h)
		if err != nil {
			return fmt.Errorf("state watch entry: %w", err)
		}
		if w.Directed != nil {
			w.processDirected(ctx, nonce, head)
		} else {
			w.process(ctx, nonce, head)
		}
		if err = s.Save(); err != nil {
			return err
		}
	}
	return directive.WriteProgress(w.ProgressFile, head)
}

// tooLate reports whether a judge transaction could no longer be included by
// judgeDue with the configured safety margin.
func (w *Worker) tooLate(head uint64, a ledger.Assignment) bool {
	return head+1+w.Opts.SubmitMarginBlocks > a.JudgeDue
}

func (w *Worker) process(ctx context.Context, nonce protocol.Bytes32, head uint64) {
	log := w.log().With("nonce", hex32(nonce))
	cur, err := w.Source.Read(ctx, nonce, ledger.ManifestBindings{})
	if err != nil {
		log.Warn("finalized read failed", "err", err)
		return
	}
	pending := false
	for _, e := range w.State.entriesFor(nonce) {
		if e.Status == StatusPrepared && (e.VerifierID != cur.VerifierID || e.Stage != cur.Stage || e.Attempt != cur.Attempt || !judging(cur)) {
			// The assignment ended while only a prepared record was known. The
			// status may be stale after a crash, so ask the outbox.
			probe := cur
			probe.Stage, probe.Attempt, probe.VerifierID = e.Stage, e.Attempt, e.VerifierID
			if _, attempted, err := w.Outbox.Load(ctx, probe); err != nil {
				log.Warn("outbox lookup for ended assignment failed", "err", err)
			} else if attempted {
				e.Status = StatusUncertain
			} else {
				e.Status, e.Note = StatusExpired, "assignment ended before broadcast; nothing was sent"
				log.Warn("assignment ended before the prepared verdict was broadcast", "stage", e.Stage, "attempt", e.Attempt)
			}
		}
		if e.Status.inFlight() {
			w.reconcile(ctx, log, e, cur)
		}
		if e.Status.inFlight() || e.Status == StatusPrepared {
			pending = true
		}
	}
	if cur.VerifierID != w.Opts.VerifierID || !judging(cur) {
		if !pending {
			w.State.unwatch(nonce)
		}
		return
	}
	key := assignmentKey(cur)
	e := w.State.S.Entries[key]
	if e != nil && (e.Status.terminal() || e.Status.inFlight()) {
		return
	}
	if e == nil {
		e = &Entry{Nonce: hex32(nonce), Stage: cur.Stage, Attempt: cur.Attempt, VerifierID: cur.VerifierID, JudgeDue: cur.JudgeDue, FromBlock: cur.BlockNumber}
		w.State.S.Entries[key] = e
	}
	log = log.With("stage", cur.Stage, "attempt", cur.Attempt)
	bindings, ok := w.Opts.Bindings[cur.Snapshot.ProfileID]
	if !ok {
		e.Status, e.Note = StatusSkipped, fmt.Sprintf("profile %d not configured", cur.Snapshot.ProfileID)
		log.Warn("assignment skipped", "reason", e.Note)
		return
	}
	a, err := w.Source.Read(ctx, nonce, bindings)
	if err != nil {
		log.Warn("finalized read failed", "err", err)
		return
	}
	if assignmentKey(a) != key || !judging(a) {
		log.Info("assignment changed between reads")
		return
	}
	p, attempted, err := w.Outbox.Load(ctx, a)
	switch {
	case err == nil && attempted:
		// A previous run reached the attempt marker; the outcome is unknown.
		e.Status, e.Verdict, e.EvidenceHash = StatusUncertain, p.Verdict.Verdict, hex32(p.Verdict.EvidenceHash)
		log.Warn("found an attempted broadcast without a recorded result; reconciling instead of resending")
		w.reconcile(ctx, log, e, a)
		return
	case err == nil:
		e.Status, e.Verdict, e.EvidenceHash = StatusPrepared, p.Verdict.Verdict, hex32(p.Verdict.EvidenceHash)
	case errors.Is(err, fs.ErrNotExist):
		if w.tooLate(head, a) {
			e.Status, e.Note = StatusExpired, fmt.Sprintf("head %d too close to judgeDue %d", head, a.JudgeDue)
			log.Warn("judge deadline reached before a verdict was prepared; leaving the case to reassignment", "head", head, "judgeDue", a.JudgeDue)
			return
		}
		if p, err = w.prepare(ctx, a); err != nil {
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
	w.submit(ctx, log, e, p, head)
}

func (w *Worker) prepare(ctx context.Context, a ledger.Assignment) (judgment.Prepared, error) {
	return w.prepareWith(ctx, a, "")
}

// prepareWith prepares a verdict; a non-empty verdict (the worst-path
// directive) replaces the predicate's verdict in the evidence envelope. The
// outbox still refuses anything but FAIL when the gate reports FAIL.
func (w *Worker) prepareWith(ctx context.Context, a ledger.Assignment, verdict string) (judgment.Prepared, error) {
	b, proof, err := w.Seller.Redeliver(ctx, a)
	if err != nil {
		return judgment.Prepared{}, err
	}
	g := gate.Check(ctx, a.Snapshot, b, w.Outbox.Verifier)
	if g.Status != gate.Ready && g.Status != gate.Fail {
		return judgment.Prepared{}, fmt.Errorf("redelivered bundle not authenticated: %s", g.Reason)
	}
	env, err := w.Predicate.Evaluate(ctx, a, b, g)
	if err != nil {
		return judgment.Prepared{}, fmt.Errorf("predicate: %w", err)
	}
	if verdict != "" {
		env.Verdict = verdict
	}
	if protocol.VerdictCode(env.Verdict) == protocol.VerdictNone {
		return judgment.Prepared{}, fmt.Errorf("predicate returned unknown verdict %q", env.Verdict)
	}
	return w.Outbox.Prepare(ctx, a, b, env, proof, w.Signer)
}

func (w *Worker) submit(ctx context.Context, log *slog.Logger, e *Entry, p judgment.Prepared, head uint64) {
	if w.tooLate(head, p.Assignment) {
		e.Status, e.Note = StatusExpired, fmt.Sprintf("head %d too close to judgeDue %d", head, p.Assignment.JudgeDue)
		log.Warn("judge deadline reached; prepared verdict not broadcast, leaving the case to reassignment", "head", head, "judgeDue", p.Assignment.JudgeDue)
		return
	}
	tx, err := w.Outbox.Submit(ctx, p, w.Source, w.Sender)
	if tx != (protocol.Bytes32{}) {
		e.Tx = hex32(tx)
	}
	if err == nil {
		e.Status = StatusSubmitted
		log.Info("verdict submitted", "tx", e.Tx, "verdict", p.Verdict.Verdict)
		return
	}
	if _, attempted, lerr := w.Outbox.Load(ctx, p.Assignment); lerr == nil && attempted {
		e.Status = StatusUncertain
		log.Warn("broadcast outcome uncertain; will reconcile, never resend", "err", err, "tx", e.Tx)
		return
	}
	log.Warn("submission refused before broadcast; will retry", "err", err)
}

// reconcile resolves a submitted or uncertain entry from finalized data only.
// cur is a finalized assignment snapshot for the entry's nonce.
func (w *Worker) reconcile(ctx context.Context, log *slog.Logger, e *Entry, cur ledger.Assignment) {
	nonce, _ := parse32(e.Nonce)
	fin := cur.BlockNumber
	if e.EvidenceHash != "" {
		h, _ := parse32(e.EvidenceHash)
		ok, err := w.Chain.VerdictRecorded(ctx, nonce, e.VerifierID, e.Stage, h, e.FromBlock, fin)
		if err != nil {
			log.Warn("verdict log lookup failed", "err", err)
			return
		}
		if ok {
			e.Status, e.Note = StatusConfirmed, ""
			log.Info("verdict confirmed at a finalized block", "stage", e.Stage, "attempt", e.Attempt)
			return
		}
	}
	if e.Tx != "" {
		tx, _ := parse32(e.Tx)
		st, err := w.Chain.TxStatus(ctx, tx)
		if err != nil {
			log.Warn("receipt lookup failed", "err", err)
			return
		}
		if st.Found && !st.Success && st.Block <= fin {
			e.Status, e.Note = StatusReverted, fmt.Sprintf("reverted in block %d", st.Block)
			log.Error("verdict transaction reverted", "tx", e.Tx, "block", st.Block)
			return
		}
	}
	if cur.VerifierID != e.VerifierID || cur.Stage != e.Stage || cur.Attempt != e.Attempt || !judging(cur) {
		e.Status, e.Note = StatusMissed, fmt.Sprintf("case state %d stage %d attempt %d at finalized block %d without our verdict", cur.CaseState, cur.Stage, cur.Attempt, fin)
		log.Error("verdict not recorded before the assignment ended", "note", e.Note)
		return
	}
	log.Info("awaiting finalized confirmation", "status", e.Status, "tx", e.Tx)
}
