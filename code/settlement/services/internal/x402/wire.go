package x402

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"reflect"
)

const (
	Version             = 2
	ExtensionKey        = "fairbind"
	AssetTransferMethod = "eip3009-fairbind-v1"
	PaymentFlow         = "upfront"
	Scheme              = "exact"

	HeaderPaymentRequired  = "PAYMENT-REQUIRED"
	HeaderPaymentSignature = "PAYMENT-SIGNATURE"
	HeaderPaymentResponse  = "PAYMENT-RESPONSE"
	HeaderReceipt          = "X-FairBind-Receipt"
	HeaderKey              = "X-FairBind-Key"
	HeaderPayer            = "X-FairBind-Payer"
	HeaderServeAuth        = "X-FairBind-Serve-Authorization"
)

// Stable error identifiers from x402-v2-integration.md section 10.
const (
	ErrExtensionMissing       = "fairbind_extension_missing"
	ErrExtensionInvalid       = "fairbind_extension_invalid"
	ErrExtensionEchoMismatch  = "fairbind_extension_echo_mismatch"
	ErrProfileMismatch        = "fairbind_profile_mismatch"
	ErrClaimsMismatch         = "fairbind_claims_mismatch"
	ErrUnknownCanon           = "fairbind_unknown_canon"
	ErrCanonicalizationFailed = "fairbind_canonicalization_failed"
	ErrRequestHashMismatch    = "fairbind_request_hash_mismatch"
	ErrNonceMismatch          = "fairbind_nonce_mismatch"
	ErrKeyUsed                = "fairbind_key_used"
	ErrKeyConflict            = "fairbind_key_conflict"
	ErrNonceUsed              = "fairbind_nonce_used"
	ErrSellerInactive         = "fairbind_seller_inactive"
	ErrRateLimited            = "fairbind_rate_limited"
	ErrValueTooLarge          = "fairbind_value_too_large"
	ErrSettlementPending      = "fairbind_settlement_pending"
	ErrReceiptMissing         = "fairbind_receipt_missing"
)

type Resource struct {
	URL         string `json:"url"`
	Description string `json:"description"`
	MimeType    string `json:"mimeType"`
	ServiceName string `json:"serviceName,omitempty"`
}

type AcceptExtra struct {
	AssetTransferMethod string `json:"assetTransferMethod"`
	PaymentFlow         string `json:"paymentFlow"`
	Name                string `json:"name"`
	Version             string `json:"version"`
}

type Accept struct {
	Scheme            string      `json:"scheme"`
	Network           string      `json:"network"`
	Amount            string      `json:"amount"`
	Asset             Addr        `json:"asset"`
	PayTo             Addr        `json:"payTo"`
	MaxTimeoutSeconds uint64      `json:"maxTimeoutSeconds"`
	Extra             AcceptExtra `json:"extra"`
}

// OfferInfo is the server-authored FairBind negotiation info. The two
// buyer-added fields are pointers so an unpaid offer omits them.
type OfferInfo struct {
	Version          int      `json:"version"`
	Contract         Addr     `json:"contract"`
	SellerID         uint32   `json:"sellerId"`
	ProfileID        uint32   `json:"profileId"`
	BondID           uint32   `json:"bondId"`
	ServiceClass     string   `json:"serviceClass"`
	PredicateID      H32      `json:"predicateId"`
	CanonID          H32      `json:"canonId"`
	ClaimsHash       H32      `json:"claimsHash"`
	ProfileHash      H32      `json:"profileHash"`
	CanonicalHeaders []string `json:"canonicalHeaders"`
	QuotedAtBlock    uint64   `json:"quotedAtBlock"`
	Remaining        uint64   `json:"remaining"`
	ResponseBlocks   uint64   `json:"responseBlocks"`
	ClaimBlocks      uint64   `json:"claimBlocks"`
	MaxRequestBytes  uint64   `json:"maxRequestBytes"`
	MaxResponseBytes uint64   `json:"maxResponseBytes"`
	RetentionBlocks  uint64   `json:"retentionBlocks"`
	IdempotencyKey   *H16     `json:"idempotencyKey,omitempty"`
	RequestHash      *H32     `json:"requestHash,omitempty"`
}

// ServerAuthored returns a copy without the buyer-added fields.
func (o OfferInfo) ServerAuthored() OfferInfo {
	o.IdempotencyKey = nil
	o.RequestHash = nil
	o.CanonicalHeaders = append([]string(nil), o.CanonicalHeaders...)
	return o
}

type OfferExtension struct {
	Info   OfferInfo       `json:"info"`
	Schema json.RawMessage `json:"schema"`
}

type PaymentRequired struct {
	X402Version int                       `json:"x402Version"`
	Error       string                    `json:"error"`
	Resource    Resource                  `json:"resource"`
	Accepts     []Accept                  `json:"accepts"`
	Extensions  map[string]OfferExtension `json:"extensions"`
}

type Authorization struct {
	From        Addr `json:"from"`
	To          Addr `json:"to"`
	Value       U64  `json:"value"`
	ValidAfter  U64  `json:"validAfter"`
	ValidBefore U64  `json:"validBefore"`
	Nonce       H32  `json:"nonce"`
}

type ExactPayload struct {
	Signature     string        `json:"signature"`
	Authorization Authorization `json:"authorization"`
}

type PaymentPayload struct {
	X402Version int                       `json:"x402Version"`
	Resource    Resource                  `json:"resource"`
	Accepted    Accept                    `json:"accepted"`
	Payload     ExactPayload              `json:"payload"`
	Extensions  map[string]OfferExtension `json:"extensions"`
}

type SettlementInfo struct {
	Version        int    `json:"version"`
	Purchase       H32    `json:"purchase"`
	KeyID          H32    `json:"keyId"`
	SellerID       uint32 `json:"sellerId"`
	ProfileID      uint32 `json:"profileId"`
	Epoch          uint32 `json:"epoch"`
	FinancialState string `json:"financialState"`
}

type SettlementExtension struct {
	Info   SettlementInfo  `json:"info"`
	Schema json.RawMessage `json:"schema"`
}

type SettlementResponse struct {
	Success     bool                           `json:"success"`
	ErrorReason string                         `json:"errorReason,omitempty"`
	Transaction string                         `json:"transaction"`
	Network     string                         `json:"network"`
	Payer       string                         `json:"payer,omitempty"`
	Amount      string                         `json:"amount,omitempty"`
	Extensions  map[string]SettlementExtension `json:"extensions,omitempty"`
}

// SettleRequest is the facilitator /settle and /verify request body.
type SettleRequest struct {
	X402Version         int            `json:"x402Version"`
	PaymentPayload      PaymentPayload `json:"paymentPayload"`
	PaymentRequirements Accept         `json:"paymentRequirements"`
}

type SupportedKind struct {
	X402Version int            `json:"x402Version"`
	Scheme      string         `json:"scheme"`
	Network     string         `json:"network"`
	Extra       map[string]any `json:"extra"`
}

type Supported struct {
	Kinds      []SupportedKind `json:"kinds"`
	Extensions []string        `json:"extensions"`
}

// EncodeHeader serializes v as compact JSON and returns standard padded base64.
func EncodeHeader(v any) (string, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(bytes.TrimSuffix(buf.Bytes(), []byte("\n"))), nil
}

// DecodeHeader reverses EncodeHeader and rejects unknown fields and
// trailing data.
func DecodeHeader(value string, v any) error {
	raw, err := base64.StdEncoding.Strict().DecodeString(value)
	if err != nil {
		return err
	}
	return DecodeStrict(raw, v)
}

// DecodeStrict decodes one JSON value with unknown fields rejected.
func DecodeStrict(raw []byte, v any) error {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(v); err != nil {
		return err
	}
	if dec.More() {
		return errors.New("trailing data")
	}
	return nil
}

// EncodeKey returns the unpadded base64url X-FairBind-Key value.
func EncodeKey(k H16) string { return base64.RawURLEncoding.EncodeToString(k[:]) }

// DecodeKey requires exactly 22 base64url characters.
func DecodeKey(s string) (H16, error) {
	var k H16
	if len(s) != 22 {
		return k, errors.New("key must be 22 base64url characters")
	}
	raw, err := base64.RawURLEncoding.Strict().DecodeString(s)
	if err != nil || len(raw) != 16 {
		return k, errors.New("invalid key encoding")
	}
	copy(k[:], raw)
	return k, nil
}

// SameJSON compares two JSON documents by value, ignoring member order.
func SameJSON(a, b []byte) bool {
	var x, y any
	if json.Unmarshal(a, &x) != nil || json.Unmarshal(b, &y) != nil {
		return false
	}
	return reflect.DeepEqual(x, y)
}

// InlineSchema reads a schema document and removes the top-level members the
// binding strips before inlining it ($id, title, description).
func InlineSchema(raw []byte) (json.RawMessage, error) {
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		return nil, err
	}
	delete(doc, "$id")
	delete(doc, "title")
	delete(doc, "description")
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(doc); err != nil {
		return nil, err
	}
	return json.RawMessage(bytes.TrimSuffix(buf.Bytes(), []byte("\n"))), nil
}

// LoadConfig reads a JSON configuration file, rejecting unknown fields.
func LoadConfig(path string, v any) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	if err = DecodeStrict(raw, v); err != nil {
		return fmt.Errorf("%s: %w", path, err)
	}
	return nil
}
