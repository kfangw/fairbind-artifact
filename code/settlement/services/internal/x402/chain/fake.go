package chain

import (
	"context"
	"encoding/binary"
	"errors"
	"sync"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/ethkey"
)

// Fault selects an injected failure for the next call of a method.
type Fault int

const (
	// FailBefore returns a transport error without executing the call.
	FailBefore Fault = iota + 1
	// LoseAfter executes the call, then returns a transport error, as when
	// a node accepted a transaction but the response was lost.
	LoseAfter
)

// ErrTransport is the error an injected fault returns.
var ErrTransport = errors.New("fake transport failure")

type FakeConfig struct {
	ChainID      uint64
	Contract     Address
	Token        Address
	TokenName    string
	TokenVersion string
}

type anchorKey struct {
	seller uint32
	epoch  uint32
}

type fakePublication struct {
	Publication
	totalBytes uint32
	chunks     [][]byte
	chunkSet   []bool
}

// Fake is an in-memory model of the FairBind contract subset used by the
// services. It executes each call at the current block; tests advance
// blocks with Mine. It checks signatures, identifiers, windows and callers
// for the calls it models, but it does not model sampling, judgment,
// reviews, seller penalties, the rate bucket or bond accounting.
type Fake struct {
	mu        sync.Mutex
	cfg       FakeConfig
	block     uint64
	time      uint64
	txCount   uint64
	profiles  map[uint32]Profile
	sellers   map[uint32]Seller
	bonds     map[uint32]Bond
	verifiers map[uint32]Verifier
	purchases map[Hash]Purchase
	byKey     map[Hash]Hash
	cases     map[Hash]Case
	anchors   map[anchorKey]Anchor
	settled   map[anchorKey][]Hash
	pubs      map[Hash]*fakePublication
	txs       map[Hash]TxStatus
	balances  map[Address]uint64
	faults    map[string]Fault
	calls     map[string]int
	details   map[Hash]CaseDetail
	exitAt    map[exitKey]uint64
}

// NewFake returns an empty fake chain at block 1.
func NewFake(cfg FakeConfig) *Fake {
	return &Fake{cfg: cfg, block: 1, time: 1_800_000_000,
		profiles: map[uint32]Profile{}, sellers: map[uint32]Seller{}, bonds: map[uint32]Bond{},
		verifiers: map[uint32]Verifier{}, purchases: map[Hash]Purchase{}, byKey: map[Hash]Hash{},
		cases: map[Hash]Case{}, anchors: map[anchorKey]Anchor{}, settled: map[anchorKey][]Hash{},
		pubs: map[Hash]*fakePublication{}, txs: map[Hash]TxStatus{}, balances: map[Address]uint64{},
		faults: map[string]Fault{}, calls: map[string]int{}, exitAt: map[exitKey]uint64{}}
}

// As returns a Client whose transactions are sent from addr.
func (f *Fake) As(addr Address) Client { return &fakeClient{f: f, from: addr} }

func (f *Fake) AddProfile(p Profile) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if p.Token == (Address{}) {
		p.Token = f.cfg.Token
	}
	f.profiles[p.ProfileID] = p
}
func (f *Fake) AddSeller(s Seller) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.sellers[s.SellerID] = s
}
func (f *Fake) AddBond(b Bond) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.bonds[b.BondID] = b
}
func (f *Fake) AddVerifier(v Verifier) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.verifiers[v.VerifierID] = v
}

// OpenCaseForTest sets a nonce's case record directly, bypassing the
// sampling and judgment machinery this fake does not model. Nonce is filled
// in from the argument when c.Nonce is zero. Tests use it to exercise a
// verifier-role redelivery authorization without a full judgment pipeline.
func (f *Fake) OpenCaseForTest(nonce Hash, c Case) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if c.Nonce == (Hash{}) {
		c.Nonce = nonce
	}
	f.cases[nonce] = c
}

// Mint credits the fake token balance of addr.
func (f *Fake) Mint(addr Address, amount uint64) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.balances[addr] += amount
}

// Balance returns the fake token balance of addr.
func (f *Fake) Balance(addr Address) uint64 {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.balances[addr]
}

// Mine advances the block number by n and the clock by 2 seconds per block.
func (f *Fake) Mine(n uint64) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.block += n
	f.time += 2 * n
}

// MineTo advances to block b if it is ahead.
func (f *Fake) MineTo(b uint64) {
	f.mu.Lock()
	cur := f.block
	f.mu.Unlock()
	if b > cur {
		f.Mine(b - cur)
	}
}

// Time returns the fake unix time used for authorization validity.
func (f *Fake) Time() uint64 {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.time
}

// Inject arms a fault for the next call of method (the Writer method name).
func (f *Fake) Inject(method string, fault Fault) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.faults[method] = fault
}

// Calls returns how many times a Writer method executed on chain.
func (f *Fake) Calls(method string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.calls[method]
}

// FreezeBond opens the claim window of a bond account at the current block.
func (f *Fake) FreezeBond(bondID uint32, claimWindowBlocks uint64) {
	f.mu.Lock()
	defer f.mu.Unlock()
	b := f.bonds[bondID]
	b.BondID = bondID
	b.FreezeState = FreezeClaimOpen
	b.FreezeBlock = f.block
	b.ClaimUntilBlock = f.block + claimWindowBlocks
	f.bonds[bondID] = b
}

func (f *Fake) newTx(status TxStatus) Hash {
	f.txCount++
	var b [8]byte
	binary.BigEndian.PutUint64(b[:], f.txCount)
	h := protocol.Keccak256([]byte("fake-tx"), b[:])
	f.txs[h] = status
	return h
}

// tx runs fn under the lock and applies fault injection and tx records.
func (f *Fake) tx(method string, fn func() error) (Hash, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	fault := f.faults[method]
	delete(f.faults, method)
	if fault == FailBefore {
		return Hash{}, ErrTransport
	}
	f.calls[method]++
	if err := fn(); err != nil {
		h := f.newTx(TxFailed)
		var r *RevertError
		if errors.As(err, &r) {
			r.Tx = h
		}
		return h, err
	}
	h := f.newTx(TxSucceeded)
	if fault == LoseAfter {
		return Hash{}, ErrTransport
	}
	return h, nil
}

func revert(name string) error { return &RevertError{Name: name} }

type fakeClient struct {
	f    *Fake
	from Address
}

func (c *fakeClient) ChainID() uint64   { return c.f.cfg.ChainID }
func (c *fakeClient) Contract() Address { return c.f.cfg.Contract }
func (c *fakeClient) From() Address     { return c.from }

func (c *fakeClient) BlockNumber(context.Context) (uint64, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	return c.f.block, nil
}

func (c *fakeClient) GetProfile(_ context.Context, id uint32) (Profile, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	return c.f.profiles[id], nil
}

func (c *fakeClient) GetSeller(_ context.Context, id uint32) (Seller, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	return c.f.sellers[id], nil
}

func (c *fakeClient) QuoteSeller(_ context.Context, id uint32) (Quote, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	s := c.f.sellers[id]
	p := c.f.profiles[s.ProfileID]
	return Quote{SellerID: id, ProfileID: s.ProfileID, ClaimsHash: s.ClaimsHash, Token: p.Token,
		MaxPurchaseValue: p.MaxPurchaseValue, Remaining: 20, QuotedAtBlock: c.f.block,
		CurrentEpoch: p.EpochAt(c.f.block), SellerStatus: s.Status, BondID: s.BondID}, nil
}

func (c *fakeClient) GetPurchase(_ context.Context, nonce Hash) (Purchase, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	return c.f.purchases[nonce], nil
}

func (c *fakeClient) PurchaseByKey(_ context.Context, keyID Hash) (Hash, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	return c.f.byKey[keyID], nil
}

func (f *Fake) frozenClaimable(p Purchase) bool {
	s := f.sellers[p.SellerID]
	b := f.bonds[s.BondID]
	return b.FreezeState == FreezeClaimOpen && p.SettledBlock <= b.FreezeBlock &&
		(p.FinancialState == FinDeferred || p.FinancialState == FinReleasable)
}

func (c *fakeClient) PurchaseState(_ context.Context, nonce Hash) (uint8, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	p := c.f.purchases[nonce]
	if c.f.frozenClaimable(p) {
		if c.f.block <= c.f.bonds[c.f.sellers[p.SellerID].BondID].ClaimUntilBlock {
			return FinFrozenClaimable, nil
		}
		return FinForfeited, nil
	}
	return p.FinancialState, nil
}

func (c *fakeClient) GetCase(_ context.Context, nonce Hash) (Case, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	return c.f.cases[nonce], nil
}

func (c *fakeClient) GetAnchor(_ context.Context, seller uint32, epoch uint32) (Anchor, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	return c.f.anchors[anchorKey{seller, epoch}], nil
}

func (c *fakeClient) GetBond(_ context.Context, id uint32) (Bond, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	return c.f.bonds[id], nil
}

func (c *fakeClient) GetVerifier(_ context.Context, id uint32) (Verifier, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	return c.f.verifiers[id], nil
}

func (c *fakeClient) SettledNonces(_ context.Context, seller uint32, epoch uint32) ([]Hash, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	return append([]Hash(nil), c.f.settled[anchorKey{seller, epoch}]...), nil
}

func (c *fakeClient) Publication(_ context.Context, nonce Hash) (*Publication, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	p := c.f.pubs[nonce]
	if p == nil || c.f.cases[nonce].State == CasePublishing {
		return nil, nil
	}
	out := p.Publication
	return &out, nil
}

func (c *fakeClient) TxStatus(_ context.Context, tx Hash) (TxStatus, error) {
	c.f.mu.Lock()
	defer c.f.mu.Unlock()
	return c.f.txs[tx], nil
}

func (c *fakeClient) Settle(_ context.Context, s Settlement) (Hash, error) {
	f := c.f
	return f.tx("Settle", func() error {
		seller, ok := f.sellers[s.SellerID]
		if !ok || seller.Status != SellerActive {
			return revert("SellerInactive")
		}
		if seller.ProfileID != s.ProfileID {
			return revert("ProfileMismatch")
		}
		if seller.ClaimsHash != s.ClaimsHash {
			return revert("ClaimsMismatch")
		}
		p := f.profiles[s.ProfileID]
		a := s.Authorization
		buyer := Address(a.From)
		keyID := protocol.DeriveKeyID(f.cfg.ChainID, f.cfg.Contract, s.SellerID, buyer, s.Key)
		nonce := protocol.DeriveNonce(f.cfg.ChainID, f.cfg.Contract, s.SellerID, s.ProfileID, s.ClaimsHash, buyer, s.Key, s.RequestHash)
		if Hash(a.Nonce) != nonce {
			return revert("NonceMismatch")
		}
		if Address(a.To) != f.cfg.Contract {
			return revert("AuthorizationMismatch")
		}
		if f.byKey[keyID] != (Hash{}) {
			return revert("KeyAlreadyUsed")
		}
		if f.purchases[nonce].Exists() {
			return revert("NonceAlreadyUsed")
		}
		if uint64(a.Value) > p.MaxPurchaseValue {
			return revert("ValueTooLarge")
		}
		if f.time <= uint64(a.ValidAfter) || f.time >= uint64(a.ValidBefore) {
			return revert("AuthorizationExpired")
		}
		digest := x402.ReceiveDigest(f.cfg.TokenName, f.cfg.TokenVersion, f.cfg.ChainID, f.cfg.Token, a)
		if ethkey.Verify(buyer, digest, s.Signature) != nil {
			return revert("TransferFailed")
		}
		if f.balances[buyer] < uint64(a.Value) {
			return revert("TransferFailed")
		}
		f.balances[buyer] -= uint64(a.Value)
		f.balances[f.cfg.Contract] += uint64(a.Value)
		b := f.block
		pur := Purchase{Nonce: nonce, KeyID: keyID, SellerID: s.SellerID, ProfileID: s.ProfileID, Buyer: buyer,
			Value: uint64(a.Value), RequestHash: s.RequestHash, ClaimsHash: s.ClaimsHash, Epoch: p.EpochAt(b),
			SettledBlock: b, ResponseDue: b + uint64(p.Deadlines.ResponseBlocks),
			ReleaseBlock: b + uint64(p.DeferBlocks), RetainUntil: b + uint64(p.RetentionBlocks), FinancialState: FinDeferred}
		pur.ClaimUntil = pur.ResponseDue + uint64(p.Deadlines.ClaimBlocks)
		f.purchases[nonce] = pur
		f.byKey[keyID] = nonce
		k := anchorKey{s.SellerID, pur.Epoch}
		f.settled[k] = append(f.settled[k], nonce)
		return nil
	})
}

func (c *fakeClient) Anchor(_ context.Context, sellerID uint32, epoch uint32, entries []x402.Entry, count uint32, pub Hash) (Hash, error) {
	f := c.f
	return f.tx("Anchor", func() error {
		s := f.sellers[sellerID]
		if s.Owner != c.from {
			return revert("Unauthorized")
		}
		p := f.profiles[s.ProfileID]
		k := anchorKey{sellerID, epoch}
		if f.anchors[k].State != EpochNone {
			return revert("InvalidTransition")
		}
		if f.block < p.AnchorBase(epoch) {
			return revert("AnchorTooEarly")
		}
		if f.block > p.AnchorDeadline(epoch) {
			return revert("AnchorWindowClosed")
		}
		if int(count) != len(f.settled[k]) || count == 0 || len(entries) != int(count) {
			return revert("CountMismatch")
		}
		if !x402.StrictlyAscending(entries) {
			return revert("EntriesNotAscending")
		}
		root := x402.EntriesRoot(x402.EntryHashes(entries))
		f.anchors[k] = Anchor{Root: root, PublicationHash: pub, AnchoredBlock: f.block,
			RandomBlock: p.AnchorDeadline(epoch) + 1 + uint64(p.BeaconDelayBlocks), ProfileID: s.ProfileID, Count: count, State: EpochAnchored}
		return nil
	})
}

func (f *Fake) checkReceipt(p Purchase, r protocol.Receipt, sig []byte) error {
	s := f.sellers[p.SellerID]
	if r.Version != 1 || r.SellerID != p.SellerID || r.ProfileID != p.ProfileID || r.Nonce != p.Nonce ||
		r.RequestHash != p.RequestHash || r.ClaimsHash != p.ClaimsHash || r.Epoch != p.Epoch {
		return revert("InvalidReceipt")
	}
	if ethkey.Verify(s.SigningKey, protocol.ReceiptDigest(f.cfg.ChainID, f.cfg.Contract, r), sig) != nil {
		return revert("InvalidSignature")
	}
	return nil
}

func (c *fakeClient) Dispute(_ context.Context, nonce Hash, kind uint8, r protocol.Receipt, sig []byte) (Hash, error) {
	f := c.f
	return f.tx("Dispute", func() error {
		p := f.purchases[nonce]
		if !p.Exists() {
			return revert("InvalidTransition")
		}
		if p.Buyer != c.from {
			return revert("Unauthorized")
		}
		if kind != TriggerNonDelivery {
			return revert("InvalidTransition") // WRONG_DELIVERY is not modelled
		}
		if len(sig) != 0 || r != (protocol.Receipt{}) {
			return revert("InvalidReceipt")
		}
		if f.block <= p.ResponseDue || f.block > p.ClaimUntil {
			return revert("ClaimWindowClosed")
		}
		if f.cases[nonce].State != CaseNone || p.FinancialState != FinDeferred {
			return revert("InvalidTransition")
		}
		prof := f.profiles[p.ProfileID]
		if f.balances[c.from] < prof.DisputeDeposit {
			return revert("TransferFailed")
		}
		f.balances[c.from] -= prof.DisputeDeposit
		p.FinancialState = FinHeld
		f.purchases[nonce] = p
		f.cases[nonce] = Case{Nonce: nonce, Requester: c.from, CaseOpenedBlock: f.block,
			ServeDue: f.block + uint64(prof.Deadlines.ServeBlocks), Trigger: kind, State: CaseServeWait, RequesterRole: RoleBuyer}
		return nil
	})
}

func (f *Fake) ownerCase(from Address, nonce Hash) (Case, Purchase, Profile, error) {
	p := f.purchases[nonce]
	s := f.sellers[p.SellerID]
	if !p.Exists() || s.Owner != from {
		return Case{}, p, Profile{}, revert("Unauthorized")
	}
	return f.cases[nonce], p, f.profiles[p.ProfileID], nil
}

func (c *fakeClient) Served(_ context.Context, nonce, bundle Hash) (Hash, error) {
	f := c.f
	return f.tx("Served", func() error {
		cs, _, prof, err := f.ownerCase(c.from, nonce)
		if err != nil {
			return err
		}
		if cs.State != CaseServeWait {
			return revert("InvalidTransition")
		}
		if f.block > cs.ServeDue {
			return revert("DeadlinePassed")
		}
		cs.State = CaseServeConfirm
		cs.BundleHash = bundle
		cs.ChallengeUntil = f.block + uint64(prof.Deadlines.ServeBlocks)
		f.cases[nonce] = cs
		return nil
	})
}

// deliver ends a buyer delivery claim. The fake keeps the deposit on a
// delivered claim and returns the purchase to DEFERRED.
func (f *Fake) deliver(nonce Hash) {
	cs := f.cases[nonce]
	cs.State = CaseDelivered
	f.cases[nonce] = cs
	p := f.purchases[nonce]
	p.FinancialState = FinDeferred
	f.purchases[nonce] = p
}

func (c *fakeClient) AcceptServe(_ context.Context, nonce Hash) (Hash, error) {
	f := c.f
	return f.tx("AcceptServe", func() error {
		cs := f.cases[nonce]
		if cs.Requester != c.from || cs.State != CaseServeConfirm {
			return revert("InvalidTransition")
		}
		if f.block > cs.ChallengeUntil {
			return revert("DeadlinePassed")
		}
		f.deliver(nonce)
		return nil
	})
}

func (c *fakeClient) Escalate(_ context.Context, nonce Hash) (Hash, error) {
	f := c.f
	return f.tx("Escalate", func() error {
		cs := f.cases[nonce]
		if cs.Requester != c.from || cs.State != CaseServeConfirm {
			return revert("InvalidTransition")
		}
		if f.block > cs.ChallengeUntil {
			return revert("DeadlinePassed")
		}
		prof := f.profiles[f.purchases[nonce].ProfileID]
		cs.State = CasePublishing
		cs.PublishDue = f.block + uint64(prof.Deadlines.ServeBlocks)
		f.cases[nonce] = cs
		return nil
	})
}

func (c *fakeClient) FinalizeServed(_ context.Context, nonce Hash) (Hash, error) {
	f := c.f
	return f.tx("FinalizeServed", func() error {
		cs := f.cases[nonce]
		if cs.State != CaseServeConfirm {
			return revert("InvalidTransition")
		}
		if f.block <= cs.ChallengeUntil {
			return revert("DeadlineNotReached")
		}
		f.deliver(nonce)
		return nil
	})
}

func (c *fakeClient) TimeoutServe(_ context.Context, nonce Hash) (Hash, error) {
	f := c.f
	return f.tx("TimeoutServe", func() error {
		cs := f.cases[nonce]
		switch {
		case cs.State == CaseServeWait && f.block > cs.ServeDue:
		case cs.State == CasePublishing && f.block > cs.PublishDue:
		default:
			return revert("InvalidTransition")
		}
		cs.State = CaseUnserved
		f.cases[nonce] = cs
		p := f.purchases[nonce]
		p.FinancialState = FinRefundable
		f.purchases[nonce] = p
		f.balances[cs.Requester] += f.profiles[p.ProfileID].DisputeDeposit
		return nil
	})
}

func (f *Fake) checkPublication(from Address, pub Publication, bodyHash Hash) error {
	cs, p, prof, err := f.ownerCase(from, pub.Nonce)
	if err != nil {
		return err
	}
	if cs.State != CasePublishing {
		return revert("InvalidTransition")
	}
	if f.block > cs.PublishDue {
		return revert("DeadlinePassed")
	}
	if pub.Request.Size() > int(prof.MaxRequestBytes) {
		return revert("InvalidPublication")
	}
	reqHash := pub.Request.Hash(prof.CanonID)
	nonce := protocol.DeriveNonce(f.cfg.ChainID, f.cfg.Contract, p.SellerID, p.ProfileID, p.ClaimsHash, p.Buyer, pub.Key, reqHash)
	if reqHash != p.RequestHash || nonce != p.Nonce {
		return revert("InvalidPublication")
	}
	if err = f.checkReceipt(p, pub.Receipt, pub.Signature); err != nil {
		return err
	}
	if bodyHash != pub.Receipt.ResponseHash {
		return revert("InvalidPublication")
	}
	return nil
}

func (c *fakeClient) Publish(_ context.Context, pub Publication) (Hash, error) {
	f := c.f
	return f.tx("Publish", func() error {
		if len(pub.Body) > int(f.profiles[f.purchases[pub.Nonce].ProfileID].MaxResponseBytes) {
			return revert("ResponseTooLarge")
		}
		if err := f.checkPublication(c.from, pub, protocol.ResponseHash(pub.Body)); err != nil {
			return err
		}
		f.pubs[pub.Nonce] = &fakePublication{Publication: pub}
		f.deliver(pub.Nonce)
		return nil
	})
}

func (c *fakeClient) BeginPublication(_ context.Context, pub Publication, total uint32, count uint16) (Hash, error) {
	f := c.f
	return f.tx("BeginPublication", func() error {
		want := (int(total) + protocol.ResponseChunkBytes - 1) / protocol.ResponseChunkBytes
		if want == 0 {
			want = 1
		}
		if int(count) != want || total > f.profiles[f.purchases[pub.Nonce].ProfileID].MaxResponseBytes {
			return revert("InvalidPublication")
		}
		if err := f.checkPublication(c.from, pub, pub.Receipt.ResponseHash); err != nil {
			return err
		}
		if f.pubs[pub.Nonce] != nil {
			return revert("InvalidTransition")
		}
		f.pubs[pub.Nonce] = &fakePublication{Publication: pub, totalBytes: total, chunks: make([][]byte, count), chunkSet: make([]bool, count)}
		return nil
	})
}

func (c *fakeClient) PublishChunk(_ context.Context, nonce Hash, index uint16, chunk []byte) (Hash, error) {
	f := c.f
	return f.tx("PublishChunk", func() error {
		fp := f.pubs[nonce]
		cs := f.cases[nonce]
		if fp == nil || cs.State != CasePublishing || f.sellers[f.purchases[nonce].SellerID].Owner != c.from {
			return revert("InvalidTransition")
		}
		if f.block > cs.PublishDue {
			return revert("DeadlinePassed")
		}
		if int(index) >= len(fp.chunks) || fp.chunkSet[index] {
			return revert("InvalidPublication")
		}
		last := int(index) == len(fp.chunks)-1
		want := protocol.ResponseChunkBytes
		if last {
			want = int(fp.totalBytes) - protocol.ResponseChunkBytes*(len(fp.chunks)-1)
		}
		if len(chunk) != want {
			return revert("InvalidPublication")
		}
		fp.chunks[index] = append([]byte(nil), chunk...)
		fp.chunkSet[index] = true
		cs.PublishedChunks++
		f.cases[nonce] = cs
		return nil
	})
}

func (c *fakeClient) FinalizePublication(_ context.Context, nonce Hash) (Hash, error) {
	f := c.f
	return f.tx("FinalizePublication", func() error {
		fp := f.pubs[nonce]
		if fp == nil || f.cases[nonce].State != CasePublishing {
			return revert("InvalidTransition")
		}
		var body []byte
		for i, ok := range fp.chunkSet {
			if !ok {
				return revert("InvalidPublication")
			}
			body = append(body, fp.chunks[i]...)
		}
		if protocol.ResponseHash(body) != fp.Receipt.ResponseHash {
			return revert("InvalidPublication")
		}
		fp.Body = body
		f.deliver(nonce)
		return nil
	})
}

func (c *fakeClient) ClaimRefund(_ context.Context, nonce Hash) (Hash, error) {
	f := c.f
	return f.tx("ClaimRefund", func() error {
		p := f.purchases[nonce]
		if p.FinancialState != FinRefundable {
			return revert("InvalidTransition")
		}
		p.FinancialState = FinRefunded
		f.purchases[nonce] = p
		f.balances[f.cfg.Contract] -= p.Value
		f.balances[p.Buyer] += p.Value
		return nil
	})
}

func (c *fakeClient) ClaimRefundWithReceipt(_ context.Context, nonce Hash, r protocol.Receipt, sig []byte, proof protocol.ReceiptProof) (Hash, error) {
	f := c.f
	return f.tx("ClaimRefundWithReceipt", func() error {
		p := f.purchases[nonce]
		if !p.Exists() {
			return revert("InvalidTransition")
		}
		b := f.bonds[f.sellers[p.SellerID].BondID]
		if b.FreezeState != FreezeClaimOpen {
			return revert("ClaimWindowNotOpen")
		}
		if f.block > b.ClaimUntilBlock {
			return revert("ClaimWindowClosed")
		}
		if p.SettledBlock > b.FreezeBlock {
			return revert("ReceiptOutOfWindow")
		}
		if p.FinancialState == FinRefunded {
			return revert("AlreadyClaimed")
		}
		if p.FinancialState != FinDeferred && p.FinancialState != FinReleasable {
			return revert("InvalidTransition")
		}
		if err := f.checkReceipt(p, r, sig); err != nil {
			return err
		}
		a := f.anchors[anchorKey{p.SellerID, p.Epoch}]
		if a.State == EpochAnchored || a.State == EpochSealed {
			leaf := protocol.ReceiptDigest(f.cfg.ChainID, f.cfg.Contract, r)
			if !protocol.VerifyReceiptProof(a.Root, protocol.ReceiptEntry{Nonce: nonce, ReceiptLeaf: leaf}, proof) {
				return revert("InvalidProof")
			}
		}
		p.FinancialState = FinRefunded
		f.purchases[nonce] = p
		f.balances[f.cfg.Contract] -= p.Value
		f.balances[p.Buyer] += p.Value
		return nil
	})
}

func (c *fakeClient) ClaimEpochFailure(_ context.Context, nonce Hash) (Hash, error) {
	f := c.f
	return f.tx("ClaimEpochFailure", func() error {
		p := f.purchases[nonce]
		if !p.Exists() {
			return revert("InvalidTransition")
		}
		k := anchorKey{p.SellerID, p.Epoch}
		a := f.anchors[k]
		prof := f.profiles[p.ProfileID]
		if a.State == EpochNone && f.block > prof.AnchorDeadline(p.Epoch) {
			a.State = EpochFailed
			f.anchors[k] = a
		}
		if a.State != EpochFailed {
			return revert("InvalidTransition")
		}
		if p.FinancialState != FinDeferred && p.FinancialState != FinHeld {
			return revert("AlreadyFinalized")
		}
		p.FinancialState = FinRefundable
		f.purchases[nonce] = p
		return nil
	})
}

var _ Client = (*fakeClient)(nil)

// String helps test failure messages.
func (s TxStatus) String() string {
	return [...]string{"unknown", "pending", "succeeded", "failed"}[s]
}
