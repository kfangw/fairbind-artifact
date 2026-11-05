// Package keeper calls FairBind public progress transitions once their fixed
// block deadlines have passed. It chooses no outcome: every call it makes takes
// only identifiers (a nonce, a seller and epoch, or a bond), and the contract
// decides the result. The keeper holds no verdict key and signs nothing itself;
// transactions go through an operator-supplied Sender.
//
// Decisions are made from views pinned to the finalized block. Because the
// finalized block never exceeds the block that will include a transaction, a
// deadline that has passed at the finalized block has also passed on chain.
package keeper

import (
	"context"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"sort"

	"example.org/fairbind/protocol"
)

// Enum values from contract-interface-v1.md section 2.
const (
	finNone uint8 = iota
	finDeferred
	finHeld
	finFrozenClaimable
	finRefundable
	finRefunded
	finReleasable
	finReleased
	finForfeited
)

const (
	epochNone uint8 = iota
	epochAnchored
	epochSealed
	epochFailed
)

const (
	caseNone uint8 = iota
	caseServeWait
	caseServeConfirm
	casePublishing
	caseAssigning
	caseJudging
	caseInitialVerdict
	casePartyReview
	caseAutoReview
	caseTiebreak
	caseDelivered
	caseUnserved
	caseInconclusive
	caseFinal
)

// blockhashWindow is the number of past blocks whose hash the EVM serves;
// seal reads blockhash(randomBlock).
const blockhashWindow uint64 = 256

const (
	freezeNone          uint8 = 0
	freezeFrozen        uint8 = 1
	freezeClaimOpen     uint8 = 2
	verdictPass         uint8 = 1
	verdictFail         uint8 = 2
	verdictInconclusive uint8 = 3
)

// Action names. Each is a public progress call from lifecycle-v1.md section 10.
const (
	ActTimeoutAnchor        = "timeoutAnchor"
	ActSeal                 = "seal"
	ActTimeoutSeal          = "timeoutSeal"
	ActOpenSample           = "openSample"
	ActAssignVerifier       = "assignVerifier"
	ActTimeoutJudge         = "timeoutJudge"
	ActTimeoutEvidence      = "timeoutEvidence"
	ActSealReviewRandomness = "sealReviewRandomness"
	ActOpenAutoRecheck      = "openAutoRecheck"
	ActFinalizeCase         = "finalizeCase"
	ActTimeoutServe         = "timeoutServe"
	ActFinalizeServed       = "finalizeServed"
	ActReleasePurchase      = "releasePurchase"
	ActForfeitUnclaimed     = "forfeitUnclaimed"
	ActFreezeSellerDeferred = "freezeSellerDeferred"
	ActReleaseFrozen        = "releaseFrozen"
	// Rule D2-17 (ADR 0024, ADR 0025): put a sample case's receipt and
	// inclusion proof on chain from the published receipt list, and end the
	// case UNSERVED once its receipt deadline has passed without them.
	ActSubmitSampleReceipt  = "submitSampleReceipt"
	ActTimeoutSampleReceipt = "timeoutSampleReceipt"
)

// AllActions lists every action the keeper can take, in a stable order.
var AllActions = []string{
	ActTimeoutAnchor, ActSeal, ActTimeoutSeal, ActOpenSample, ActAssignVerifier,
	ActTimeoutJudge, ActTimeoutEvidence, ActSealReviewRandomness, ActOpenAutoRecheck,
	ActFinalizeCase, ActTimeoutServe, ActFinalizeServed, ActReleasePurchase, ActForfeitUnclaimed,
	ActFreezeSellerDeferred, ActReleaseFrozen, ActSubmitSampleReceipt, ActTimeoutSampleReceipt,
}

var signatures = map[string]string{
	ActTimeoutAnchor:        "timeoutAnchor(uint32,uint24)",
	ActSeal:                 "seal(uint32,uint24)",
	ActTimeoutSeal:          "timeoutSeal(uint32,uint24)",
	ActOpenSample:           "openSample(bytes32)",
	ActAssignVerifier:       "assignVerifier(bytes32)",
	ActTimeoutJudge:         "timeoutJudge(bytes32)",
	ActTimeoutEvidence:      "timeoutEvidence(bytes32,uint8,uint8)",
	ActSealReviewRandomness: "sealReviewRandomness(bytes32)",
	ActOpenAutoRecheck:      "openAutoRecheck(bytes32)",
	ActFinalizeCase:         "finalizeCase(bytes32)",
	ActTimeoutServe:         "timeoutServe(bytes32)",
	ActFinalizeServed:       "finalizeServed(bytes32)",
	ActReleasePurchase:      "releasePurchase(bytes32)",
	ActForfeitUnclaimed:     "forfeitUnclaimed(uint32)",
	ActFreezeSellerDeferred: "freezeSellerDeferred(bytes32)",
	ActReleaseFrozen:        "releaseFrozen(uint32)",
	// Built by SubmitSampleReceiptData, not CallData: the receipt, signature
	// and proof are dynamic arguments.
	ActSubmitSampleReceipt:  "submitSampleReceipt(bytes32,(uint8,uint32,uint32,bytes32,bytes32,bytes32,bytes32,bytes32,uint24,uint64),bytes,(uint32,uint32,bytes32[]))",
	ActTimeoutSampleReceipt: "timeoutSampleReceipt(bytes32)",
}

// Block is a finalized block reference. All views are read at its hash.
type Block struct {
	Number uint64
	Hash   protocol.Bytes32
}

// Settlement is the part of a Settled event the keeper tracks.
type Settlement struct {
	Nonce                       protocol.Bytes32
	SellerID, BondID, ProfileID uint32
	Epoch                       uint32
}

// Timing holds the profile fields that fix epoch deadlines.
type Timing struct {
	EpochOrigin, EpochBlocks, AnchorBlocks, OpenBlocks uint64
	// SealBlocks and MaxAssignments are read for the worst-path directive: the
	// review seal window and the last assignment of a stage.
	SealBlocks     uint64
	MaxAssignments uint64
	// FreezeOnInitialFail is the profile flag of ADR 0020: only under it does
	// an initial FAIL freeze the bond account and can freezeSellerDeferred act.
	FreezeOnInitialFail bool
}

// AnchorDeadline follows lifecycle-v1.md section 1.
func (t Timing) AnchorDeadline(epoch uint32) uint64 {
	return t.EpochOrigin + (uint64(epoch)+2)*t.EpochBlocks - 1 + t.AnchorBlocks
}

type Purchase struct {
	ClaimUntil, ReleaseBlock, RetainUntil uint64
	FinancialState                        uint8
}

type Case struct {
	State, Stage, Attempt, InitialVerdict, Trigger                           uint8
	AssignedVerifierID                                                       uint32
	ServeDue, ChallengeUntil, PublishDue, RandomBlock, JudgeDue, EvidenceDue uint64
	// SampleReceiptDue is the last block for the receipt and inclusion proof
	// of a sample case, zero once they are on chain (getSampleReceiptDue).
	SampleReceiptDue uint64
}

// SignedReceipt is one entry of the published receipt list of an anchored
// epoch: the seller-signed receipt and its inclusion proof in the root.
type SignedReceipt struct {
	Receipt   protocol.Receipt
	Signature []byte
	Proof     protocol.ReceiptProof
}

// ReceiptList is the receipt list sellers publish for their anchored epochs
// (assumption A-LEAF, design 2 rule D2-10 (e)). The keeper reads a sample
// case's receipt from it and puts it on chain when nobody else has.
type ReceiptList interface {
	SampleReceipt(ctx context.Context, nonce protocol.Bytes32) (SignedReceipt, bool, error)
}

type Anchor struct {
	State                     uint8
	RandomBlock, SealDeadline uint64
}

type Bond struct {
	FreezeState     uint8
	FreezeBlock     uint64
	ClaimUntilBlock uint64
}

// Chain is the read side of the ledger. View methods read at the given
// finalized block. Simulate runs a call against the latest block and returns
// an error when it would revert.
type Chain interface {
	Finalized(ctx context.Context) (Block, error)
	Settlements(ctx context.Context, from, to uint64) ([]Settlement, error)
	Timing(ctx context.Context, at Block, profileID uint32) (Timing, error)
	Purchase(ctx context.Context, at Block, nonce protocol.Bytes32) (Purchase, error)
	PurchaseState(ctx context.Context, at Block, nonce protocol.Bytes32) (uint8, error)
	Case(ctx context.Context, at Block, nonce protocol.Bytes32) (Case, error)
	Sampled(ctx context.Context, at Block, nonce protocol.Bytes32) (eligible, known bool, err error)
	Anchor(ctx context.Context, at Block, sellerID, epoch uint32) (Anchor, error)
	Bond(ctx context.Context, at Block, bondID uint32) (Bond, error)
	Simulate(ctx context.Context, data []byte) error
}

// DirectedChain is the additional read side the worst-path directive needs: the
// latest block (the directive times every call to the block that includes it,
// so views are read at the latest block and calls are simulated against the
// pending one) and the review reseal bits of a case.
type DirectedChain interface {
	Chain
	Latest(ctx context.Context) (Block, error)
	ReviewReseals(ctx context.Context, at Block, nonce protocol.Bytes32) (uint8, error)
	// ReviewResealDue reads getReviewResealDue(nonce): the last block of the
	// reopened seal window of the current review stage (ADR 0025).
	ReviewResealDue(ctx context.Context, at Block, nonce protocol.Bytes32) (uint64, error)
}

// Sender submits one transaction to the contract. runtime/judgment.LocalRelay
// satisfies it for a loopback development node.
type Sender interface {
	Send(ctx context.Context, to protocol.Address, data []byte) (protocol.Bytes32, error)
}

// Action is one planned call. Key names the call together with the state it
// answers, so a later deadline of the same object yields a different key.
type Action struct {
	Name string
	Key  string
	Data []byte
	// Due is the first block at which the call is due (for a timeout, the block
	// after its deadline); the keeper delay of a call is its inclusion block
	// minus Due. Nonce names the case of a per-purchase call and Epoch
	// ("sellerId:epoch") the epoch of an epoch call.
	Due   uint64
	Nonce string
	Epoch string
}

type Keeper struct {
	Chain    Chain
	Sender   Sender
	Contract protocol.Address
	Store    *Store
	// Enabled restricts the actions taken; nil enables all.
	Enabled map[string]bool
	// ResendAfter is the number of finalized blocks to wait before sending the
	// same action again when its state has not moved.
	ResendAfter uint64
	// MaxLogRange bounds one event query.
	MaxLogRange uint64
	// StartBlock is the first block scanned when the state file is new.
	StartBlock uint64
	// WorstPath enables the worst-path directive (experiments/controller/
	// worstpath.py): every call lands in the first block it is valid in, seal and
	// openSample land at the end of their windows, and the first seal window of
	// every review stage of a sampled case lapses before the reopened stage is
	// sealed at its deadline. Chain must then be a DirectedChain.
	WorstPath bool
	// DelayBlocks is the per-case keeper delay budget (kappa): the last keeper
	// call before the confirmed failure of a sampled case on the worst path (the
	// tiebreak replacement of its next-to-last assignment, or the tiebreak seal
	// when a stage has one assignment) lands DelayBlocks after it is due.
	DelayBlocks uint64
	// Receipts is the published receipt list (A-LEAF). With it the keeper puts
	// the receipt of an open sample case on chain before its deadline; without
	// it the keeper only ends the case UNSERVED after the deadline. Under the
	// worst-path directive both receipt calls need it.
	Receipts ReceiptList
}

// Outcome records what happened to one planned action in a tick.
type Outcome struct {
	Action Action
	Status string // "sent", "pending", "disabled", "rejected", "error"
	Tx     string
	Err    string
}

type Report struct {
	Finalized uint64
	// Head is the latest block the pass read under the worst-path directive
	// (equal to Finalized otherwise); its calls are included from Head + 1.
	Head     uint64
	Outcomes []Outcome
}

// Tick scans new finalized settlements, plans every eligible call and submits
// those not already in flight. It is safe to call repeatedly and after a
// restart: submitted actions are recorded before broadcast, and the contract
// rejects a duplicate or premature call without changing state.
func (k *Keeper) Tick(ctx context.Context) (Report, error) {
	if k.Chain == nil || k.Sender == nil || k.Store == nil || k.Contract == (protocol.Address{}) {
		return Report{}, fmt.Errorf("incomplete keeper")
	}
	head, now, err := k.head(ctx)
	if err != nil {
		return Report{}, err
	}
	st := k.Store.State()
	if st.Scanned > 0 && head.Number < st.Scanned {
		return Report{}, fmt.Errorf("finalized block %d is below scanned block %d", head.Number, st.Scanned)
	}
	if err = k.scan(ctx, head.Number); err != nil {
		return Report{}, err
	}
	actions, done, err := k.plan(ctx, head, now)
	if err != nil {
		return Report{}, err
	}
	rep := Report{Finalized: head.Number, Head: head.Number}
	planned := map[string]bool{}
	for _, a := range actions {
		planned[a.Key] = true
		rep.Outcomes = append(rep.Outcomes, k.execute(ctx, head.Number, a))
	}
	if err = k.Store.Update(func(s *State) {
		for key := range s.Sent {
			if !planned[key] {
				delete(s.Sent, key)
			}
		}
		for _, n := range done.purchases {
			delete(s.Purchases, n)
		}
		for _, e := range done.epochs {
			delete(s.Epochs, e)
		}
	}); err != nil {
		return rep, err
	}
	return rep, nil
}

// head returns the block views are read at and the block number deadlines are
// compared with. By default both are the finalized block F: a deadline passed
// at F has passed on chain. Under the worst-path directive views are read at
// the latest block L and deadlines are compared with L + 1, the block that
// includes a call sent now, so a timeout lands in the block after its deadline.
func (k *Keeper) head(ctx context.Context) (Block, uint64, error) {
	if !k.WorstPath {
		b, err := k.Chain.Finalized(ctx)
		return b, b.Number, err
	}
	dc, ok := k.Chain.(DirectedChain)
	if !ok {
		return Block{}, 0, fmt.Errorf("the worst-path directive needs a chain with latest-block views")
	}
	b, err := dc.Latest(ctx)
	return b, b.Number + 1, err
}

func (k *Keeper) scan(ctx context.Context, head uint64) error {
	st := k.Store.State()
	from := k.StartBlock
	if st.Scanned > 0 || st.Started {
		from = st.Scanned + 1
	}
	span := k.MaxLogRange
	if span == 0 {
		span = 1000
	}
	for from <= head {
		to := from + span - 1
		if to > head || to < from {
			to = head
		}
		logs, err := k.Chain.Settlements(ctx, from, to)
		if err != nil {
			return err
		}
		if err = k.Store.Update(func(s *State) {
			for _, l := range logs {
				s.Purchases[hexKey(l.Nonce)] = TrackedPurchase{SellerID: l.SellerID, BondID: l.BondID, ProfileID: l.ProfileID, Epoch: l.Epoch}
				s.Epochs[epochKey(l.SellerID, l.Epoch)] = TrackedEpoch{SellerID: l.SellerID, ProfileID: l.ProfileID, Epoch: l.Epoch}
				s.Bonds[fmt.Sprint(l.BondID)] = l.BondID
			}
			s.Scanned = to
			s.Started = true
		}); err != nil {
			return err
		}
		from = to + 1
	}
	return nil
}

type retired struct{ purchases, epochs []string }

func (k *Keeper) plan(ctx context.Context, head Block, now uint64) ([]Action, retired, error) {
	st := k.Store.State()
	var out []Action
	var done retired
	timings := map[uint32]Timing{}
	timing := func(pid uint32) (Timing, error) {
		if t, ok := timings[pid]; ok {
			return t, nil
		}
		t, err := k.Chain.Timing(ctx, head, pid)
		if err != nil {
			return t, err
		}
		if t.EpochBlocks == 0 {
			return t, fmt.Errorf("profile %d has zero epochBlocks", pid)
		}
		timings[pid] = t
		return t, nil
	}
	anchors := map[string]Anchor{}
	anchor := func(sid, epoch uint32) (Anchor, error) {
		key := epochKey(sid, epoch)
		if a, ok := anchors[key]; ok {
			return a, nil
		}
		a, err := k.Chain.Anchor(ctx, head, sid, epoch)
		if err == nil {
			anchors[key] = a
		}
		return a, err
	}
	bonds := map[uint32]Bond{}
	bond := func(id uint32) (Bond, error) {
		if b, ok := bonds[id]; ok {
			return b, nil
		}
		b, err := k.Chain.Bond(ctx, head, id)
		if err == nil {
			bonds[id] = b
		}
		return b, err
	}

	for _, key := range sortedKeys(st.Epochs) {
		e := st.Epochs[key]
		t, err := timing(e.ProfileID)
		if err != nil {
			return nil, done, err
		}
		a, err := anchor(e.SellerID, e.Epoch)
		if err != nil {
			return nil, done, err
		}
		args := [][]byte{word(uint64(e.SellerID)), word(uint64(e.Epoch))}
		epochAct := func(name string, due uint64) Action {
			a := action(name, key, args...)
			a.Due, a.Epoch = due, key
			return a
		}
		switch a.State {
		case epochNone:
			if now > t.AnchorDeadline(e.Epoch) {
				out = append(out, epochAct(ActTimeoutAnchor, t.AnchorDeadline(e.Epoch)+1))
			}
		case epochAnchored:
			// Rule D2-16 (ADR 0029): an anchored epoch waits for its value. seal
			// stays valid after sealDeadline while the chain serves the block
			// hash; timeoutSeal ends the epoch only when its checkpoint is
			// short, and reverts otherwise, so it is tried once the value is
			// no longer served.
			switch {
			case now > a.RandomBlock+blockhashWindow:
				out = append(out, epochAct(ActTimeoutSeal, a.RandomBlock+blockhashWindow+1))
			case k.WorstPath && now <= a.SealDeadline:
				// The worst path seals in the last block of the seal window.
				if now == a.SealDeadline {
					out = append(out, epochAct(ActSeal, a.SealDeadline))
				}
			case now > a.RandomBlock:
				out = append(out, epochAct(ActSeal, a.RandomBlock+1))
			}
		default:
			done.epochs = append(done.epochs, key)
		}
	}

	for _, key := range sortedKeys(st.Purchases) {
		p := st.Purchases[key]
		nonce, err := parseKey(key)
		if err != nil {
			return nil, done, err
		}
		acts, finished, err := k.planPurchase(ctx, head, now, nonce, p, timing, anchor)
		if err != nil {
			return nil, done, err
		}
		if !finished {
			receipt, err := k.planReceipt(ctx, head, now, nonce)
			if err != nil {
				return nil, done, err
			}
			acts = append(receipt, acts...)
		}
		for i := range acts {
			acts[i].Nonce = key
		}
		out = append(out, acts...)
		if finished {
			done.purchases = append(done.purchases, key)
		}
		freeze, err := k.planFreeze(ctx, head, nonce, p, timing, bond)
		if err != nil {
			return nil, done, err
		}
		out = append(out, freeze...)
	}

	bondIDs := make([]uint32, 0, len(st.Bonds))
	for _, id := range st.Bonds {
		bondIDs = append(bondIDs, id)
	}
	sort.Slice(bondIDs, func(i, j int) bool { return bondIDs[i] < bondIDs[j] })
	for _, id := range bondIDs {
		b, err := bond(id)
		if err != nil {
			return nil, done, err
		}
		switch {
		case b.FreezeState == freezeClaimOpen && now > b.ClaimUntilBlock:
			out = append(out, action(ActForfeitUnclaimed, fmt.Sprintf("%d:%d", id, b.ClaimUntilBlock), word(uint64(id))))
		case b.FreezeState == freezeFrozen:
			// The contract itself performs the release inline on overturn; this
			// call only catches a trigger case that ended without a failure
			// through some other path. A freeze whose trigger case is still
			// open, or that did end in failure, is rejected by Simulate.
			out = append(out, action(ActReleaseFrozen, fmt.Sprintf("%d:%d", id, b.FreezeBlock), word(uint64(id))))
		}
	}
	return out, done, nil
}

// planReceipt plans the receipt calls of a sample case (rule D2-17). Before
// the deadline it submits the receipt from the published list, once per
// deadline; in the first block after the deadline it calls
// timeoutSampleReceipt, which ends the case UNSERVED. Under the worst-path
// directive it acts only with a receipt list, and submits in the deadline
// block, so that a run without one keeps the case on its worst path.
func (k *Keeper) planReceipt(ctx context.Context, head Block, now uint64, nonce protocol.Bytes32) ([]Action, error) {
	c, err := k.Chain.Case(ctx, head, nonce)
	if err != nil {
		return nil, err
	}
	if c.Trigger != triggerSample || c.SampleReceiptDue == 0 || caseTerminal(c.State) {
		return nil, nil
	}
	if k.WorstPath && k.Receipts == nil {
		return nil, nil
	}
	key := fmt.Sprintf("%s:%d", hexKey(nonce), c.SampleReceiptDue)
	if now > c.SampleReceiptDue {
		return []Action{due(action(ActTimeoutSampleReceipt, key, nonce[:]), c.SampleReceiptDue+1)}, nil
	}
	if k.Receipts == nil || (k.WorstPath && now != c.SampleReceiptDue) {
		return nil, nil
	}
	r, ok, err := k.Receipts.SampleReceipt(ctx, nonce)
	if err != nil || !ok {
		return nil, err
	}
	data, err := SubmitSampleReceiptData(nonce, r)
	if err != nil {
		return nil, err
	}
	return []Action{{Name: ActSubmitSampleReceipt, Key: ActSubmitSampleReceipt + ":" + key, Data: data, Due: now}}, nil
}

// SubmitSampleReceiptData is the ABI encoding of
// submitSampleReceipt(nonce, receipt, signature, proof).
func SubmitSampleReceiptData(nonce protocol.Bytes32, r SignedReceipt) ([]byte, error) {
	if len(r.Signature) != 65 || r.Receipt.Nonce != nonce {
		return nil, fmt.Errorf("receipt for %s: bad signature length or nonce", hexKey(nonce))
	}
	sel := protocol.Keccak256([]byte(signatures[ActSubmitSampleReceipt]))
	out := append([]byte{}, sel[:4]...)
	rc := r.Receipt
	head := [][]byte{nonce[:], word(uint64(rc.Version)), word(uint64(rc.SellerID)), word(uint64(rc.ProfileID)),
		rc.Nonce[:], rc.RequestHash[:], rc.ResponseHash[:], rc.ClaimsHash[:], rc.PredicateCommitment[:],
		word(uint64(rc.Epoch)), word(rc.IssuedAt)}
	// Eleven static words, then the offsets of the signature and the proof.
	const headLen = 13 * 32
	sig := append(word(uint64(len(r.Signature))), r.Signature...)
	sig = append(sig, make([]byte, (32-len(r.Signature)%32)%32)...)
	proof := append(word(uint64(r.Proof.Index)), word(uint64(r.Proof.Count))...)
	proof = append(proof, word(3*32)...)
	proof = append(proof, word(uint64(len(r.Proof.Siblings)))...)
	for _, h := range r.Proof.Siblings {
		proof = append(proof, h[:]...)
	}
	for _, w := range head {
		out = append(out, w...)
	}
	out = append(out, word(headLen)...)
	out = append(out, word(uint64(headLen+len(sig)))...)
	out = append(out, sig...)
	return append(out, proof...), nil
}

// caseTerminal reports whether a case state is one of the machine's ended
// states: no purchase held by a still-open case can be released or forfeited.
func caseTerminal(state uint8) bool {
	switch state {
	case caseDelivered, caseUnserved, caseInconclusive, caseFinal:
		return true
	}
	return false
}

// planFreeze proposes freezeSellerDeferred(nonce) when this purchase's own
// case holds an initial FAIL that is not yet terminal, its profile freezes at
// the initial FAIL, and its bond account carries no freeze. It is independent
// of planPurchase's release/timeout switch: a case can be a freeze trigger in
// any of its nonterminal states.
func (k *Keeper) planFreeze(ctx context.Context, head Block, nonce protocol.Bytes32, p TrackedPurchase,
	timing func(uint32) (Timing, error), bond func(uint32) (Bond, error)) ([]Action, error) {
	c, err := k.Chain.Case(ctx, head, nonce)
	if err != nil {
		return nil, err
	}
	if c.InitialVerdict != verdictFail || caseTerminal(c.State) {
		return nil, nil
	}
	t, err := timing(p.ProfileID)
	if err != nil {
		return nil, err
	}
	if !t.FreezeOnInitialFail {
		return nil, nil
	}
	b, err := bond(p.BondID)
	if err != nil {
		return nil, err
	}
	if b.FreezeState != freezeNone {
		return nil, nil
	}
	// This purchase's own case is the trigger for its bond's freeze.
	return []Action{action(ActFreezeSellerDeferred, hexKey(nonce), nonce[:])}, nil
}

func (k *Keeper) planPurchase(ctx context.Context, head Block, now uint64, nonce protocol.Bytes32, p TrackedPurchase,
	timing func(uint32) (Timing, error), anchor func(uint32, uint32) (Anchor, error)) ([]Action, bool, error) {
	n := nonce[:]
	id := hexKey(nonce)
	ps, err := k.Chain.PurchaseState(ctx, head, nonce)
	if err != nil {
		return nil, false, err
	}
	pv, err := k.Chain.Purchase(ctx, head, nonce)
	if err != nil {
		return nil, false, err
	}
	switch ps {
	case finRefundable, finRefunded, finReleased:
		return nil, true, nil
	case finForfeited:
		if pv.FinancialState == finForfeited {
			return nil, true, nil
		}
	}
	c, err := k.Chain.Case(ctx, head, nonce)
	if err != nil {
		return nil, false, err
	}
	a, err := anchor(p.SellerID, p.Epoch)
	if err != nil {
		return nil, false, err
	}
	t, err := timing(p.ProfileID)
	if err != nil {
		return nil, false, err
	}
	stageKey := fmt.Sprintf("%s:%d:%d", id, c.Stage, c.Attempt)
	release := func() []Action {
		if ps == finForfeited {
			// The principal left with the closed claim window; the call only
			// settles the deposits of a finished case.
			return []Action{action(ActReleasePurchase, id, n)}
		}
		if (ps != finDeferred && ps != finReleasable) || a.State != epochSealed {
			return nil
		}
		if now <= pv.ClaimUntil || now <= a.SealDeadline+t.OpenBlocks ||
			now < pv.ReleaseBlock || now < pv.RetainUntil {
			return nil
		}
		return []Action{due(action(ActReleasePurchase, id, n), max(pv.ClaimUntil+1, a.SealDeadline+t.OpenBlocks+1, pv.ReleaseBlock, pv.RetainUntil))}
	}
	directed := k.WorstPath && c.Trigger == triggerSample
	switch c.State {
	case caseNone:
		if a.State == epochFailed {
			// Refunds after an epoch failure belong to the buyer.
			return nil, true, nil
		}
		if a.State != epochSealed {
			return nil, false, nil
		}
		eligible, known, err := k.Chain.Sampled(ctx, head, nonce)
		if err != nil {
			return nil, false, err
		}
		if !known {
			return nil, false, nil
		}
		if eligible && ps != finForfeited {
			if k.WorstPath {
				// The worst path opens the sample in the last block of the open window.
				if end := a.SealDeadline + t.OpenBlocks; now == end {
					return []Action{due(action(ActOpenSample, id, n), end)}, false, nil
				}
				return nil, false, nil
			}
			return []Action{due(action(ActOpenSample, id, n), a.SealDeadline+1)}, false, nil
		}
		return release(), false, nil
	case caseAssigning:
		if a.State == epochSealed {
			return []Action{action(ActAssignVerifier, stageKey, n)}, false, nil
		}
	case caseJudging, casePartyReview, caseAutoReview, caseTiebreak:
		if c.AssignedVerifierID != 0 {
			d := c.JudgeDue + 1
			if directed && k.delayed(c, t, ActTimeoutJudge) {
				d += k.DelayBlocks
			}
			if now >= d {
				return []Action{due(action(ActTimeoutJudge, fmt.Sprintf("%s:%d", stageKey, c.JudgeDue), n), c.JudgeDue+1)}, false, nil
			}
		} else if c.State != caseJudging && c.RandomBlock != 0 && directed {
			return k.planReviewSeal(ctx, head, now, nonce, c, t, stageKey)
		} else if c.State != caseJudging && c.RandomBlock != 0 && now > c.RandomBlock {
			return []Action{due(action(ActSealReviewRandomness, fmt.Sprintf("%s:%d", stageKey, c.RandomBlock), n), c.RandomBlock+1)}, false, nil
		}
	case caseInitialVerdict:
		if c.EvidenceDue != 0 && now > c.EvidenceDue {
			return []Action{due(action(ActTimeoutEvidence, fmt.Sprintf("%s:%d", stageKey, c.EvidenceDue),
				n, word(uint64(c.Stage)), word(uint64(c.Attempt))), c.EvidenceDue+1)}, false, nil
		}
		// randomBlock = appealUntil + 1 while an initial verdict waits.
		if c.RandomBlock == 0 {
			return nil, false, nil
		}
		// An unappealed PASS or INCONCLUSIVE passes the recheck gate one block
		// after its candidate block (ADR 0019); a FAIL is final at the candidate block.
		if c.InitialVerdict != verdictFail {
			if now > c.RandomBlock {
				return []Action{due(action(ActOpenAutoRecheck, fmt.Sprintf("%s:%d", stageKey, c.RandomBlock), n), c.RandomBlock+1)}, false, nil
			}
		} else if now >= c.RandomBlock {
			return []Action{due(action(ActFinalizeCase, fmt.Sprintf("%s:%d", stageKey, c.RandomBlock), n), c.RandomBlock)}, false, nil
		}
	case caseServeWait:
		if now > c.ServeDue {
			return []Action{due(action(ActTimeoutServe, fmt.Sprintf("%s:w:%d", id, c.ServeDue), n), c.ServeDue+1)}, false, nil
		}
	case casePublishing:
		if now > c.PublishDue {
			return []Action{due(action(ActTimeoutServe, fmt.Sprintf("%s:p:%d", id, c.PublishDue), n), c.PublishDue+1)}, false, nil
		}
	case caseServeConfirm:
		if now > c.ChallengeUntil {
			return []Action{due(action(ActFinalizeServed, fmt.Sprintf("%s:%d", id, c.ChallengeUntil), n), c.ChallengeUntil+1)}, false, nil
		}
	case caseDelivered:
		if c.Trigger == triggerNonDelivery {
			// A non-delivery dispute that ended as delivered still owes its
			// sample case when the purchase is sampled (ADR 0024, rule 94a).
			if a.State == epochFailed {
				return nil, true, nil
			}
			if a.State != epochSealed {
				return nil, false, nil
			}
			eligible, known, err := k.Chain.Sampled(ctx, head, nonce)
			if err != nil {
				return nil, false, err
			}
			if !known {
				return nil, false, nil
			}
			if eligible && ps != finForfeited {
				return []Action{due(action(ActOpenSample, id, n), a.SealDeadline+1)}, false, nil
			}
		}
		return release(), false, nil
	case caseInconclusive, caseFinal:
		return release(), false, nil
	case caseUnserved:
		return nil, true, nil
	}
	return nil, false, nil
}

// triggerSample is CaseTrigger.SAMPLE: the worst-path directive applies to
// cases opened by sampling.
const triggerSample uint8 = 1

// triggerNonDelivery is CaseTrigger.NON_DELIVERY.
const triggerNonDelivery uint8 = 2

func due(a Action, block uint64) Action {
	a.Due = block
	return a
}

// delayed reports whether a call on a sampled worst-path case is the one that
// spends the keeper delay budget: the last keeper call before the confirmed
// failure. On the worst path the tiebreak's last assignment delivers the
// confirming FAIL, so that call is the timeoutJudge that replaces the
// next-to-last tiebreak assignment, or, with one assignment per stage, the
// reopened tiebreak seal.
func (k *Keeper) delayed(c Case, t Timing, name string) bool {
	if k.DelayBlocks == 0 || c.State != caseTiebreak {
		return false
	}
	if t.MaxAssignments <= 1 {
		return name == ActSealReviewRandomness
	}
	return name == ActTimeoutJudge && uint64(c.Attempt)+2 == t.MaxAssignments
}

// planReviewSeal lets the first seal window of a review stage lapse
// (finalizeCase in the block after it reopens the seal, ADR 0021) and seals
// the reopened stage in the last block of its window.
func (k *Keeper) planReviewSeal(ctx context.Context, head Block, now uint64, nonce protocol.Bytes32, c Case, t Timing, stageKey string) ([]Action, bool, error) {
	dc, ok := k.Chain.(DirectedChain)
	if !ok {
		return nil, false, fmt.Errorf("the worst-path directive needs a chain with review reseal views")
	}
	bits, err := dc.ReviewReseals(ctx, head, nonce)
	if err != nil {
		return nil, false, err
	}
	end := c.RandomBlock + t.SealBlocks
	if bits&(1<<c.Stage) == 0 {
		if now > end {
			return []Action{due(action(ActFinalizeCase, fmt.Sprintf("%s:lapse:%d", stageKey, c.RandomBlock), nonce[:]), end+1)}, false, nil
		}
		return nil, false, nil
	}
	// The reopened seal keeps randomBlock; its window ends at the block the
	// contract recorded at the reopening (ADR 0025).
	end, err = dc.ReviewResealDue(ctx, head, nonce)
	if err != nil {
		return nil, false, err
	}
	d := end
	if k.delayed(c, t, ActSealReviewRandomness) {
		d += k.DelayBlocks
	}
	if now >= d {
		return []Action{due(action(ActSealReviewRandomness, fmt.Sprintf("%s:%d", stageKey, c.RandomBlock), nonce[:]), end)}, false, nil
	}
	return nil, false, nil
}

func (k *Keeper) execute(ctx context.Context, finalized uint64, a Action) Outcome {
	o := Outcome{Action: a}
	if k.Enabled != nil && !k.Enabled[a.Name] {
		o.Status = "disabled"
		return o
	}
	if prev, ok := k.Store.State().Sent[a.Key]; ok && finalized < prev.At+k.ResendAfter {
		o.Status, o.Tx = "pending", prev.Tx
		return o
	}
	if err := k.Chain.Simulate(ctx, a.Data); err != nil {
		o.Status, o.Err = "rejected", err.Error()
		return o
	}
	// Record intent before broadcast so a restart does not resend at once.
	if err := k.Store.Update(func(s *State) { s.Sent[a.Key] = SentRecord{Action: a.Name, At: finalized} }); err != nil {
		o.Status, o.Err = "error", err.Error()
		return o
	}
	tx, err := k.Sender.Send(ctx, k.Contract, a.Data)
	if err != nil {
		o.Status, o.Err = "error", err.Error()
		return o
	}
	o.Status, o.Tx = "sent", hexKey(tx)
	if err := k.Store.Update(func(s *State) { s.Sent[a.Key] = SentRecord{Action: a.Name, At: finalized, Tx: hexKey(tx)} }); err != nil {
		o.Err = err.Error()
	}
	return o
}

// CallData returns the ABI encoding of a keeper action with static arguments.
func CallData(name string, args ...[]byte) ([]byte, error) {
	sig, ok := signatures[name]
	if !ok {
		return nil, fmt.Errorf("unknown action %q", name)
	}
	sel := protocol.Keccak256([]byte(sig))
	data := append([]byte{}, sel[:4]...)
	for _, a := range args {
		if len(a) != 32 {
			return nil, fmt.Errorf("argument must be one ABI word")
		}
		data = append(data, a...)
	}
	return data, nil
}

func action(name, key string, args ...[]byte) Action {
	data, err := CallData(name, args...)
	if err != nil {
		panic(err)
	}
	return Action{Name: name, Key: name + ":" + key, Data: data}
}

func word(v uint64) []byte {
	w := make([]byte, 32)
	binary.BigEndian.PutUint64(w[24:], v)
	return w
}

func hexKey(b protocol.Bytes32) string { return "0x" + hex.EncodeToString(b[:]) }

func parseKey(s string) (b protocol.Bytes32, err error) {
	if len(s) != 66 || s[:2] != "0x" {
		return b, fmt.Errorf("invalid nonce key %q", s)
	}
	raw, err := hex.DecodeString(s[2:])
	copy(b[:], raw)
	return b, err
}

func epochKey(sellerID, epoch uint32) string { return fmt.Sprintf("%d:%d", sellerID, epoch) }

func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
