package x402

import (
	"encoding/json"
	"os"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402/ethkey"
)

const root = "../../../"

func readJSON(t *testing.T, path string, v any) {
	t.Helper()
	raw, err := os.ReadFile(root + path)
	if err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(raw, v); err != nil {
		t.Fatal(err)
	}
}

type cryptoVectors struct {
	Fixtures struct {
		ChainID         string
		ContractAddress string
	}
	PaymentAuthorization struct {
		TokenName, TokenVersion, TokenAddress, Digest string
	}
	Receipt            struct{ Digest string }
	ServeAuthorization struct {
		Message struct {
			Nonce                       string
			Role                        uint8
			CaseOpenedBlock, ValidUntil string
		}
		Digest, Signature string
	}
	ServeBundle struct{ BundleHash string }
}

func must32(t *testing.T, s string) protocol.Bytes32 {
	h, err := ParseH32(s)
	if err != nil {
		t.Fatal(err)
	}
	return protocol.Bytes32(h)
}

func TestHeaderVectorsDecodeStrictly(t *testing.T) {
	var headers struct {
		RequestHeaders map[string]string
		Encoded        map[string]struct{ Value string }
	}
	readJSON(t, "test-vectors/x402-v2/headers.json", &headers)
	var pr PaymentRequired
	if err := DecodeHeader(headers.Encoded[HeaderPaymentRequired].Value, &pr); err != nil {
		t.Fatal(err)
	}
	var pp PaymentPayload
	if err := DecodeHeader(headers.Encoded[HeaderPaymentSignature].Value, &pp); err != nil {
		t.Fatal(err)
	}
	var sr SettlementResponse
	if err := DecodeHeader(headers.Encoded[HeaderPaymentResponse].Value, &sr); err != nil {
		t.Fatal(err)
	}
	var rc Receipt
	if err := DecodeHeader(headers.Encoded[HeaderReceipt].Value, &rc); err != nil {
		t.Fatal(err)
	}
	offer := pr.Extensions[ExtensionKey]
	paid := pp.Extensions[ExtensionKey]
	if !equalOffer(offer.Info, paid.Info.ServerAuthored()) || !SameJSON(offer.Schema, paid.Schema) {
		t.Fatal("paid extension does not echo the offer")
	}
	key, err := DecodeKey(headers.RequestHeaders[HeaderKey])
	if err != nil || key != *paid.Info.IdempotencyKey {
		t.Fatalf("key header %v", err)
	}
	// Re-encoding and decoding is lossless.
	enc, _ := EncodeHeader(pp)
	var again PaymentPayload
	if err := DecodeHeader(enc, &again); err != nil {
		t.Fatal(err)
	}
	if EncodeKey(key) != headers.RequestHeaders[HeaderKey] {
		t.Fatal("key encoding")
	}
	var v cryptoVectors
	readJSON(t, "test-vectors/cryptography-v1.json", &v)
	tok, _ := ParseAddr(v.PaymentAuthorization.TokenAddress)
	d := ReceiveDigest(pp.Accepted.Extra.Name, pp.Accepted.Extra.Version, 31337, protocol.Address(tok), pp.Payload.Authorization)
	if d != must32(t, v.PaymentAuthorization.Digest) {
		t.Fatal("EIP-3009 digest")
	}
	sig, _ := ParseHex(pp.Payload.Signature)
	if err := ethkey.Verify(protocol.Address(pp.Payload.Authorization.From), d, sig); err != nil {
		t.Fatal(err)
	}
	// ADR 0016: the same signature is not a TransferWithAuthorization, so a
	// direct token transfer cannot spend it outside settle.
	a := pp.Payload.Authorization
	dom := domainSeparator(pp.Accepted.Extra.Name, pp.Accepted.Extra.Version, 31337, protocol.Address(tok))
	transferType := protocol.Keccak256([]byte("TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"))
	ts := protocol.Keccak256(transferType[:], addrWord(protocol.Address(a.From)), addrWord(protocol.Address(a.To)),
		word(uint64(a.Value)), word(uint64(a.ValidAfter)), word(uint64(a.ValidBefore)), a.Nonce[:])
	td := protocol.Keccak256([]byte{0x19, 0x01}, dom[:], ts[:])
	if td == d || ethkey.Verify(protocol.Address(a.From), td, sig) == nil {
		t.Fatal("payment signature also verifies as TransferWithAuthorization")
	}
	if rc.Digest() != must32(t, v.Receipt.Digest) {
		t.Fatal("receipt digest")
	}
	nonce := protocol.DeriveNonce(31337, protocol.Address(paid.Info.Contract), paid.Info.SellerID, paid.Info.ProfileID,
		protocol.Bytes32(paid.Info.ClaimsHash), protocol.Address(pp.Payload.Authorization.From), protocol.Bytes16(key), protocol.Bytes32(*paid.Info.RequestHash))
	if H32(nonce) != pp.Payload.Authorization.Nonce || H32(nonce) != sr.Extensions[ExtensionKey].Info.Purchase {
		t.Fatal("nonce")
	}
}

func equalOffer(a, b OfferInfo) bool {
	x, _ := json.Marshal(a)
	y, _ := json.Marshal(b)
	return string(x) == string(y)
}

func TestServeAuthorizationAndBundleVectors(t *testing.T) {
	var v cryptoVectors
	readJSON(t, "test-vectors/cryptography-v1.json", &v)
	contract, _ := ParseAddr(v.Fixtures.ContractAddress)
	m := v.ServeAuthorization.Message
	var opened, until U64
	json.Unmarshal([]byte(`"`+m.CaseOpenedBlock+`"`), &opened)
	json.Unmarshal([]byte(`"`+m.ValidUntil+`"`), &until)
	d := ServeAuthDigest(31337, protocol.Address(contract), must32(t, m.Nonce), m.Role, uint64(opened), uint64(until))
	if d != must32(t, v.ServeAuthorization.Digest) {
		t.Fatal("serve authorization digest")
	}
	var rc Receipt
	readJSON(t, "test-vectors/x402-v2/fairbind-receipt.json", &rc)
	body := []byte("{\"price\":\"123.45\",\"symbol\":\"ETH-USD\"}\n")
	if protocol.ResponseHash(body) != protocol.Bytes32(rc.ResponseHash) {
		t.Fatal("response hash")
	}
	key, _ := ParseH16("0x00112233445566778899aabbccddeeff")
	b := ServeBundle{Nonce: rc.Nonce, IdempotencyKey: key, ResponseBody: body, Receipt: rc}
	if b.ComputeHash() != must32(t, v.ServeBundle.BundleHash) {
		t.Fatal("bundle hash")
	}
}

func TestTreeMatchesMerkleVectors(t *testing.T) {
	var m struct {
		Root        string
		Publication struct {
			Manifest        Manifest
			PublicationHash string
		}
		Entries []struct {
			Index              uint32
			Nonce, ReceiptLeaf string
			Siblings           []string
		}
	}
	readJSON(t, "test-vectors/merkle-v1.json", &m)
	var entries []Entry
	for i := len(m.Entries) - 1; i >= 0; i-- {
		e := m.Entries[i]
		entries = append(entries, Entry{H32(must32(t, e.Nonce)), H32(must32(t, e.ReceiptLeaf))})
	}
	tree, err := BuildTree(entries)
	if err != nil {
		t.Fatal(err)
	}
	if tree.Root() != must32(t, m.Root) {
		t.Fatal("root")
	}
	for _, e := range m.Entries {
		entry, proof, ok := tree.Prove(must32(t, e.Nonce))
		if !ok || proof.Index != e.Index || len(proof.Siblings) != len(e.Siblings) {
			t.Fatalf("proof for %s", e.Nonce)
		}
		for i, s := range e.Siblings {
			if proof.Siblings[i] != H32(must32(t, s)) {
				t.Fatalf("sibling %d of %d", i, e.Index)
			}
		}
		if !protocol.VerifyReceiptProof(tree.Root(), protocol.ReceiptEntry{Nonce: protocol.Bytes32(entry.Nonce), ReceiptLeaf: protocol.Bytes32(entry.ReceiptLeaf)}, proof.Typed()) {
			t.Fatal("proof does not verify")
		}
	}
	if _, _, ok := tree.Prove(protocol.Bytes32{1}); ok {
		t.Fatal("proof for absent nonce")
	}
	h, _, err := PublicationHash(m.Publication.Manifest)
	if err != nil || h != must32(t, m.Publication.PublicationHash) {
		t.Fatalf("publication hash %x", h)
	}
	if _, err := BuildTree(append(entries, entries[0])); err == nil {
		t.Fatal("duplicate nonce accepted")
	}
}

func TestTreeProofsForManySizes(t *testing.T) {
	for n := 1; n <= 9; n++ {
		var entries []Entry
		for i := 0; i < n; i++ {
			entries = append(entries, Entry{H32(protocol.Keccak256([]byte{byte(i)})), H32(protocol.Keccak256([]byte{byte(i), 1}))})
		}
		tree, _ := BuildTree(entries)
		var pe []protocol.ReceiptEntry
		for _, e := range entries {
			pe = append(pe, protocol.ReceiptEntry{Nonce: protocol.Bytes32(e.Nonce), ReceiptLeaf: protocol.Bytes32(e.ReceiptLeaf)})
		}
		want, _ := protocol.ReceiptRoot(pe)
		if tree.Root() != want {
			t.Fatalf("n=%d root", n)
		}
		for _, e := range entries {
			_, p, _ := tree.Prove(protocol.Bytes32(e.Nonce))
			if !protocol.VerifyReceiptProof(want, protocol.ReceiptEntry{Nonce: protocol.Bytes32(e.Nonce), ReceiptLeaf: protocol.Bytes32(e.ReceiptLeaf)}, p.Typed()) {
				t.Fatalf("n=%d proof", n)
			}
		}
	}
}

func TestDecodeKeyRejectsBadInput(t *testing.T) {
	for _, s := range []string{"", "ABEiM0RVZneImaq7zN3u_w=", "ABEiM0RVZneImaq7zN3u/w", "ABEiM0RVZneImaq7zN3u_x"} {
		if _, err := DecodeKey(s); err == nil {
			t.Fatalf("accepted %q", s)
		}
	}
}

// The anchor carries the (nonce, receiptLeaf) entries and the contract
// computes the root from them (ADR 0026); that root must equal the tree root
// for every list length, and BuildTree's order must be one the contract
// accepts.
func TestEntriesRootMatchesTreeRoot(t *testing.T) {
	for n := 1; n <= 9; n++ {
		entries := make([]Entry, n)
		for i := range entries {
			entries[i] = Entry{Nonce: H32(protocol.Keccak256([]byte{byte(i), 1})), ReceiptLeaf: H32(protocol.Keccak256([]byte{byte(i), 2}))}
		}
		tree, err := BuildTree(entries)
		if err != nil {
			t.Fatal(err)
		}
		if !StrictlyAscending(tree.Entries) {
			t.Fatalf("n=%d: tree entries not strictly ascending", n)
		}
		if got := EntriesRoot(tree.EntryHashes()); got != tree.Root() {
			t.Fatalf("n=%d: entries root %x, tree root %x", n, got, tree.Root())
		}
		if got := EntriesRoot(EntryHashes(tree.Entries)); got != tree.Root() {
			t.Fatalf("n=%d: entry hashes of sorted entries do not give the root", n)
		}
	}
	if StrictlyAscending([]Entry{{Nonce: H32{2}}, {Nonce: H32{2}}}) || StrictlyAscending([]Entry{{Nonce: H32{2}}, {Nonce: H32{1}}}) {
		t.Fatal("repeated or descending nonces accepted")
	}
}

// Shared vectors with the contract: AnchorEntryList.t.sol
// test_computeRootSharedVectors asserts the same two roots for the same lists
// (the three entries of test-vectors/merkle-v1.json, and seven entries with
// nonce i + 1 and leaf keccak256 of the byte i).
func TestEntriesRootSharedVectors(t *testing.T) {
	var m struct {
		Root    string
		Entries []struct{ Nonce, ReceiptLeaf string }
	}
	readJSON(t, "test-vectors/merkle-v1.json", &m)
	var three []Entry
	for _, e := range m.Entries {
		three = append(three, Entry{H32(must32(t, e.Nonce)), H32(must32(t, e.ReceiptLeaf))})
	}
	if got := EntriesRoot(EntryHashes(three)); got != must32(t, "0xb0e5ce6b84df6db5f7e3847d05560064b749bdc676f4ad8ff9338ca0a71bf28a") || got != must32(t, m.Root) {
		t.Fatalf("three-entry root %x", got)
	}
	seven := make([]Entry, 7)
	for i := range seven {
		var nonce H32
		nonce[31] = byte(i + 1)
		seven[i] = Entry{Nonce: nonce, ReceiptLeaf: H32(protocol.Keccak256([]byte{byte(i)}))}
	}
	if got := EntriesRoot(EntryHashes(seven)); got != must32(t, "0x08cb9f67335b1ed71e5d9fec9415beb67e03f1064e97899b17d9cce31fba8f0f") {
		t.Fatalf("seven-entry root %x", got)
	}
}
