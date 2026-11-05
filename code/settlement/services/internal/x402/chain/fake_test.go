package chain

import (
	"context"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/ethkey"
)

func setup(t *testing.T) (*Fake, *ethkey.PrivateKey, Address, Settlement) {
	buyer, _ := ethkey.ParsePrivateKey("0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
	f := NewFake(FakeConfig{ChainID: 31337, Contract: Address{0x11}, Token: Address{0x22}, TokenName: "MockUSDC", TokenVersion: "2"})
	owner := Address{0x33}
	f.AddProfile(Profile{ProfileID: 3, Active: true, EpochOrigin: 1, EpochBlocks: 100, MaxPurchaseValue: 1_000_000,
		DisputeDeposit: 50, MaxRequestBytes: 1 << 16, MaxResponseBytes: 1 << 16, RetentionBlocks: 300, DeferBlocks: 400,
		Deadlines: DeadlineConfig{AnchorBlocks: 20, ResponseBlocks: 10, ClaimBlocks: 50, ServeBlocks: 10}})
	f.AddSeller(Seller{SellerID: 7, ProfileID: 3, Owner: owner, SigningKey: Address{0x44}, ClaimsHash: Hash{0x55}, BondID: 1, Status: SellerActive})
	f.Mint(buyer.Address(), 100_000)
	key := protocol.Bytes16{1}
	req := Hash{0x66}
	nonce := protocol.DeriveNonce(31337, Address{0x11}, 7, 3, Hash{0x55}, buyer.Address(), key, req)
	a := x402.Authorization{From: x402.Addr(buyer.Address()), To: x402.Addr{0x11}, Value: 10_000,
		ValidAfter: x402.U64(f.Time() - 10), ValidBefore: x402.U64(f.Time() + 60), Nonce: x402.H32(nonce)}
	sig := buyer.Sign(x402.ReceiveDigest("MockUSDC", "2", 31337, Address{0x22}, a))
	return f, buyer, owner, Settlement{SellerID: 7, ProfileID: 3, ClaimsHash: Hash{0x55}, Key: key, RequestHash: req, Authorization: a, Signature: sig}
}

func TestFakeSettleRulesAndIdempotency(t *testing.T) {
	ctx := context.Background()
	f, buyer, owner, s := setup(t)
	fac := f.As(Address{0x77})
	bad := s
	bad.ClaimsHash = Hash{1}
	if _, err := fac.Settle(ctx, bad); !IsRevert(err, "ClaimsMismatch") {
		t.Fatal(err)
	}
	bad = s
	bad.Signature = append([]byte(nil), s.Signature...)
	bad.Signature[5] ^= 1
	if _, err := fac.Settle(ctx, bad); !IsRevert(err, "TransferFailed") {
		t.Fatal(err)
	}
	f.Inject("Settle", LoseAfter)
	if _, err := fac.Settle(ctx, s); err != ErrTransport {
		t.Fatal(err)
	}
	if _, err := fac.Settle(ctx, s); !IsRevert(err, "KeyAlreadyUsed") {
		t.Fatalf("retry after lost response: %v", err)
	}
	p, _ := fac.GetPurchase(ctx, Hash(s.Authorization.Nonce))
	if !p.Exists() || p.Buyer != buyer.Address() || p.Epoch != 0 || f.Balance(buyer.Address()) != 90_000 {
		t.Fatalf("purchase %+v", p)
	}
	// anchor window for epoch 0 is [epochEnd(1), epochEnd(1)+20] = [200, 220]
	so := f.As(owner)
	one := []x402.Entry{{Nonce: x402.H32{9}, ReceiptLeaf: x402.H32{1}}}
	if _, err := so.Anchor(ctx, 7, 0, one, 1, Hash{}); !IsRevert(err, "AnchorTooEarly") {
		t.Fatal(err)
	}
	f.MineTo(200)
	if _, err := fac.Anchor(ctx, 7, 0, one, 1, Hash{}); !IsRevert(err, "Unauthorized") {
		t.Fatal(err)
	}
	if _, err := so.Anchor(ctx, 7, 0, one, 2, Hash{}); !IsRevert(err, "CountMismatch") {
		t.Fatal(err)
	}
	if _, err := so.Anchor(ctx, 7, 0, one, 1, Hash{}); err != nil {
		t.Fatal(err)
	}
	if a, _ := so.GetAnchor(ctx, 7, 0); a.Root != x402.EntriesRoot(x402.EntryHashes(one)) {
		t.Fatalf("root %x", a.Root)
	}
}

func TestFakeNonDeliveryTimeoutRefund(t *testing.T) {
	ctx := context.Background()
	f, buyer, _, s := setup(t)
	f.As(Address{0x77}).Settle(ctx, s)
	b := f.As(buyer.Address())
	n := Hash(s.Authorization.Nonce)
	if _, err := b.Dispute(ctx, n, TriggerNonDelivery, protocol.Receipt{}, nil); !IsRevert(err, "ClaimWindowClosed") {
		t.Fatal(err)
	}
	f.Mine(11)
	if _, err := b.Dispute(ctx, n, TriggerNonDelivery, protocol.Receipt{}, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := b.TimeoutServe(ctx, n); !IsRevert(err, "InvalidTransition") {
		t.Fatal(err)
	}
	f.Mine(11)
	if _, err := b.TimeoutServe(ctx, n); err != nil {
		t.Fatal(err)
	}
	if _, err := b.ClaimRefund(ctx, n); err != nil {
		t.Fatal(err)
	}
	if f.Balance(buyer.Address()) != 100_000 {
		t.Fatalf("balance %d", f.Balance(buyer.Address()))
	}
}
