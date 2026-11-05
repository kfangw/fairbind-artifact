// Package chain is the narrow contract interface the services use. RPC talks
// to a node over JSON-RPC; Fake is an in-memory model of the subset of the
// FairBind contract rules the services depend on, for tests.
package chain

import (
	"context"
	"errors"
	"fmt"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
)

type (
	Address = protocol.Address
	Hash    = protocol.Bytes32
)

// Enum values from contract-interface-v1 section 2.
const (
	SellerActive uint8 = 1

	FreezeNone      uint8 = 0
	FreezeFrozen    uint8 = 1
	FreezeClaimOpen uint8 = 2

	FinNone            uint8 = 0
	FinDeferred        uint8 = 1
	FinHeld            uint8 = 2
	FinFrozenClaimable uint8 = 3
	FinRefundable      uint8 = 4
	FinRefunded        uint8 = 5
	FinReleasable      uint8 = 6
	FinReleased        uint8 = 7
	FinForfeited       uint8 = 8

	EpochNone     uint8 = 0
	EpochAnchored uint8 = 1
	EpochSealed   uint8 = 2
	EpochFailed   uint8 = 3

	TriggerNonDelivery   uint8 = 2
	TriggerWrongDelivery uint8 = 3

	CaseNone         uint8 = 0
	CaseServeWait    uint8 = 1
	CaseServeConfirm uint8 = 2
	CasePublishing   uint8 = 3
	CaseAssigning    uint8 = 4
	CaseJudging      uint8 = 5
	CaseDelivered    uint8 = 10
	CaseUnserved     uint8 = 11
	CaseInconclusive uint8 = 12
	CaseFinal        uint8 = 13

	RoleBuyer    uint8 = 1
	RoleVerifier uint8 = 2
)

// FinancialStateName maps a financial state to its enum name.
func FinancialStateName(s uint8) string {
	names := []string{"NONE", "DEFERRED", "HELD", "FROZEN_CLAIMABLE", "REFUNDABLE", "REFUNDED", "RELEASABLE", "RELEASED", "FORFEITED"}
	if int(s) < len(names) {
		return names[s]
	}
	return fmt.Sprintf("UNKNOWN_%d", s)
}

type DeadlineConfig struct {
	AnchorBlocks, SealBlocks, OpenBlocks, ResponseBlocks, ClaimBlocks, ServeBlocks, JudgeBlocks, EvidenceBlocks, AppealBlocks uint32
}

// Profile is the subset of ServiceProfileView the services read, with its
// deadline configuration resolved.
type Profile struct {
	ProfileID         uint32
	Active            bool
	Token             Address
	ClassID           uint16
	PredicateID       Hash
	CanonID           Hash
	EpochOrigin       uint64
	EpochBlocks       uint32
	DeferBlocks       uint32
	RetentionBlocks   uint32
	MaxRequestBytes   uint32
	MaxResponseBytes  uint32
	MaxPurchaseValue  uint64
	DisputeDeposit    uint64
	DeadlineConfigID  uint32
	BeaconDelayBlocks uint32
	FailureLimit      uint32
	SellerPenalty     uint64
	Deadlines         DeadlineConfig
}

// EpochAt returns the settlement epoch of block b.
func (p Profile) EpochAt(b uint64) uint32 {
	if b < p.EpochOrigin || p.EpochBlocks == 0 {
		return 0
	}
	return uint32((b - p.EpochOrigin) / uint64(p.EpochBlocks))
}

// EpochStart returns the first block of epoch e.
func (p Profile) EpochStart(e uint32) uint64 {
	return p.EpochOrigin + uint64(e)*uint64(p.EpochBlocks)
}

// AnchorBase is epochEnd(e + 1), the first block anchor is valid for e.
func (p Profile) AnchorBase(e uint32) uint64 { return p.EpochStart(e+2) - 1 }

// AnchorDeadline is the last block anchor is valid for e.
func (p Profile) AnchorDeadline(e uint32) uint64 {
	return p.AnchorBase(e) + uint64(p.Deadlines.AnchorBlocks)
}

type Seller struct {
	SellerID   uint32
	ProfileID  uint32
	Owner      Address
	SigningKey Address
	ClaimsHash Hash
	BondID     uint32
	Status     uint8
}

type Quote struct {
	SellerID         uint32
	ProfileID        uint32
	ClaimsHash       Hash
	Token            Address
	MaxPurchaseValue uint64
	Remaining        uint32
	QuotedAtBlock    uint64
	CurrentEpoch     uint32
	SellerStatus     uint8
	BondID           uint32
}

type Purchase struct {
	Nonce          Hash
	KeyID          Hash
	SellerID       uint32
	ProfileID      uint32
	Buyer          Address
	Value          uint64
	RequestHash    Hash
	ClaimsHash     Hash
	Epoch          uint32
	SettledBlock   uint64
	ResponseDue    uint64
	ClaimUntil     uint64
	ReleaseBlock   uint64
	RetainUntil    uint64
	FinancialState uint8
}

// Exists reports whether the view names a recorded purchase.
func (p Purchase) Exists() bool { return p.Nonce != (Hash{}) }

// Expected converts a recorded purchase to the reconciliation form.
func (p Purchase) Expected() protocol.ExpectedPurchase {
	return protocol.ExpectedPurchase{Nonce: p.Nonce, KeyID: p.KeyID, SellerID: p.SellerID, ProfileID: p.ProfileID,
		Buyer: p.Buyer, Value: p.Value, RequestHash: p.RequestHash, ClaimsHash: p.ClaimsHash}
}

type Case struct {
	Nonce              Hash
	Requester          Address
	BundleHash         Hash
	CaseOpenedBlock    uint64
	ServeDue           uint64
	ChallengeUntil     uint64
	PublishDue         uint64
	AssignedVerifierID uint32
	PublishedChunks    uint16
	Trigger            uint8
	State              uint8
	RequesterRole      uint8
}

type Anchor struct {
	Root            Hash
	PublicationHash Hash
	AnchoredBlock   uint64
	RandomBlock     uint64
	ProfileID       uint32
	Count           uint32
	State           uint8
}

type Bond struct {
	BondID          uint32
	FreezeBlock     uint64
	ClaimUntilBlock uint64
	FreezeState     uint8
	Status          uint8
}

type Verifier struct {
	VerifierID uint32
	SigningKey Address
}

// Settlement holds the settle arguments.
type Settlement struct {
	SellerID      uint32
	ProfileID     uint32
	ClaimsHash    Hash
	Key           protocol.Bytes16
	RequestHash   Hash
	Authorization x402.Authorization
	Signature     []byte
}

// Publication holds the publish arguments. Body is empty for
// BeginPublication.
type Publication struct {
	Nonce     Hash
	Key       protocol.Bytes16
	Request   x402.CanonicalRequest
	Body      []byte
	Receipt   protocol.Receipt
	Signature []byte
}

type TxStatus uint8

const (
	TxUnknown TxStatus = iota
	TxPending
	TxSucceeded
	TxFailed
)

// Reader is the read side. Missing records return zero views, as the
// contract views do.
type Reader interface {
	ChainID() uint64
	Contract() Address
	BlockNumber(ctx context.Context) (uint64, error)
	GetProfile(ctx context.Context, profileID uint32) (Profile, error)
	GetSeller(ctx context.Context, sellerID uint32) (Seller, error)
	QuoteSeller(ctx context.Context, sellerID uint32) (Quote, error)
	GetPurchase(ctx context.Context, nonce Hash) (Purchase, error)
	PurchaseByKey(ctx context.Context, keyID Hash) (Hash, error)
	PurchaseState(ctx context.Context, nonce Hash) (uint8, error)
	GetCase(ctx context.Context, nonce Hash) (Case, error)
	GetAnchor(ctx context.Context, sellerID uint32, epoch uint32) (Anchor, error)
	GetBond(ctx context.Context, bondID uint32) (Bond, error)
	GetVerifier(ctx context.Context, verifierID uint32) (Verifier, error)
	// SettledNonces lists the ledger nonces the contract recorded for a
	// seller and epoch (from Settled events).
	SettledNonces(ctx context.Context, sellerID uint32, epoch uint32) ([]Hash, error)
	// Publication returns on-chain published response data, if any.
	Publication(ctx context.Context, nonce Hash) (*Publication, error)
	TxStatus(ctx context.Context, tx Hash) (TxStatus, error)
}

// Writer submits transactions from one account. A returned hash with a nil
// error means the transaction succeeded. A *RevertError means it reverted.
// Any other error leaves the outcome uncertain; callers reconcile through
// views before retrying.
type Writer interface {
	From() Address
	Settle(ctx context.Context, s Settlement) (Hash, error)
	// Anchor sends the (nonce, receiptLeaf) entries of the epoch tree in
	// strictly ascending nonce order; the contract checks the order and
	// computes the root from them (ADR 0026).
	Anchor(ctx context.Context, sellerID uint32, epoch uint32, entries []x402.Entry, count uint32, publicationHash Hash) (Hash, error)
	Dispute(ctx context.Context, nonce Hash, kind uint8, receipt protocol.Receipt, signature []byte) (Hash, error)
	Served(ctx context.Context, nonce, bundleHash Hash) (Hash, error)
	AcceptServe(ctx context.Context, nonce Hash) (Hash, error)
	Escalate(ctx context.Context, nonce Hash) (Hash, error)
	FinalizeServed(ctx context.Context, nonce Hash) (Hash, error)
	TimeoutServe(ctx context.Context, nonce Hash) (Hash, error)
	Publish(ctx context.Context, p Publication) (Hash, error)
	BeginPublication(ctx context.Context, p Publication, totalBytes uint32, chunkCount uint16) (Hash, error)
	PublishChunk(ctx context.Context, nonce Hash, index uint16, chunk []byte) (Hash, error)
	FinalizePublication(ctx context.Context, nonce Hash) (Hash, error)
	ClaimRefund(ctx context.Context, nonce Hash) (Hash, error)
	ClaimRefundWithReceipt(ctx context.Context, nonce Hash, receipt protocol.Receipt, signature []byte, proof protocol.ReceiptProof) (Hash, error)
	ClaimEpochFailure(ctx context.Context, nonce Hash) (Hash, error)
}

type Client interface {
	Reader
	Writer
}

// RevertError reports a reverted call with the contract custom error name
// when it is known.
type RevertError struct {
	Name string
	Tx   Hash
}

func (e *RevertError) Error() string { return "execution reverted: " + e.Name }

// IsRevert reports whether err is a revert, optionally with a given name.
func IsRevert(err error, name string) bool {
	var r *RevertError
	if !errors.As(err, &r) {
		return false
	}
	return name == "" || r.Name == name
}
