// Package verifier implements the verifier worker: it discovers finalized
// assignments, obtains the seller's serve bundle, runs the local predicate
// behind the authentication gate, and submits one signed verdict per
// assignment through the durable outbox in runtime/judgment.
package verifier

import (
	"bytes"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"example.org/fairbind/protocol"
	gate "example.org/fairbind/runtime/verifier"
)

// ServeBundleDomain is keccak256("fairbind/serve-bundle/v1").
var ServeBundleDomain = protocol.Keccak256([]byte("fairbind/serve-bundle/v1"))

// wireRequest, wireReceipt, wirePreimage, wireProof and wireBundle follow
// schemas/fairbind-serve-bundle-v1.schema.json and fairbind-receipt-v1.
type wireRequest struct {
	Method      string `json:"method"`
	Path        string `json:"path"`
	Query       string `json:"query"`
	HeaderBlock string `json:"headerBlock"`
	Body        string `json:"body"`
}

type wireReceipt struct {
	Version             int    `json:"version"`
	ChainID             string `json:"chainId"`
	ContractAddress     string `json:"contractAddress"`
	SellerID            uint32 `json:"sellerId"`
	ProfileID           uint32 `json:"profileId"`
	Nonce               string `json:"nonce"`
	RequestHash         string `json:"requestHash"`
	ResponseHash        string `json:"responseHash"`
	ClaimsHash          string `json:"claimsHash"`
	PredicateCommitment string `json:"predicateCommitment"`
	Epoch               uint32 `json:"epoch"`
	IssuedAt            string `json:"issuedAt"`
	Signature           string `json:"signature"`
}

type wirePreimage struct {
	Kind                string `json:"kind"`
	ReferenceTime       string `json:"referenceTime,omitempty"`
	SourceSetHash       string `json:"sourceSetHash,omitempty"`
	TolerancePolicyHash string `json:"tolerancePolicyHash,omitempty"`
	ToplocCommitment    string `json:"toplocCommitment,omitempty"`
	ModelHash           string `json:"modelHash,omitempty"`
	ConfigHash          string `json:"configHash,omitempty"`
}

type wireProof struct {
	Index    uint32   `json:"index"`
	Count    uint32   `json:"count"`
	Siblings []string `json:"siblings"`
}

type wireBundle struct {
	Version           int          `json:"version"`
	Nonce             string       `json:"nonce"`
	IdempotencyKey    string       `json:"idempotencyKey"`
	CanonicalRequest  wireRequest  `json:"canonicalRequest"`
	ResponseBody      string       `json:"responseBody"`
	Receipt           wireReceipt  `json:"receipt"`
	PredicatePreimage wirePreimage `json:"predicatePreimage"`
	ReceiptProof      *wireProof   `json:"receiptProof"`
	BundleHash        string       `json:"bundleHash"`
}

// BundleHash computes the serve bundle identifier from cryptography-v1 section 8.
func BundleHash(nonce protocol.Bytes32, key protocol.Bytes16, requestHash, responseHash, receiptDigest, predicateCommitment protocol.Bytes32) protocol.Bytes32 {
	var k [32]byte
	copy(k[:], key[:]) // abi.encode(bytes16) is left aligned.
	return protocol.Keccak256(ServeBundleDomain[:], nonce[:], k[:], requestHash[:], responseHash[:], receiptDigest[:], predicateCommitment[:])
}

func hex32(h protocol.Bytes32) string { return "0x" + hex.EncodeToString(h[:]) }

func parseHex(s string, n int) ([]byte, error) {
	if len(s) != 2+2*n || !strings.HasPrefix(s, "0x") {
		return nil, fmt.Errorf("expected %d-byte hex value", n)
	}
	return hex.DecodeString(s[2:])
}

func parse32(s string) (h protocol.Bytes32, err error) {
	b, err := parseHex(s, 32)
	copy(h[:], b)
	return h, err
}

func parseAddress(s string) (a protocol.Address, err error) {
	b, err := parseHex(s, 20)
	copy(a[:], b)
	return a, err
}

func b64(s string) ([]byte, error) { return base64.StdEncoding.Strict().DecodeString(s) }

// EncodeBundle produces the serve-bundle JSON for a bundle. Sellers and tests
// use it; the worker only decodes.
func EncodeBundle(chainID uint64, contract protocol.Address, b gate.Bundle, proof *protocol.ReceiptProof) ([]byte, error) {
	if len(b.Signature) != 65 {
		return nil, fmt.Errorf("receipt signature length")
	}
	r := b.Receipt
	enc := base64.StdEncoding.EncodeToString
	w := wireBundle{
		Version:          1,
		Nonce:            hex32(r.Nonce),
		IdempotencyKey:   "0x" + hex.EncodeToString(b.Key[:]),
		CanonicalRequest: wireRequest{enc(b.Request.Method), enc(b.Request.Path), enc(b.Request.Query), enc(b.Request.Headers), enc(b.Request.Body)},
		ResponseBody:     enc(b.Response),
		Receipt: wireReceipt{Version: int(r.Version), ChainID: strconv.FormatUint(chainID, 10), ContractAddress: "0x" + hex.EncodeToString(contract[:]),
			SellerID: r.SellerID, ProfileID: r.ProfileID, Nonce: hex32(r.Nonce), RequestHash: hex32(r.RequestHash), ResponseHash: hex32(r.ResponseHash),
			ClaimsHash: hex32(r.ClaimsHash), PredicateCommitment: hex32(r.PredicateCommitment), Epoch: r.Epoch, IssuedAt: strconv.FormatUint(r.IssuedAt, 10),
			Signature: "0x" + hex.EncodeToString(b.Signature)},
	}
	p := b.Preimage
	if p.ModelHash != (protocol.Bytes32{}) || p.ConfigHash != (protocol.Bytes32{}) || p.ToplocCommitment != (protocol.Bytes32{}) {
		w.PredicatePreimage = wirePreimage{Kind: "open-weights-inference", ToplocCommitment: hex32(p.ToplocCommitment), ModelHash: hex32(p.ModelHash), ConfigHash: hex32(p.ConfigHash)}
	} else {
		w.PredicatePreimage = wirePreimage{Kind: "data-api", ReferenceTime: strconv.FormatUint(p.ReferenceTime, 10), SourceSetHash: hex32(p.SourceSetHash), TolerancePolicyHash: hex32(p.TolerancePolicyHash)}
	}
	if proof != nil {
		wp := &wireProof{Index: proof.Index, Count: proof.Count, Siblings: []string{}}
		for _, s := range proof.Siblings {
			wp.Siblings = append(wp.Siblings, hex32(s))
		}
		w.ReceiptProof = wp
	}
	w.BundleHash = hex32(BundleHash(r.Nonce, b.Key, r.RequestHash, r.ResponseHash, protocol.ReceiptDigest(chainID, contract, r), r.PredicateCommitment))
	return json.Marshal(w)
}

func uintString(s string) (uint64, error) {
	if s == "" || (len(s) > 1 && s[0] == '0') {
		return 0, fmt.Errorf("invalid unsigned integer string")
	}
	return strconv.ParseUint(s, 10, 64)
}

// DecodeBundle strictly parses serve-bundle JSON, checks the receipt domain
// against the configured deployment and recomputes the bundle hash. It does
// NOT authenticate the receipt signature or the bindings to the ledger; the
// caller must run the verifier gate. Claims are not part of the bundle.
func DecodeBundle(raw []byte, chainID uint64, contract protocol.Address) (gate.Bundle, protocol.ReceiptProof, error) {
	var b gate.Bundle
	var proof protocol.ReceiptProof
	var w wireBundle
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&w); err != nil {
		return b, proof, fmt.Errorf("serve bundle: %w", err)
	}
	if dec.More() {
		return b, proof, fmt.Errorf("serve bundle: trailing data")
	}
	if w.Version != 1 || w.Receipt.Version != 1 {
		return b, proof, fmt.Errorf("serve bundle: unsupported version")
	}
	if w.Receipt.ChainID != strconv.FormatUint(chainID, 10) || !strings.EqualFold(w.Receipt.ContractAddress, "0x"+hex.EncodeToString(contract[:])) {
		return b, proof, fmt.Errorf("serve bundle: receipt domain mismatch")
	}
	key, err := parseHex(w.IdempotencyKey, 16)
	if err != nil {
		return b, proof, fmt.Errorf("serve bundle: idempotency key: %w", err)
	}
	copy(b.Key[:], key)
	fields := []struct {
		src string
		dst *[]byte
	}{{w.CanonicalRequest.Method, &b.Request.Method}, {w.CanonicalRequest.Path, &b.Request.Path}, {w.CanonicalRequest.Query, &b.Request.Query}, {w.CanonicalRequest.HeaderBlock, &b.Request.Headers}, {w.CanonicalRequest.Body, &b.Request.Body}, {w.ResponseBody, &b.Response}}
	for _, f := range fields {
		if *f.dst, err = b64(f.src); err != nil {
			return b, proof, fmt.Errorf("serve bundle: base64: %w", err)
		}
	}
	r := &b.Receipt
	r.Version, r.SellerID, r.ProfileID, r.Epoch = 1, w.Receipt.SellerID, w.Receipt.ProfileID, w.Receipt.Epoch
	if r.Epoch > 0xffffff {
		return b, proof, fmt.Errorf("serve bundle: epoch range")
	}
	if r.IssuedAt, err = uintString(w.Receipt.IssuedAt); err != nil {
		return b, proof, fmt.Errorf("serve bundle: issuedAt: %w", err)
	}
	for _, f := range []struct {
		src string
		dst *protocol.Bytes32
	}{{w.Receipt.Nonce, &r.Nonce}, {w.Receipt.RequestHash, &r.RequestHash}, {w.Receipt.ResponseHash, &r.ResponseHash}, {w.Receipt.ClaimsHash, &r.ClaimsHash}, {w.Receipt.PredicateCommitment, &r.PredicateCommitment}} {
		if *f.dst, err = parse32(f.src); err != nil {
			return b, proof, fmt.Errorf("serve bundle: receipt: %w", err)
		}
	}
	if b.Signature, err = parseHex(w.Receipt.Signature, 65); err != nil {
		return b, proof, fmt.Errorf("serve bundle: receipt signature: %w", err)
	}
	nonce, err := parse32(w.Nonce)
	if err != nil || nonce != r.Nonce {
		return b, proof, fmt.Errorf("serve bundle: nonce mismatch")
	}
	p := w.PredicatePreimage
	switch p.Kind {
	case "data-api":
		if p.ToplocCommitment != "" || p.ModelHash != "" || p.ConfigHash != "" {
			return b, proof, fmt.Errorf("serve bundle: mixed preimage")
		}
		if b.Preimage.ReferenceTime, err = uintString(p.ReferenceTime); err != nil {
			return b, proof, fmt.Errorf("serve bundle: referenceTime: %w", err)
		}
		if b.Preimage.SourceSetHash, err = parse32(p.SourceSetHash); err == nil {
			b.Preimage.TolerancePolicyHash, err = parse32(p.TolerancePolicyHash)
		}
	case "open-weights-inference":
		if p.ReferenceTime != "" || p.SourceSetHash != "" || p.TolerancePolicyHash != "" {
			return b, proof, fmt.Errorf("serve bundle: mixed preimage")
		}
		if b.Preimage.ToplocCommitment, err = parse32(p.ToplocCommitment); err == nil {
			if b.Preimage.ModelHash, err = parse32(p.ModelHash); err == nil {
				b.Preimage.ConfigHash, err = parse32(p.ConfigHash)
			}
		}
	default:
		err = fmt.Errorf("unknown kind")
	}
	if err != nil {
		return b, proof, fmt.Errorf("serve bundle: preimage: %w", err)
	}
	if w.ReceiptProof != nil {
		if w.ReceiptProof.Count == 0 || len(w.ReceiptProof.Siblings) > 32 {
			return b, proof, fmt.Errorf("serve bundle: receipt proof shape")
		}
		proof = protocol.ReceiptProof{Index: w.ReceiptProof.Index, Count: w.ReceiptProof.Count}
		for _, s := range w.ReceiptProof.Siblings {
			h, err := parse32(s)
			if err != nil {
				return b, proof, fmt.Errorf("serve bundle: proof sibling: %w", err)
			}
			proof.Siblings = append(proof.Siblings, h)
		}
	}
	want, err := parse32(w.BundleHash)
	if err != nil || want != BundleHash(r.Nonce, b.Key, r.RequestHash, r.ResponseHash, protocol.ReceiptDigest(chainID, contract, *r), r.PredicateCommitment) {
		return b, proof, fmt.Errorf("serve bundle: bundle hash mismatch")
	}
	return b, proof, nil
}
