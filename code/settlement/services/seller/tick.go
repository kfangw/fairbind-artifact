package seller

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/directive"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
)

// Run calls Tick every interval until ctx ends.
func (s *Seller) Run(ctx context.Context, interval time.Duration) {
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		if err := s.Tick(ctx); err != nil {
			s.opt.Log.Printf("tick: %v", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
	}
}

// Tick performs one pass of background work: reconcile uncertain
// settlements, submit due anchors, answer serve and publication
// obligations, and prune expired retention. Every step derives its next
// action from persisted state and chain views, so a restarted process
// resumes where it stopped.
func (s *Seller) Tick(ctx context.Context) error {
	b, err := s.chain.BlockNumber(ctx)
	if err != nil {
		return err
	}
	err = errors.Join(s.reconcileSettling(ctx), s.anchorDue(ctx, b), s.answerCases(ctx, b), s.exitDue(ctx, b), s.prune(ctx, b))
	return errors.Join(err, directive.WriteProgress(s.opt.ProgressFile, b))
}

func (s *Seller) eachRecord(fn func(nonce protocol.Bytes32) error) error {
	ids, err := s.store.List("purchases")
	if err != nil {
		return err
	}
	var errs []error
	for _, id := range ids {
		h, err := x402.ParseH32(id)
		if err != nil {
			continue
		}
		if err = fn(protocol.Bytes32(h)); err != nil {
			errs = append(errs, fmt.Errorf("%s: %w", id, err))
		}
	}
	return errors.Join(errs...)
}

// reconcileSettling moves purchases whose settlement outcome was unknown
// (for example after a crash during settlement) to settled when the ledger
// has the matching record, and to rejected once the authorization expired
// without one.
func (s *Seller) reconcileSettling(ctx context.Context) error {
	return s.eachRecord(func(nonce protocol.Bytes32) error {
		unlock := s.lock(nonce)
		defer unlock()
		rec, err := s.getRecord(nonce)
		if err != nil || rec == nil || rec.State != StateSettling {
			return err
		}
		ok, conflict, err := s.confirm(ctx, rec)
		if err != nil {
			return err
		}
		switch {
		case ok:
			rec.Settlement = s.settlementFromLedger(ctx, rec, "")
		case conflict:
			rec.State, rec.Reason = StateRejected, x402.ErrKeyConflict
		case rec.Payload != nil && uint64(rec.Payload.Payload.Authorization.ValidBefore) < s.opt.Now():
			rec.State, rec.Reason = StateRejected, "authorization_expired"
		default:
			return nil
		}
		return s.putRecord(rec)
	})
}

func epochID(e uint32) string { return strconv.FormatUint(uint64(e), 10) }

// anchorDue submits the anchor of every nonempty epoch whose anchor window
// is open. The tree covers exactly the ledger nonces of the epoch.
func (s *Seller) anchorDue(ctx context.Context, b uint64) error {
	s.epochMu.Lock()
	defer s.epochMu.Unlock()
	var cur cursor
	found, err := s.store.Get("meta", "cursor", &cur)
	if err != nil {
		return err
	}
	if !found {
		// A new data directory starts with the oldest epoch whose window may
		// still be open.
		cur = cursor{Version: 1}
		if e := s.profile.EpochAt(b); e >= 2 {
			cur.NextEpoch = e - 2
		}
	}
	var errs []error
	advancing := true
	for e := cur.NextEpoch; s.profile.AnchorBase(e) <= b; e++ {
		done, err := s.anchorEpoch(ctx, b, e)
		if err != nil {
			errs = append(errs, fmt.Errorf("epoch %d: %w", e, err))
		}
		if done && advancing {
			cur.NextEpoch = e + 1
		} else {
			advancing = false
		}
	}
	if err = s.store.Put("meta", "cursor", cur); err != nil {
		errs = append(errs, err)
	}
	return errors.Join(errs...)
}

// anchorEpoch reports whether epoch e needs no further work.
func (s *Seller) anchorEpoch(ctx context.Context, b uint64, e uint32) (bool, error) {
	var er EpochRecord
	if _, err := s.store.Get("epochs", epochID(e), &er); err != nil {
		return false, err
	}
	switch er.State {
	case EpochAnchored, EpochEmpty, EpochMissed:
		return true, nil
	}
	a, err := s.chain.GetAnchor(ctx, s.view.SellerID, e)
	if err != nil {
		return false, err
	}
	if a.State != chain.EpochNone {
		if er.State == EpochSubmitting && a.Root == protocol.Bytes32(er.Root) {
			er.State = EpochAnchored
		} else {
			s.opt.Log.Printf("epoch %d: chain anchor state %d differs from local state %q", e, a.State, er.State)
			er = EpochRecord{Version: 1, Epoch: e, State: EpochMissed, Entries: er.Entries}
		}
		return true, s.store.Put("epochs", epochID(e), er)
	}
	nonces, err := s.chain.SettledNonces(ctx, s.view.SellerID, e)
	if err != nil {
		return false, err
	}
	if len(nonces) == 0 {
		if b > s.profile.AnchorDeadline(e) {
			return true, s.store.Put("epochs", epochID(e), EpochRecord{Version: 1, Epoch: e, State: EpochEmpty, Entries: []x402.Entry{}})
		}
		return false, nil // a settlement can no longer land in e, but keep checking until the window ends
	}
	if b > s.profile.AnchorDeadline(e) {
		s.opt.Log.Printf("epoch %d: anchor window closed before submission", e)
		return true, s.store.Put("epochs", epochID(e), EpochRecord{Version: 1, Epoch: e, State: EpochMissed, Entries: []x402.Entry{}})
	}
	if s.opt.WorstPath && b+1 < s.profile.AnchorDeadline(e) {
		return false, nil // the worst path anchors at the anchor deadline
	}
	if er.State != EpochSubmitting || len(er.Entries) != len(nonces) {
		entries := make([]x402.Entry, 0, len(nonces))
		for _, n := range nonces {
			entries = append(entries, x402.Entry{Nonce: x402.H32(n), ReceiptLeaf: s.leafFor(ctx, n)})
		}
		tree, err := x402.BuildTree(entries)
		if err != nil {
			return false, err
		}
		entriesHash, _, err := x402.EntriesHash(tree.Entries)
		if err != nil {
			return false, err
		}
		m := x402.Manifest{Version: 1, SellerID: s.view.SellerID, ProfileID: s.view.ProfileID, Epoch: e, Root: x402.H32(tree.Root()),
			Count: tree.Count(), EntriesURI: fmt.Sprintf("%s/fairbind/epochs/%d/entries", s.opt.PublicURL, e),
			EntriesHash: x402.H32(entriesHash), CreatedAt: strconv.FormatUint(s.opt.Now(), 10)}
		pub, _, err := x402.PublicationHash(m)
		if err != nil {
			return false, err
		}
		// Publish the entries and manifest before the anchor transaction.
		er = EpochRecord{Version: 1, Epoch: e, State: EpochSubmitting, Entries: tree.Entries, Root: m.Root, Manifest: m, PublicationHash: x402.H32(pub)}
		if err = s.store.Put("epochs", epochID(e), er); err != nil {
			return false, err
		}
	}
	// The anchor carries the (nonce, receiptLeaf) entries; er.Entries comes
	// from BuildTree and is sorted by nonce without repeats, as the contract
	// requires, and the root the contract computes equals er.Root (ADR 0026).
	tx, err := s.chain.Anchor(ctx, s.view.SellerID, e, er.Entries, uint32(len(er.Entries)), protocol.Bytes32(er.PublicationHash))
	if err != nil {
		return false, err // the next tick reads the anchor view before retrying
	}
	er.State = EpochAnchored
	er.Tx = x402.H32(tx).String()
	return true, s.store.Put("epochs", epochID(e), er)
}

// leafFor returns the receipt leaf for a ledger nonce, signing the receipt
// of a settled but undelivered purchase first. A ledger nonce the seller has
// no request for (settled without passing through this server) gets a zero
// leaf; the buyer's redelivery claim then fails against the seller.
func (s *Seller) leafFor(ctx context.Context, nonce protocol.Bytes32) x402.H32 {
	unlock := s.lock(nonce)
	defer unlock()
	rec, err := s.getRecord(nonce)
	if err == nil && rec != nil && rec.State == StateSettling {
		if ok, _, cerr := s.confirm(ctx, rec); cerr == nil && ok {
			rec.Settlement = s.settlementFromLedger(ctx, rec, "")
			if s.putRecord(rec) != nil {
				return x402.H32{}
			}
		}
	}
	if err == nil && rec != nil && rec.State == StateSettled {
		if derr := s.deliver(ctx, rec); derr != nil {
			s.opt.Log.Printf("late delivery %s: %v", rec.Nonce, derr)
		}
	}
	if err != nil || rec == nil || rec.Receipt == nil {
		s.opt.Log.Printf("ledger nonce %s has no receipt; anchoring a zero leaf", x402.H32(nonce))
		return x402.H32{}
	}
	return x402.H32(rec.Receipt.Digest())
}

// answerCases records served bundles for open serve requests and publishes
// the response on chain after an escalation.
func (s *Seller) answerCases(ctx context.Context, b uint64) error {
	return s.eachRecord(func(nonce protocol.Bytes32) error {
		rec, err := s.getRecord(nonce)
		if err != nil || rec == nil || (rec.State != StateSettled && rec.State != StateDelivered) {
			return err
		}
		cs, err := s.chain.GetCase(ctx, nonce)
		if err != nil {
			return err
		}
		if s.directed(cs) {
			return s.answerDirected(ctx, nonce, rec, cs, b)
		}
		switch cs.State {
		case chain.CaseServeWait:
			if b > cs.ServeDue {
				return nil
			}
			return s.served(ctx, nonce, cs)
		case chain.CasePublishing:
			if b > cs.PublishDue {
				return nil
			}
			return s.publish(ctx, nonce)
		}
		return nil
	})
}

func (s *Seller) served(ctx context.Context, nonce protocol.Bytes32, cs chain.Case) error {
	unlock := s.lock(nonce)
	defer unlock()
	bundle, err := s.bundleLocked(ctx, nonce)
	if err != nil {
		return err
	}
	rec, err := s.getRecord(nonce)
	if err != nil {
		return err
	}
	h := bundle.BundleHash
	rec.BundleHash = &h
	rec.ServedCase = cs.CaseOpenedBlock
	if err = s.putRecord(rec); err != nil {
		return err
	}
	_, err = s.chain.Served(ctx, nonce, protocol.Bytes32(h))
	return err
}

// publish uses the single-call form for a body of at most one chunk and the
// chunked form otherwise. Chunk progress is persisted so a restart resumes.
func (s *Seller) publish(ctx context.Context, nonce protocol.Bytes32) error {
	unlock := s.lock(nonce)
	defer unlock()
	rec, err := s.getRecord(nonce)
	if err != nil {
		return err
	}
	if rec.Receipt == nil || rec.Response == nil || rec.Request == nil {
		return errors.New("no retained response to publish")
	}
	sig, err := rec.Receipt.SignatureBytes()
	if err != nil {
		return err
	}
	pub := chain.Publication{Nonce: nonce, Key: protocol.Bytes16(rec.Key), Request: *rec.Request, Receipt: rec.Receipt.Typed(), Signature: sig}
	body := rec.Response.Body
	if len(body) <= protocol.ResponseChunkBytes {
		pub.Body = body
		if _, err = s.chain.Publish(ctx, pub); err != nil {
			return err
		}
		rec.Published = true
		return s.putRecord(rec)
	}
	count := (len(body) + protocol.ResponseChunkBytes - 1) / protocol.ResponseChunkBytes
	if rec.Chunks == nil {
		if _, err = s.chain.BeginPublication(ctx, pub, uint32(len(body)), uint16(count)); err != nil {
			return err
		}
		rec.Chunks = make([]bool, count)
		if err = s.putRecord(rec); err != nil {
			return err
		}
	}
	for i := 0; i < count; i++ {
		if rec.Chunks[i] {
			continue
		}
		end := (i + 1) * protocol.ResponseChunkBytes
		if end > len(body) {
			end = len(body)
		}
		if _, err = s.chain.PublishChunk(ctx, nonce, uint16(i), body[i*protocol.ResponseChunkBytes:end]); err != nil {
			return err
		}
		rec.Chunks[i] = true
		if err = s.putRecord(rec); err != nil {
			return err
		}
	}
	if _, err = s.chain.FinalizePublication(ctx, nonce); err != nil {
		return err
	}
	rec.Published = true
	return s.putRecord(rec)
}

// prune drops request and response bytes after retentionBlocks when no case
// is open. The receipt stays so proofs and receipts remain available.
func (s *Seller) prune(ctx context.Context, b uint64) error {
	return s.eachRecord(func(nonce protocol.Bytes32) error {
		unlock := s.lock(nonce)
		defer unlock()
		rec, err := s.getRecord(nonce)
		if err != nil || rec == nil || rec.State != StateDelivered || rec.RetainUntil == 0 || b <= rec.RetainUntil {
			return err
		}
		cs, err := s.chain.GetCase(ctx, nonce)
		if err != nil {
			return err
		}
		switch cs.State {
		case chain.CaseNone, chain.CaseDelivered, chain.CaseUnserved, chain.CaseInconclusive, chain.CaseFinal:
		default:
			return nil
		}
		rec.Request, rec.Response, rec.Payload = nil, nil, nil
		rec.State = StatePruned
		return s.putRecord(rec)
	})
}
