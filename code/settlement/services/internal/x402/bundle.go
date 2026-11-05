package x402

import (
	"bytes"
	"encoding/json"

	"example.org/fairbind/protocol"
)

// CanonicalRequest holds the five normalized request fields. encoding/json
// encodes []byte as standard padded base64, which the bundle schema uses.
type CanonicalRequest struct {
	Method      []byte `json:"method"`
	Path        []byte `json:"path"`
	Query       []byte `json:"query"`
	HeaderBlock []byte `json:"headerBlock"`
	Body        []byte `json:"body"`
}

// Hash is the canonicalization-v1 request hash.
func (c CanonicalRequest) Hash(canonID protocol.Bytes32) protocol.Bytes32 {
	words := append([]byte{}, canonID[:]...)
	for _, b := range [][]byte{c.Method, c.Path, c.Query, c.HeaderBlock, c.Body} {
		h := protocol.Keccak256(b)
		words = append(words, h[:]...)
	}
	return protocol.Keccak256(words)
}

// Size is the combined byte length the contract bounds by maxRequestBytes.
func (c CanonicalRequest) Size() int {
	return len(c.Method) + len(c.Path) + len(c.Query) + len(c.HeaderBlock) + len(c.Body)
}

// ServeBundle follows schemas/fairbind-serve-bundle-v1.schema.json.
type ServeBundle struct {
	Version           int              `json:"version"`
	Nonce             H32              `json:"nonce"`
	IdempotencyKey    H16              `json:"idempotencyKey"`
	CanonicalRequest  CanonicalRequest `json:"canonicalRequest"`
	ResponseBody      []byte           `json:"responseBody"`
	Receipt           Receipt          `json:"receipt"`
	PredicatePreimage Preimage         `json:"predicatePreimage"`
	ReceiptProof      *Proof           `json:"receiptProof"`
	BundleHash        H32              `json:"bundleHash"`
}

// BundleHash computes the cryptography-v1 section 8 hash.
func BundleHash(nonce protocol.Bytes32, key protocol.Bytes16, requestHash, responseHash, receiptDigest, commitment protocol.Bytes32) protocol.Bytes32 {
	k := make([]byte, 32)
	copy(k, key[:])
	return protocol.Keccak256(serveBundleDomain[:], nonce[:], k, requestHash[:], responseHash[:], receiptDigest[:], commitment[:])
}

// ComputeHash recomputes the bundle hash from its content.
func (b ServeBundle) ComputeHash() protocol.Bytes32 {
	return BundleHash(protocol.Bytes32(b.Nonce), protocol.Bytes16(b.IdempotencyKey), protocol.Bytes32(b.Receipt.RequestHash),
		protocol.ResponseHash(b.ResponseBody), b.Receipt.Digest(), protocol.Bytes32(b.Receipt.PredicateCommitment))
}

// CanonicalJSON returns a compact JSON encoding with object members sorted by
// key and no HTML escaping. For the ASCII strings and integers below 2^53 used
// in manifests, this equals RFC 8785 (JCS) output.
func CanonicalJSON(v any) ([]byte, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	var generic any
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	if err = dec.Decode(&generic); err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err = enc.Encode(generic); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(buf.Bytes(), []byte("\n")), nil
}

// Manifest is the epoch publication manifest.
type Manifest struct {
	Version     int    `json:"version"`
	SellerID    uint32 `json:"sellerId"`
	ProfileID   uint32 `json:"profileId"`
	Epoch       uint32 `json:"epoch"`
	Root        H32    `json:"root"`
	Count       uint32 `json:"count"`
	EntriesURI  string `json:"entriesUri"`
	EntriesHash H32    `json:"entriesHash"`
	CreatedAt   string `json:"createdAt"`
}

// EntriesHash is keccak256 of the canonical JSON of the sorted entry list.
func EntriesHash(entries []Entry) (protocol.Bytes32, []byte, error) {
	raw, err := CanonicalJSON(entries)
	if err != nil {
		return protocol.Bytes32{}, nil, err
	}
	return protocol.Keccak256(raw), raw, nil
}

// PublicationHash is keccak256(UTF8(JCS(manifest))).
func PublicationHash(m Manifest) (protocol.Bytes32, []byte, error) {
	raw, err := CanonicalJSON(m)
	if err != nil {
		return protocol.Bytes32{}, nil, err
	}
	return protocol.Keccak256(raw), raw, nil
}
