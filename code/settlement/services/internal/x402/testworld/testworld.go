// Package testworld builds a fake chain with one profile, seller, bond and
// funded buyer for service tests. Keys are public test fixtures.
package testworld

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"

	"example.org/fairbind/adapters/httpcanon"
	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/ethkey"
)

const (
	ChainID   = 31337
	SellerID  = 7
	ProfileID = 3
	BondID    = 1
	Price     = 10_000
)

var (
	Contract    = chain.Address{0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11}
	Token       = chain.Address{0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x22}
	SellerOwner = chain.Address{0x0a}
	Facilitator = chain.Address{0x0f}
	Claims      = []byte("test claims")
	ClaimsHash  = protocol.Keccak256(Claims)
	ProfileHash = protocol.Keccak256([]byte("test profile"))
	PredicateID = protocol.Keccak256([]byte("test predicate"))
)

type World struct {
	Fake      *chain.Fake
	Profile   chain.Profile
	SellerKey *ethkey.PrivateKey
	BuyerKey  *ethkey.PrivateKey
}

func mustKey(s string) *ethkey.PrivateKey {
	k, err := ethkey.ParsePrivateKey(s)
	if err != nil {
		panic(err)
	}
	return k
}

// New returns a world at block 1. Epochs are 100 blocks starting at block 1;
// the anchor window of epoch e is [100e+200, 100e+220].
func New() *World {
	f := chain.NewFake(chain.FakeConfig{ChainID: ChainID, Contract: Contract, Token: Token, TokenName: "MockUSDC", TokenVersion: "2"})
	p := chain.Profile{ProfileID: ProfileID, Active: true, Token: Token, ClassID: 1, PredicateID: PredicateID, CanonID: httpcanon.ID,
		EpochOrigin: 1, EpochBlocks: 100, DeferBlocks: 400, RetentionBlocks: 300, MaxRequestBytes: 65536, MaxResponseBytes: 65536,
		MaxPurchaseValue: 1_000_000, DisputeDeposit: 500, DeadlineConfigID: 1,
		Deadlines: chain.DeadlineConfig{AnchorBlocks: 20, SealBlocks: 10, OpenBlocks: 10, ResponseBlocks: 10, ClaimBlocks: 50, ServeBlocks: 10}}
	w := &World{Fake: f, Profile: p,
		SellerKey: mustKey("0x0000000000000000000000000000000000000000000000000000000000000001"),
		BuyerKey:  mustKey("0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")}
	f.AddProfile(p)
	f.AddBond(chain.Bond{BondID: BondID, Status: 1})
	f.AddSeller(chain.Seller{SellerID: SellerID, ProfileID: ProfileID, Owner: SellerOwner, SigningKey: w.SellerKey.Address(),
		ClaimsHash: ClaimsHash, BondID: BondID, Status: chain.SellerActive})
	f.Mint(w.BuyerKey.Address(), 1_000_000)
	return w
}

// RepoRoot returns the repository root directory.
func RepoRoot() string {
	_, file, _, _ := runtime.Caller(0)
	return filepath.Join(filepath.Dir(file), "..", "..", "..", "..")
}

// Schema returns an inline schema from schemas/.
func Schema(name string) json.RawMessage {
	raw, err := os.ReadFile(filepath.Join(RepoRoot(), "schemas", name))
	if err != nil {
		panic(err)
	}
	s, err := x402.InlineSchema(raw)
	if err != nil {
		panic(err)
	}
	return s
}

// Offer returns the server-authored extension info for the world's seller.
func (w *World) Offer() x402.OfferInfo {
	return x402.OfferInfo{Version: 1, Contract: x402.Addr(Contract), SellerID: SellerID, ProfileID: ProfileID, BondID: BondID,
		ServiceClass: "data-api", PredicateID: x402.H32(PredicateID), CanonID: x402.H32(w.Profile.CanonID),
		ClaimsHash: x402.H32(ClaimsHash), ProfileHash: x402.H32(ProfileHash), CanonicalHeaders: []string{"accept"},
		QuotedAtBlock: 1, Remaining: 20, ResponseBlocks: uint64(w.Profile.Deadlines.ResponseBlocks),
		ClaimBlocks: uint64(w.Profile.Deadlines.ClaimBlocks), MaxRequestBytes: uint64(w.Profile.MaxRequestBytes),
		MaxResponseBytes: uint64(w.Profile.MaxResponseBytes), RetentionBlocks: uint64(w.Profile.RetentionBlocks)}
}

// Accept returns the accepts entry for the world's seller.
func (w *World) Accept() x402.Accept {
	return x402.Accept{Scheme: x402.Scheme, Network: "eip155:31337", Amount: "10000", Asset: x402.Addr(Token),
		PayTo: x402.Addr(Contract), MaxTimeoutSeconds: 60,
		Extra: x402.AcceptExtra{AssetTransferMethod: x402.AssetTransferMethod, PaymentFlow: x402.PaymentFlow, Name: "MockUSDC", Version: "2"}}
}

// SettleRequest builds a signed facilitator request for a buyer key and
// request hash, valid for 60 seconds of fake time.
func (w *World) SettleRequest(buyer *ethkey.PrivateKey, key protocol.Bytes16, requestHash protocol.Bytes32) x402.SettleRequest {
	info := w.Offer()
	k, rh := x402.H16(key), x402.H32(requestHash)
	info.IdempotencyKey, info.RequestHash = &k, &rh
	nonce := protocol.DeriveNonce(ChainID, Contract, SellerID, ProfileID, ClaimsHash, buyer.Address(), key, requestHash)
	now := w.Fake.Time()
	auth := x402.Authorization{From: x402.Addr(buyer.Address()), To: x402.Addr(Contract), Value: Price,
		ValidAfter: x402.U64(now - 10), ValidBefore: x402.U64(now + 60), Nonce: x402.H32(nonce)}
	sig := buyer.Sign(x402.ReceiveDigest("MockUSDC", "2", ChainID, Token, auth))
	pp := x402.PaymentPayload{X402Version: 2, Resource: x402.Resource{URL: "http://seller.test/v1/quote", Description: "quote", MimeType: "application/json"},
		Accepted: w.Accept(), Payload: x402.ExactPayload{Signature: x402.Hex(sig), Authorization: auth},
		Extensions: map[string]x402.OfferExtension{x402.ExtensionKey: {Info: info, Schema: Schema("fairbind-extension-v1.schema.json")}}}
	return x402.SettleRequest{X402Version: 2, PaymentPayload: pp, PaymentRequirements: w.Accept()}
}
