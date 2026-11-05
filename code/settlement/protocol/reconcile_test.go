package protocol

import "testing"

func TestReconcileUncertainSettlement(t *testing.T) {
	expected := ExpectedPurchase{
		Nonce: Bytes32{1}, KeyID: Bytes32{2}, SellerID: 7, ProfileID: 3,
		Buyer: Address{3}, Value: 10_000, RequestHash: Bytes32{4}, ClaimsHash: Bytes32{5},
	}
	recorded := RecordedPurchase(expected)
	if Reconcile(expected, &recorded, expected.Nonce) != ReconcileConfirmed {
		t.Fatal("matching retry was not confirmed")
	}
	conflict := recorded
	conflict.RequestHash = Bytes32{9}
	if Reconcile(expected, &conflict, expected.Nonce) != ReconcileConflict {
		t.Fatal("idempotency conflict was not detected")
	}
	if Reconcile(expected, nil, Bytes32{}) != ReconcileMissing {
		t.Fatal("missing settlement was not detected")
	}
}
