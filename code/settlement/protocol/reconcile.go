package protocol

type ReconcileStatus uint8

const (
	ReconcileMissing ReconcileStatus = iota
	ReconcileConfirmed
	ReconcileConflict
)

type ExpectedPurchase struct {
	Nonce       Bytes32
	KeyID       Bytes32
	SellerID    uint32
	ProfileID   uint32
	Buyer       Address
	Value       uint64
	RequestHash Bytes32
	ClaimsHash  Bytes32
}

type RecordedPurchase = ExpectedPurchase

func Reconcile(expected ExpectedPurchase, byNonce *RecordedPurchase, nonceByKey Bytes32) ReconcileStatus {
	if byNonce == nil && nonceByKey == (Bytes32{}) {
		return ReconcileMissing
	}
	if byNonce == nil || nonceByKey != expected.Nonce || *byNonce != expected {
		return ReconcileConflict
	}
	return ReconcileConfirmed
}
