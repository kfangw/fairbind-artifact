package verifier

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/ledger"
	gate "example.org/fairbind/runtime/verifier"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
)

// Seller obtains the serve bundle and the registered claims bytes for an
// assignment. Everything it returns is untrusted until the verifier gate has
// bound it to the finalized ledger snapshot.
type Seller interface {
	Redeliver(ctx context.Context, a ledger.Assignment) (gate.Bundle, protocol.ReceiptProof, error)
}

// checkEndpoint accepts HTTPS, or plain HTTP only to a literal loopback address.
func checkEndpoint(raw string) (*url.URL, error) {
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" || u.User != nil || u.Fragment != "" || u.RawQuery != "" {
		return nil, fmt.Errorf("invalid endpoint URL")
	}
	ip := net.ParseIP(u.Hostname())
	if u.Scheme != "https" && !(u.Scheme == "http" && ip != nil && ip.IsLoopback()) {
		return nil, fmt.Errorf("endpoint requires HTTPS or literal loopback HTTP")
	}
	return u, nil
}

// Signer signs the FairBindServeAuthorization digest with the verifier's
// registered signing key. judgment.KeystoreSigner and ethkey.PrivateKey both
// satisfy this by their identical SignDigest method.
type Signer interface {
	SignDigest(ctx context.Context, digest protocol.Bytes32) ([]byte, error)
}

// CaseReader is the minimal on-chain view HTTPSeller needs to build a serve
// authorization: the case's opening block. chain.Client (services/internal/
// x402/chain) satisfies this.
type CaseReader interface {
	GetCase(ctx context.Context, nonce protocol.Bytes32) (chain.Case, error)
}

// HTTPSeller calls a seller's redelivery endpoints:
//
//	GET {base}/fairbind/serve/{nonce}   X-FairBind-Serve-Authorization -> serve bundle v1 JSON
//	GET {base}/fairbind/claims          -> the exact registered claims bytes
type HTTPSeller struct {
	ChainID   uint64
	Contract  protocol.Address
	Endpoints map[uint32]string // seller ID -> base URL
	Client    *http.Client
	MaxBytes  int64
	Cases     CaseReader // reads the active case's caseOpenedBlock
	Signer    Signer     // signs the FairBindServeAuthorization digest
}

func (s HTTPSeller) client() *http.Client {
	if s.Client != nil {
		return s.Client
	}
	return &http.Client{Timeout: 15 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
}

func (s HTTPSeller) do(ctx context.Context, method, target string, header http.Header) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, method, target, nil)
	if err != nil {
		return nil, err
	}
	for k, vs := range header {
		for _, v := range vs {
			req.Header.Add(k, v)
		}
	}
	res, err := s.client().Do(req)
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	limit := s.MaxBytes
	if limit <= 0 {
		limit = 4 << 20
	}
	raw, err := io.ReadAll(io.LimitReader(res.Body, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(raw)) > limit {
		return nil, fmt.Errorf("seller response exceeds limit")
	}
	if res.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("seller HTTP status %d", res.StatusCode)
	}
	return raw, nil
}

// serveAuthHeader signs a FairBindServeAuthorization for the verifier role,
// valid through the assignment's judge deadline (the assignment is never
// worked past that block; see Worker.tooLate), and encodes it as the
// X-FairBind-Serve-Authorization header value.
func (s HTTPSeller) serveAuthHeader(ctx context.Context, a ledger.Assignment) (string, error) {
	if s.Cases == nil || s.Signer == nil {
		return "", fmt.Errorf("case reader and signer are required")
	}
	cs, err := s.Cases.GetCase(ctx, a.Snapshot.Nonce)
	if err != nil {
		return "", err
	}
	validUntil := a.JudgeDue
	digest := x402.ServeAuthDigest(s.ChainID, s.Contract, a.Snapshot.Nonce, x402.RoleVerifier, cs.CaseOpenedBlock, validUntil)
	sig, err := s.Signer.SignDigest(ctx, digest)
	if err != nil {
		return "", err
	}
	raw, err := json.Marshal(x402.ServeAuthorization{Role: x402.RoleVerifier, CaseOpenedBlock: cs.CaseOpenedBlock, ValidUntil: validUntil, Signature: x402.Hex(sig)})
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(raw), nil
}

func (s HTTPSeller) Redeliver(ctx context.Context, a ledger.Assignment) (gate.Bundle, protocol.ReceiptProof, error) {
	base, ok := s.Endpoints[a.Snapshot.SellerID]
	if !ok {
		return gate.Bundle{}, protocol.ReceiptProof{}, fmt.Errorf("no endpoint for seller %d", a.Snapshot.SellerID)
	}
	u, err := checkEndpoint(base)
	if err != nil {
		return gate.Bundle{}, protocol.ReceiptProof{}, err
	}
	root := strings.TrimSuffix(u.String(), "/")
	auth, err := s.serveAuthHeader(ctx, a)
	if err != nil {
		return gate.Bundle{}, protocol.ReceiptProof{}, fmt.Errorf("serve authorization: %w", err)
	}
	raw, err := s.do(ctx, http.MethodGet, root+"/fairbind/serve/"+hex32(a.Snapshot.Nonce), http.Header{x402.HeaderServeAuth: {auth}})
	if err != nil {
		return gate.Bundle{}, protocol.ReceiptProof{}, fmt.Errorf("redelivery: %w", err)
	}
	b, proof, err := DecodeBundle(raw, s.ChainID, s.Contract)
	if err != nil {
		return gate.Bundle{}, protocol.ReceiptProof{}, err
	}
	if b.Claims, err = s.do(ctx, http.MethodGet, root+"/fairbind/claims", nil); err != nil {
		return gate.Bundle{}, protocol.ReceiptProof{}, fmt.Errorf("claims: %w", err)
	}
	return b, proof, nil
}
