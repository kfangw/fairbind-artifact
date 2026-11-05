package buyer

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
)

func (b *Buyer) paymentHeader(r *Record) (string, error) { return x402.EncodeHeader(r.Payload) }

func (b *Buyer) noteTx(r *Record, tx protocol.Bytes32) {
	if tx != (protocol.Bytes32{}) {
		r.Transactions = append(r.Transactions, x402.H32(tx).String())
	}
}

// verifyReceipt checks a receipt against the purchase and the response body.
func (b *Buyer) verifyReceipt(ctx context.Context, r *Record, rc x402.Receipt, body []byte, p chain.Purchase) error {
	if uint64(rc.ChainID) != b.chain.ChainID() || protocol.Address(rc.ContractAddress) != b.chain.Contract() || rc.Version != 1 {
		return errors.New("receipt names another deployment")
	}
	info := r.Payload.Extensions[x402.ExtensionKey].Info
	if rc.Nonce != *r.Nonce || rc.RequestHash != *r.RequestHash || rc.SellerID != info.SellerID ||
		rc.ProfileID != info.ProfileID || rc.ClaimsHash != info.ClaimsHash {
		return errors.New("receipt does not match the purchase")
	}
	if p.Exists() && rc.Epoch != p.Epoch {
		return errors.New("receipt epoch differs from the settlement epoch")
	}
	if protocol.ResponseHash(body) != protocol.Bytes32(rc.ResponseHash) {
		return errors.New("response does not hash to the receipt responseHash")
	}
	if rc.PredicateCommitment == (x402.H32{}) {
		return errors.New("receipt has an empty predicate commitment")
	}
	s, err := b.chain.GetSeller(ctx, rc.SellerID)
	if err != nil {
		return err
	}
	sig, err := rc.SignatureBytes()
	if err != nil {
		return err
	}
	return verifySig(s.SigningKey, rc.Digest(), sig)
}

// progressPaid sends (or resends) the saved payload. It never creates a new
// authorization for a purchase whose settlement may exist. After the
// response deadline without a valid receipt it opens a NON_DELIVERY case.
func (b *Buyer) progressPaid(ctx context.Context, r *Record) error {
	nonce := protocol.Bytes32(*r.Nonce)
	p, err := b.chain.GetPurchase(ctx, nonce)
	if err != nil {
		return err
	}
	block, err := b.chain.BlockNumber(ctx)
	if err != nil {
		return err
	}
	if p.Exists() {
		r.Epoch, r.ResponseDue, r.ClaimUntil = p.Epoch, p.ResponseDue, p.ClaimUntil
	} else if b.opt.Now() >= uint64(r.Payload.Payload.Authorization.ValidBefore) {
		keyID := protocol.DeriveKeyID(b.chain.ChainID(), b.chain.Contract(), r.SellerID, b.opt.Address, protocol.Bytes16(r.Key))
		if used, err := b.chain.PurchaseByKey(ctx, keyID); err == nil && used == (protocol.Bytes32{}) {
			// The authorization can no longer settle and nothing was recorded.
			r.State, r.Reason = StateAbandoned, "authorization expired without settlement"
			return b.put(r)
		}
	}
	undelivered := func(reason string) error {
		r.Reason = reason
		if p.Exists() && block > p.ResponseDue {
			return b.openNonDelivery(ctx, r, p, block)
		}
		return b.put(r)
	}
	header, err := b.paymentHeader(r)
	if err != nil {
		return err
	}
	resp, body, err := b.send(ctx, r, header)
	if err != nil {
		return undelivered("paid request failed: " + err.Error())
	}
	if resp.StatusCode != http.StatusOK {
		var sr x402.SettlementResponse
		if x402.DecodeHeader(resp.Header.Get(x402.HeaderPaymentResponse), &sr) == nil && sr.ErrorReason != "" {
			return undelivered(sr.ErrorReason)
		}
		return undelivered(fmt.Sprintf("paid request answered %d", resp.StatusCode))
	}
	var sr x402.SettlementResponse
	if err = x402.DecodeHeader(resp.Header.Get(x402.HeaderPaymentResponse), &sr); err == nil && sr.Success {
		r.Settlement = &sr
	}
	var rc x402.Receipt
	if err = x402.DecodeHeader(resp.Header.Get(x402.HeaderReceipt), &rc); err != nil {
		return undelivered(x402.ErrReceiptMissing)
	}
	if !p.Exists() {
		if p, err = b.chain.GetPurchase(ctx, nonce); err != nil {
			return err
		}
		r.Epoch, r.ResponseDue, r.ClaimUntil = p.Epoch, p.ResponseDue, p.ClaimUntil
	}
	if !p.Exists() {
		return undelivered("response without a recorded settlement")
	}
	if err = b.verifyReceipt(ctx, r, rc, body, p); err != nil {
		// An invalid receipt is not delivery.
		return undelivered("invalid receipt: " + err.Error())
	}
	r.Receipt = &rc
	r.Response = &StoredResponse{Status: resp.StatusCode, ContentType: resp.Header.Get("Content-Type"), Body: body, Source: "http"}
	r.State, r.Reason = StateReceived, ""
	return b.put(r)
}

func (b *Buyer) sellerBase(r *Record) (string, error) {
	u, err := url.Parse(r.Request.URL)
	if err != nil {
		return "", err
	}
	return u.Scheme + "://" + u.Host, nil
}

type proofResponse struct {
	Epoch       uint32     `json:"epoch"`
	Root        x402.H32   `json:"root"`
	Entry       x402.Entry `json:"entry"`
	Proof       x402.Proof `json:"proof"`
	ManifestURI string     `json:"manifestUri"`
}

// fetchProof requests the inclusion proof and verifies it against the root
// recorded on chain.
func (b *Buyer) fetchProof(ctx context.Context, r *Record, root protocol.Bytes32) error {
	base, err := b.sellerBase(r)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, base+"/fairbind/proofs/"+r.Nonce.String(), nil)
	if err != nil {
		return err
	}
	resp, err := b.opt.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("proof request answered %d", resp.StatusCode)
	}
	var pr proofResponse
	if err = json.NewDecoder(resp.Body).Decode(&pr); err != nil {
		return err
	}
	leaf := r.Receipt.Digest()
	if pr.Entry.Nonce != *r.Nonce || protocol.Bytes32(pr.Entry.ReceiptLeaf) != leaf ||
		!protocol.VerifyReceiptProof(root, protocol.ReceiptEntry{Nonce: protocol.Bytes32(*r.Nonce), ReceiptLeaf: leaf}, pr.Proof.Typed()) {
		return errors.New("inclusion proof does not verify against the anchored root")
	}
	h := x402.H32(root)
	r.Proof, r.AnchorRoot = &pr.Proof, &h
	return nil
}

// progressReceived obtains the inclusion proof once the epoch is anchored,
// and claims the epoch-failure refund when the seller missed the anchor.
func (b *Buyer) progressReceived(ctx context.Context, r *Record) error {
	nonce := protocol.Bytes32(*r.Nonce)
	a, err := b.chain.GetAnchor(ctx, r.SellerID, r.Epoch)
	if err != nil {
		return err
	}
	switch a.State {
	case chain.EpochAnchored, chain.EpochSealed:
		if err = b.fetchProof(ctx, r, a.Root); err != nil {
			r.Reason = err.Error()
			b.put(r)
			return b.claimIfFrozen(ctx, r)
		}
		r.State, r.Reason = StateProven, ""
		if err = b.put(r); err != nil {
			return err
		}
		return b.claimIfFrozen(ctx, r)
	case chain.EpochFailed:
		return b.claimEpochFailure(ctx, r, nonce)
	}
	s, err := b.chain.GetSeller(ctx, r.SellerID)
	if err != nil {
		return err
	}
	p, err := b.chain.GetProfile(ctx, s.ProfileID)
	if err != nil {
		return err
	}
	block, err := b.chain.BlockNumber(ctx)
	if err != nil {
		return err
	}
	if block > p.AnchorDeadline(r.Epoch) {
		return b.claimEpochFailure(ctx, r, nonce)
	}
	return b.claimIfFrozen(ctx, r)
}

func (b *Buyer) claimEpochFailure(ctx context.Context, r *Record, nonce protocol.Bytes32) error {
	st, err := b.chain.PurchaseState(ctx, nonce)
	if err != nil {
		return err
	}
	if st != chain.FinRefundable && st != chain.FinRefunded {
		tx, err := b.chain.ClaimEpochFailure(ctx, nonce)
		b.noteTx(r, tx)
		if err != nil {
			b.put(r)
			return err
		}
	}
	return b.claimRefund(ctx, r, nonce)
}

func (b *Buyer) claimRefund(ctx context.Context, r *Record, nonce protocol.Bytes32) error {
	st, err := b.chain.PurchaseState(ctx, nonce)
	if err != nil {
		return err
	}
	if st == chain.FinRefundable {
		tx, err := b.chain.ClaimRefund(ctx, nonce)
		b.noteTx(r, tx)
		if err != nil {
			b.put(r)
			return err
		}
		st = chain.FinRefunded
	}
	if st == chain.FinRefunded {
		r.State = StateRefunded
	}
	return b.put(r)
}

// claimIfFrozen claims the purchase amount with the receipt while the
// seller's bond account has an open claim window.
func (b *Buyer) claimIfFrozen(ctx context.Context, r *Record) error {
	if r.Receipt == nil {
		return nil
	}
	nonce := protocol.Bytes32(*r.Nonce)
	st, err := b.chain.PurchaseState(ctx, nonce)
	if err != nil || st != chain.FinFrozenClaimable {
		return err
	}
	if b.opt.WorstPath {
		cs, err := b.chain.GetCase(ctx, nonce)
		if err != nil || !claimAfterCase(cs.State) {
			return err
		}
	}
	a, err := b.chain.GetAnchor(ctx, r.SellerID, r.Epoch)
	if err != nil {
		return err
	}
	proof := protocol.ReceiptProof{}
	if a.State == chain.EpochAnchored || a.State == chain.EpochSealed {
		if r.Proof == nil || r.AnchorRoot == nil || protocol.Bytes32(*r.AnchorRoot) != a.Root {
			if err = b.fetchProof(ctx, r, a.Root); err != nil {
				return fmt.Errorf("claim needs an inclusion proof: %w", err)
			}
		}
		proof = r.Proof.Typed()
	}
	sig, err := r.Receipt.SignatureBytes()
	if err != nil {
		return err
	}
	tx, err := b.chain.ClaimRefundWithReceipt(ctx, nonce, r.Receipt.Typed(), sig, proof)
	b.noteTx(r, tx)
	if err != nil && !chain.IsRevert(err, "AlreadyClaimed") {
		b.put(r)
		return err
	}
	r.State = StateRefunded
	return b.put(r)
}

// claimAfterCase reports whether a purchase whose case is in state s may be
// claimed under the worst-path directive: only without a case or once the
// case has ended.
func claimAfterCase(s uint8) bool {
	switch s {
	case chain.CaseNone, chain.CaseDelivered, chain.CaseUnserved, chain.CaseInconclusive, chain.CaseFinal:
		return true
	}
	return false
}

// openNonDelivery opens the NON_DELIVERY case after the response deadline.
func (b *Buyer) openNonDelivery(ctx context.Context, r *Record, p chain.Purchase, block uint64) error {
	if b.opt.WorstPath {
		r.Reason = "undelivered; the worst-path directive opens no dispute"
		return b.put(r)
	}
	nonce := protocol.Bytes32(*r.Nonce)
	cs, err := b.chain.GetCase(ctx, nonce)
	if err != nil {
		return err
	}
	if cs.State == chain.CaseNone {
		if block > p.ClaimUntil {
			r.Reason = "claim window closed without delivery"
			return b.put(r)
		}
		tx, err := b.chain.Dispute(ctx, nonce, chain.TriggerNonDelivery, protocol.Receipt{}, nil)
		b.noteTx(r, tx)
		if err != nil {
			b.put(r)
			return err // a lost response is resolved by reading the case next time
		}
	}
	r.State, r.Reason = StateDisputed, ""
	if err = b.put(r); err != nil {
		return err
	}
	return b.progressDispute(ctx, r)
}

func (b *Buyer) serveAuthorization(ctx context.Context, nonce protocol.Bytes32, cs chain.Case) (string, error) {
	d := x402.ServeAuthDigest(b.chain.ChainID(), b.chain.Contract(), nonce, x402.RoleBuyer, cs.CaseOpenedBlock, cs.ChallengeUntil)
	sig, err := b.opt.Signer.SignDigest(ctx, d)
	if err != nil {
		return "", err
	}
	raw, err := json.Marshal(x402.ServeAuthorization{Role: x402.RoleBuyer, CaseOpenedBlock: cs.CaseOpenedBlock, ValidUntil: cs.ChallengeUntil, Signature: x402.Hex(sig)})
	return base64.StdEncoding.EncodeToString(raw), err
}

// fetchBundle retrieves and checks the served bundle against the case.
func (b *Buyer) fetchBundle(ctx context.Context, r *Record, cs chain.Case) (*x402.ServeBundle, error) {
	nonce := protocol.Bytes32(*r.Nonce)
	auth, err := b.serveAuthorization(ctx, nonce, cs)
	if err != nil {
		return nil, err
	}
	base, err := b.sellerBase(r)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, base+"/fairbind/serve/"+r.Nonce.String(), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set(x402.HeaderServeAuth, auth)
	resp, err := b.opt.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("serve request answered %d", resp.StatusCode)
	}
	var bundle x402.ServeBundle
	if err = json.NewDecoder(resp.Body).Decode(&bundle); err != nil {
		return nil, err
	}
	p, err := b.chain.GetPurchase(ctx, nonce)
	if err != nil {
		return nil, err
	}
	s, err := b.chain.GetSeller(ctx, r.SellerID)
	if err != nil {
		return nil, err
	}
	prof, err := b.chain.GetProfile(ctx, s.ProfileID)
	if err != nil {
		return nil, err
	}
	switch {
	case bundle.Nonce != *r.Nonce || bundle.IdempotencyKey != r.Key:
		return nil, errors.New("bundle names another purchase")
	case bundle.CanonicalRequest.Hash(prof.CanonID) != protocol.Bytes32(*r.RequestHash):
		return nil, errors.New("bundle request does not hash to the purchase requestHash")
	case bundle.ComputeHash() != cs.BundleHash || bundle.BundleHash != x402.H32(cs.BundleHash):
		return nil, errors.New("bundle does not match the served bundleHash")
	}
	commitment, err := bundle.PredicatePreimage.Commitment()
	if err != nil || commitment != protocol.Bytes32(bundle.Receipt.PredicateCommitment) {
		return nil, errors.New("predicate preimage does not match the receipt")
	}
	if err = b.verifyReceipt(ctx, r, bundle.Receipt, bundle.ResponseBody, p); err != nil {
		return nil, err
	}
	return &bundle, nil
}

// progressDispute follows the serve procedure of a NON_DELIVERY case.
func (b *Buyer) progressDispute(ctx context.Context, r *Record) error {
	nonce := protocol.Bytes32(*r.Nonce)
	cs, err := b.chain.GetCase(ctx, nonce)
	if err != nil {
		return err
	}
	block, err := b.chain.BlockNumber(ctx)
	if err != nil {
		return err
	}
	switch cs.State {
	case chain.CaseServeWait:
		if block > cs.ServeDue {
			tx, err := b.chain.TimeoutServe(ctx, nonce)
			b.noteTx(r, tx)
			b.put(r)
			return err
		}
	case chain.CaseServeConfirm:
		if block > cs.ChallengeUntil {
			return nil // anyone may finalize; the seller served
		}
		bundle, ferr := b.fetchBundle(ctx, r, cs)
		if ferr != nil {
			b.opt.Log.Printf("purchase %s: bundle rejected: %v", r.Nonce, ferr)
			r.Reason = "escalated: " + ferr.Error()
			tx, err := b.chain.Escalate(ctx, nonce)
			b.noteTx(r, tx)
			b.put(r)
			return err
		}
		r.Receipt = &bundle.Receipt
		r.Response = &StoredResponse{Status: 200, Body: bundle.ResponseBody, Source: "serve"}
		if err = b.put(r); err != nil {
			return err
		}
		tx, err := b.chain.AcceptServe(ctx, nonce)
		b.noteTx(r, tx)
		if err != nil {
			b.put(r)
			return err
		}
		r.State, r.Reason = StateReceived, ""
		return b.put(r)
	case chain.CasePublishing:
		if block > cs.PublishDue {
			tx, err := b.chain.TimeoutServe(ctx, nonce)
			b.noteTx(r, tx)
			b.put(r)
			return err
		}
	case chain.CaseDelivered:
		if r.Response != nil && r.Receipt != nil {
			r.State = StateReceived
			return b.put(r)
		}
		pub, err := b.chain.Publication(ctx, nonce)
		if err != nil || pub == nil {
			r.State, r.Reason = StateDelivered, "delivered on chain; body not retrieved"
			return b.put(r)
		}
		rc := receiptFromPublication(b, pub)
		p, err := b.chain.GetPurchase(ctx, nonce)
		if err != nil {
			return err
		}
		if err = b.verifyReceipt(ctx, r, rc, pub.Body, p); err != nil {
			r.State, r.Reason = StateDelivered, "published response failed verification: "+err.Error()
			return b.put(r)
		}
		r.Receipt = &rc
		r.Response = &StoredResponse{Status: 200, Body: pub.Body, Source: "publication"}
		r.State = StateReceived
		return b.put(r)
	case chain.CaseUnserved:
		return b.claimRefund(ctx, r, nonce)
	}
	return nil
}

func receiptFromPublication(b *Buyer, p *chain.Publication) x402.Receipt {
	rc := p.Receipt
	return x402.Receipt{Version: rc.Version, ChainID: x402.U64(b.chain.ChainID()), ContractAddress: x402.Addr(b.chain.Contract()),
		SellerID: rc.SellerID, ProfileID: rc.ProfileID, Nonce: x402.H32(rc.Nonce), RequestHash: x402.H32(rc.RequestHash),
		ResponseHash: x402.H32(rc.ResponseHash), ClaimsHash: x402.H32(rc.ClaimsHash), PredicateCommitment: x402.H32(rc.PredicateCommitment),
		Epoch: rc.Epoch, IssuedAt: x402.U64(rc.IssuedAt), Signature: x402.Hex(p.Signature)}
}
