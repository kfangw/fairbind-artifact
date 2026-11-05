package seller

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"net/http"
	"strconv"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/ethkey"
)

// proofFor returns the inclusion proof of a nonce when its epoch was anchored.
func (s *Seller) proofFor(epoch uint32, nonce protocol.Bytes32) (*x402.Proof, *EpochRecord, error) {
	var er EpochRecord
	ok, err := s.store.Get("epochs", strconv.FormatUint(uint64(epoch), 10), &er)
	if err != nil || !ok || (er.State != EpochAnchored && er.State != EpochSubmitting) {
		return nil, nil, err
	}
	tree, err := x402.BuildTree(er.Entries)
	if err != nil {
		return nil, nil, err
	}
	_, p, found := tree.Prove(nonce)
	if !found {
		return nil, &er, nil
	}
	return &p, &er, nil
}

// Bundle builds the serve bundle of a delivered purchase, producing the
// receipt first when the purchase is settled but was never delivered.
func (s *Seller) Bundle(ctx context.Context, nonce protocol.Bytes32) (*x402.ServeBundle, error) {
	unlock := s.lock(nonce)
	defer unlock()
	return s.bundleLocked(ctx, nonce)
}

func (s *Seller) bundleLocked(ctx context.Context, nonce protocol.Bytes32) (*x402.ServeBundle, error) {
	rec, err := s.getRecord(nonce)
	if err != nil {
		return nil, err
	}
	if rec == nil {
		return nil, fmt.Errorf("unknown purchase %s", x402.H32(nonce))
	}
	if rec.State == StateSettled {
		if err = s.deliver(ctx, rec); err != nil {
			return nil, err
		}
	}
	if rec.Receipt == nil || rec.Response == nil || rec.Request == nil {
		return nil, fmt.Errorf("purchase %s has no retained response", rec.Nonce)
	}
	b := &x402.ServeBundle{Version: 1, Nonce: rec.Nonce, IdempotencyKey: rec.Key, CanonicalRequest: *rec.Request,
		ResponseBody: rec.Response.Body, Receipt: *rec.Receipt, PredicatePreimage: rec.Response.Preimage}
	if p, a, err := s.proofFor(rec.Epoch, nonce); err == nil && a != nil && a.State == EpochAnchored {
		b.ReceiptProof = p
	}
	b.BundleHash = x402.H32(b.ComputeHash())
	return b, nil
}

// authError carries the HTTP status a serve-authorization failure maps to, so
// handleServe can distinguish a malformed header, an unknown or ended case,
// and an authorization that does not verify.
type authError struct {
	status int
	id     string
}

func (e *authError) Error() string { return e.id }

var (
	errAuthMalformed = &authError{http.StatusBadRequest, "serve_authorization_malformed"}
	errCaseUnknown   = &authError{http.StatusNotFound, "unknown_purchase"}
	errAuthInvalid   = &authError{http.StatusUnauthorized, "serve_authorization_invalid"}
)

// checkServeAuth validates a role-bound serve authorization against the
// current case.
func (s *Seller) checkServeAuth(ctx context.Context, nonce protocol.Bytes32, header string) error {
	raw, err := base64.StdEncoding.Strict().DecodeString(header)
	if err != nil {
		return errAuthMalformed
	}
	var a x402.ServeAuthorization
	if err = x402.DecodeStrict(raw, &a); err != nil {
		return errAuthMalformed
	}
	sig, err := x402.ParseHex(a.Signature)
	if err != nil {
		return errAuthMalformed
	}
	cs, err := s.chain.GetCase(ctx, nonce)
	if err != nil {
		return err
	}
	b, err := s.chain.BlockNumber(ctx)
	if err != nil {
		return err
	}
	var deadline uint64
	switch cs.State {
	case chain.CaseServeWait:
		deadline = cs.ServeDue
	case chain.CaseServeConfirm:
		deadline = cs.ChallengeUntil
	case chain.CasePublishing:
		deadline = cs.PublishDue
	case chain.CaseNone, chain.CaseDelivered, chain.CaseUnserved, chain.CaseInconclusive, chain.CaseFinal:
		// Either the nonce never opened a case (an unknown or unsettled
		// nonce) or its case already ended; either way there is nothing left
		// to serve.
		return errCaseUnknown
	default:
		deadline = a.ValidUntil // judging states: bounded by the verifier's own authorization
	}
	if a.CaseOpenedBlock != cs.CaseOpenedBlock || a.ValidUntil > deadline || b > a.ValidUntil {
		return errAuthInvalid
	}
	digest := x402.ServeAuthDigest(s.chain.ChainID(), s.chain.Contract(), nonce, a.Role, a.CaseOpenedBlock, a.ValidUntil)
	signer, err := ethkey.Recover(digest, sig)
	if err != nil {
		return errAuthInvalid
	}
	switch a.Role {
	case x402.RoleBuyer:
		p, err := s.chain.GetPurchase(ctx, nonce)
		if err != nil {
			return err
		}
		if signer != p.Buyer {
			return errAuthInvalid
		}
	case x402.RoleVerifier:
		v, err := s.chain.GetVerifier(ctx, cs.AssignedVerifierID)
		if err != nil {
			return err
		}
		if cs.AssignedVerifierID == 0 || signer != v.SigningKey {
			return errAuthInvalid
		}
	default:
		return errAuthMalformed
	}
	return nil
}

func parseNonce(r *http.Request) (protocol.Bytes32, bool) {
	h, err := x402.ParseH32(r.PathValue("nonce"))
	return protocol.Bytes32(h), err == nil
}

func (s *Seller) handleServe(w http.ResponseWriter, r *http.Request) {
	nonce, ok := parseNonce(r)
	if !ok {
		fail(w, http.StatusBadRequest, "invalid_nonce")
		return
	}
	if err := s.checkServeAuth(r.Context(), nonce, r.Header.Get(x402.HeaderServeAuth)); err != nil {
		var ae *authError
		if errors.As(err, &ae) {
			fail(w, ae.status, ae.id)
		} else {
			s.opt.Log.Printf("serve authorization %s: %v", x402.H32(nonce), err)
			fail(w, http.StatusInternalServerError, "serve_authorization_check_failed")
		}
		return
	}
	b, err := s.Bundle(r.Context(), nonce)
	if err != nil {
		s.opt.Log.Printf("serve %s: %v", x402.H32(nonce), err)
		fail(w, http.StatusNotFound, x402.ErrReceiptMissing)
		return
	}
	writeJSON(w, http.StatusOK, b)
}

// handleClaims answers GET /fairbind/claims with the exact registered claims
// document, so a caller can hash it and compare against the on-chain
// claimsHash independently of any purchase.
func (s *Seller) handleClaims(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "public, max-age=86400, immutable")
	w.Write(s.opt.Claims)
}

// ProofResponse answers GET /fairbind/proofs/{nonce}.
type ProofResponse struct {
	Epoch       uint32     `json:"epoch"`
	Root        x402.H32   `json:"root"`
	Entry       x402.Entry `json:"entry"`
	Proof       x402.Proof `json:"proof"`
	ManifestURI string     `json:"manifestUri"`
}

func (s *Seller) handleProof(w http.ResponseWriter, r *http.Request) {
	nonce, ok := parseNonce(r)
	if !ok {
		fail(w, http.StatusBadRequest, "invalid_nonce")
		return
	}
	rec, err := s.getRecord(nonce)
	if err != nil || rec == nil || (rec.State != StateDelivered && rec.State != StatePruned && rec.State != StateSettled) {
		fail(w, http.StatusNotFound, "unknown_purchase")
		return
	}
	p, er, err := s.proofFor(rec.Epoch, nonce)
	if err != nil || er == nil || er.State != EpochAnchored || p == nil {
		fail(w, http.StatusNotFound, "not_anchored")
		return
	}
	var leaf x402.H32
	for _, e := range er.Entries {
		if e.Nonce == x402.H32(nonce) {
			leaf = e.ReceiptLeaf
		}
	}
	writeJSON(w, http.StatusOK, ProofResponse{Epoch: rec.Epoch, Root: er.Root, Entry: x402.Entry{Nonce: x402.H32(nonce), ReceiptLeaf: leaf},
		Proof: *p, ManifestURI: fmt.Sprintf("%s/fairbind/epochs/%d/manifest", s.opt.PublicURL, rec.Epoch)})
}

func (s *Seller) epochFromPath(r *http.Request) (*EpochRecord, bool) {
	e, err := strconv.ParseUint(r.PathValue("epoch"), 10, 24)
	if err != nil {
		return nil, false
	}
	var er EpochRecord
	ok, err := s.store.Get("epochs", strconv.FormatUint(e, 10), &er)
	if err != nil || !ok || (er.State != EpochAnchored && er.State != EpochSubmitting) {
		return nil, false
	}
	return &er, true
}

func (s *Seller) handleEntries(w http.ResponseWriter, r *http.Request) {
	er, ok := s.epochFromPath(r)
	if !ok {
		fail(w, http.StatusNotFound, "unknown_epoch")
		return
	}
	_, raw, _ := x402.EntriesHash(er.Entries)
	w.Header().Set("Content-Type", "application/json")
	w.Write(raw)
}

func (s *Seller) handleManifest(w http.ResponseWriter, r *http.Request) {
	er, ok := s.epochFromPath(r)
	if !ok {
		fail(w, http.StatusNotFound, "unknown_epoch")
		return
	}
	_, raw, _ := x402.PublicationHash(er.Manifest)
	w.Header().Set("Content-Type", "application/json")
	w.Write(raw)
}
