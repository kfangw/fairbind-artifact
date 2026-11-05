// Package judgment prepares bounded signed submissions and a durable send-once
// outbox. Uncertain broadcast is preserved for reconciliation, never auto-retried.
package judgment

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/evidence"
	"example.org/fairbind/runtime/ledger"
	"example.org/fairbind/runtime/verifier"
	"os"
	"path/filepath"
	"strconv"
	"syscall"
)

type Signer interface {
	SignDigest(context.Context, protocol.Bytes32) ([]byte, error)
}
type Source interface {
	Read(context.Context, protocol.Bytes32, ledger.ManifestBindings) (ledger.Assignment, error)
}
type Sender interface {
	Send(context.Context, protocol.Address, []byte) (protocol.Bytes32, error)
}
type Prepared struct {
	Assignment                                   ledger.Assignment
	Verdict                                      protocol.SignedVerdict
	Receipt                                      protocol.Receipt
	ReceiptSignature, VerdictSignature, CallData []byte
	Proof                                        protocol.ReceiptProof
}
type Outbox struct {
	Dir      string
	Objects  *evidence.Store
	Verifier verifier.CastVerifier
}

func key(a ledger.Assignment) string {
	v := protocol.SignedVerdict{Nonce: a.Snapshot.Nonce, Stage: a.Stage, Attempt: a.Attempt, VerifierID: a.VerifierID}
	return fmt.Sprintf("%x", protocol.VerdictDigest(a.Snapshot.ChainID, a.Snapshot.Contract, v))
}
func active(a ledger.Assignment) bool {
	return a.VerifierID > 0 && a.Stage >= 1 && a.Stage <= 4 && a.CaseState == map[uint8]uint8{1: 5, 2: 7, 3: 8, 4: 9}[a.Stage] && a.JudgeDue >= a.BlockNumber
}
func (o Outbox) lock() (func(), error) {
	if o.Objects == nil {
		return nil, fmt.Errorf("missing store")
	}
	if e := os.Mkdir(o.Dir, 0700); e != nil && !os.IsExist(e) {
		return nil, e
	}
	info, e := os.Lstat(o.Dir)
	if e != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, fmt.Errorf("invalid outbox directory")
	}
	parent, e := os.Open(filepath.Dir(o.Dir))
	if e != nil {
		return nil, e
	}
	e = parent.Sync()
	parent.Close()
	if e != nil {
		return nil, e
	}
	f, e := os.OpenFile(filepath.Join(o.Dir, ".lock"), os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if e != nil {
		return nil, e
	}
	if e = syscall.Flock(int(f.Fd()), syscall.LOCK_EX); e != nil {
		f.Close()
		return nil, e
	}
	return func() { syscall.Flock(int(f.Fd()), syscall.LOCK_UN); f.Close() }, nil
}
func save(path string, b []byte) error {
	f, e := os.CreateTemp(filepath.Dir(path), ".pending-")
	if e != nil {
		return e
	}
	name := f.Name()
	defer os.Remove(name)
	if _, e = f.Write(b); e == nil {
		e = f.Sync()
	}
	closeErr := f.Close()
	if e == nil {
		e = closeErr
	}
	if e != nil {
		return e
	}
	if e = os.Link(name, path); e != nil {
		return e
	}
	d, e := os.Open(filepath.Dir(path))
	if e != nil {
		return e
	}
	defer d.Close()
	return d.Sync()
}
func (o Outbox) Prepare(ctx context.Context, a ledger.Assignment, b verifier.Bundle, env evidence.Envelope, proof protocol.ReceiptProof, signer Signer) (Prepared, error) {
	var zero Prepared
	unlock, e := o.lock()
	if e != nil {
		return zero, e
	}
	defer unlock()
	if !active(a) || signer == nil {
		return zero, fmt.Errorf("assignment unavailable")
	}
	check := verifier.Check(ctx, a.Snapshot, b, o.Verifier)
	if check.Status != verifier.Ready && check.Status != verifier.Fail {
		return zero, fmt.Errorf("unauthenticated bundle: %s", check.Reason)
	}
	code := protocol.VerdictCode(env.Verdict)
	if code == protocol.VerdictNone || check.Status == verifier.Fail && code != protocol.VerdictFail {
		return zero, fmt.Errorf("invalid content result")
	}
	hx := func(h protocol.Bytes32) string { return fmt.Sprintf("0x%x", h) }
	if env.Nonce != hx(a.Snapshot.Nonce) || env.PredicateID != hx(a.Snapshot.PredicateID) || env.ClassID != int(a.Snapshot.ClassID) || env.ResponseHash != hx(b.Receipt.ResponseHash) || env.PredicateCommitment != hx(b.Receipt.PredicateCommitment) {
		return zero, fmt.Errorf("evidence binding mismatch")
	}
	if a.Trigger == 1 && (proof.Count != a.AnchorCount || !protocol.VerifyReceiptProof(a.AnchorRoot, protocol.ReceiptEntry{Nonce: a.Snapshot.Nonce, ReceiptLeaf: protocol.ReceiptDigest(a.Snapshot.ChainID, a.Snapshot.Contract, b.Receipt)}, proof)) {
		return zero, fmt.Errorf("sample proof invalid")
	}
	if env.ClassID == 1 {
		if env.Details["sourceSetHash"] != hx(b.Preimage.SourceSetHash) || env.Details["tolerancePolicyHash"] != hx(b.Preimage.TolerancePolicyHash) || env.Details["referenceTime"] != strconv.FormatUint(b.Preimage.ReferenceTime, 10) {
			return zero, fmt.Errorf("evidence preimage mismatch")
		}
	} else {
		if env.Details["modelHash"] != hx(b.Preimage.ModelHash) || env.Details["configHash"] != hx(b.Preimage.ConfigHash) || env.Details["toplocCommitment"] != hx(b.Preimage.ToplocCommitment) {
			return zero, fmt.Errorf("evidence preimage mismatch")
		}
	}
	raw, h, e := evidence.Build(env)
	if e != nil {
		return zero, e
	}
	if len(raw) > int(a.MaxEvidenceBytes) {
		return zero, fmt.Errorf("evidence limit")
	}
	// Every content-addressed evidence reference must be present and hash-checked.
	refs := []string{env.ImplementationHash}
	if env.ClassID == 1 {
		refs = append(refs, env.Details["sourceSetHash"], env.Details["tolerancePolicyHash"], env.Details["referenceResponsesHash"], env.Details["comparisonHash"])
	} else {
		refs = append(refs, env.Details["traceHash"], env.Details["configHash"])
	}
	for _, ref := range refs {
		var hash protocol.Bytes32
		if len(ref) != 66 || ref[:2] != "0x" {
			return zero, fmt.Errorf("invalid object reference")
		}
		decoded, decodeErr := hex.DecodeString(ref[2:])
		if decodeErr != nil {
			return zero, decodeErr
		}
		copy(hash[:], decoded)
		if _, e = o.Objects.Get(hash); e != nil {
			return zero, fmt.Errorf("unavailable referenced object")
		}
	}
	if _, e = o.Objects.Put(raw); e != nil {
		return zero, e
	}
	path := filepath.Join(o.Dir, key(a)+".json")
	if old, e := os.ReadFile(path); e == nil {
		var p Prepared
		if json.Unmarshal(old, &p) != nil || p.Verdict.EvidenceHash != h {
			return zero, fmt.Errorf("conflicting assignment result")
		}
		return p, nil
	} else if !os.IsNotExist(e) {
		return zero, e
	}
	v := protocol.SignedVerdict{Version: 1, Nonce: a.Snapshot.Nonce, Stage: a.Stage, Attempt: a.Attempt, VerifierID: a.VerifierID, Verdict: code, EvidenceHash: h}
	sig, e := signer.SignDigest(ctx, protocol.VerdictDigest(a.Snapshot.ChainID, a.Snapshot.Contract, v))
	if e != nil {
		return zero, e
	}
	if e = o.Verifier.Verify(ctx, a.VerifierKey, protocol.VerdictDigest(a.Snapshot.ChainID, a.Snapshot.Contract, v), sig); e != nil {
		return zero, e
	}
	call, e := EncodeJudge(v, sig, b.Receipt, b.Signature, proof)
	if e != nil {
		return zero, e
	}
	p := Prepared{a, v, b.Receipt, b.Signature, sig, call, proof}
	encoded, e := json.Marshal(p)
	if e != nil {
		return zero, e
	}
	if e = save(path, encoded); e != nil {
		return zero, e
	}
	return p, nil
}

// Submit verifies the saved record and a fresh finalized assignment, then durably
// marks the attempt BEFORE calling the sender. A crash/error requires explicit
// transaction/contract reconciliation; absence of a receipt is not permission to retry.
func (o Outbox) Submit(ctx context.Context, p Prepared, source Source, sender Sender) (protocol.Bytes32, error) {
	var zero protocol.Bytes32
	unlock, e := o.lock()
	if e != nil {
		return zero, e
	}
	defer unlock()
	raw, e := os.ReadFile(filepath.Join(o.Dir, key(p.Assignment)+".json"))
	if e != nil {
		return zero, e
	}
	want, e := json.Marshal(p)
	if e != nil || !bytes.Equal(raw, want) {
		return zero, fmt.Errorf("outbox mismatch")
	}
	if _, e = o.Objects.Get(p.Verdict.EvidenceHash); e != nil {
		return zero, e
	}
	if source == nil || sender == nil {
		return zero, fmt.Errorf("missing adapter")
	}
	s := p.Assignment.Snapshot
	a, e := source.Read(ctx, s.Nonce, ledger.ManifestBindings{SourceSetHash: s.SourceSetHash, TolerancePolicyHash: s.TolerancePolicyHash, ModelHash: s.ModelHash, ConfigHash: s.ConfigHash})
	if e != nil {
		return zero, e
	}
	if !active(a) || a.Snapshot != s || a.Stage != p.Verdict.Stage || a.Attempt != p.Verdict.Attempt || a.VerifierID != p.Verdict.VerifierID || a.VerifierKey != p.Assignment.VerifierKey || a.JudgeDue != p.Assignment.JudgeDue {
		return zero, fmt.Errorf("assignment changed")
	}
	if a.Trigger != p.Assignment.Trigger || a.MaxEvidenceBytes != p.Assignment.MaxEvidenceBytes || a.AnchorRoot != p.Assignment.AnchorRoot || a.AnchorCount != p.Assignment.AnchorCount {
		return zero, fmt.Errorf("proof context changed")
	}
	if err := o.validatePrepared(ctx, p); err != nil {
		return zero, err
	}
	marker := filepath.Join(o.Dir, key(p.Assignment)+".attempt")
	if e = save(marker, []byte("broadcast outcome may be unknown; reconcile before any retry\n")); e != nil {
		return zero, fmt.Errorf("already attempted or persistence failed: %w", e)
	}
	tx, e := sender.Send(ctx, s.Contract, p.CallData)
	if e != nil {
		return zero, fmt.Errorf("broadcast uncertain: %w", e)
	}
	if tx == zero {
		return zero, fmt.Errorf("broadcast uncertain: empty transaction")
	}
	if e = save(marker+".tx", []byte(fmt.Sprintf("0x%x\n", tx))); e != nil {
		return tx, fmt.Errorf("broadcast acknowledged but receipt persistence failed: %w", e)
	}
	return tx, nil
}

func (o Outbox) validatePrepared(ctx context.Context, p Prepared) error {
	a := p.Assignment
	s := a.Snapshot
	if p.Verdict.Nonce != s.Nonce || p.Verdict.Stage != a.Stage || p.Verdict.Attempt != a.Attempt || p.Verdict.VerifierID != a.VerifierID {
		return fmt.Errorf("prepared identity mismatch")
	}
	if e := o.Verifier.Verify(ctx, a.VerifierKey, protocol.VerdictDigest(s.ChainID, s.Contract, p.Verdict), p.VerdictSignature); e != nil {
		return e
	}
	if e := o.Verifier.Verify(ctx, s.SellerKey, protocol.ReceiptDigest(s.ChainID, s.Contract, p.Receipt), p.ReceiptSignature); e != nil {
		return e
	}
	call, e := EncodeJudge(p.Verdict, p.VerdictSignature, p.Receipt, p.ReceiptSignature, p.Proof)
	if e != nil || !bytes.Equal(call, p.CallData) {
		return fmt.Errorf("prepared calldata mismatch")
	}
	raw, e := o.Objects.Get(p.Verdict.EvidenceHash)
	if e != nil {
		return e
	}
	if len(raw) > int(a.MaxEvidenceBytes) {
		return fmt.Errorf("evidence limit")
	}
	env, e := evidence.Parse(raw)
	if e != nil {
		return e
	}
	if env.Nonce != fmt.Sprintf("0x%x", s.Nonce) || protocol.VerdictCode(env.Verdict) != p.Verdict.Verdict {
		return fmt.Errorf("prepared evidence mismatch")
	}
	refs := []string{env.ImplementationHash}
	if env.ClassID == 1 {
		for _, k := range []string{"sourceSetHash", "tolerancePolicyHash", "referenceResponsesHash", "comparisonHash"} {
			refs = append(refs, env.Details[k])
		}
	} else {
		refs = append(refs, env.Details["traceHash"], env.Details["configHash"])
	}
	for _, ref := range refs {
		if len(ref) != 66 {
			return fmt.Errorf("reference hash")
		}
		decoded, e := hex.DecodeString(ref[2:])
		if e != nil {
			return e
		}
		var h protocol.Bytes32
		copy(h[:], decoded)
		if _, e = o.Objects.Get(h); e != nil {
			return fmt.Errorf("referenced object unavailable")
		}
	}
	if a.Trigger == 1 && (p.Proof.Count != a.AnchorCount || !protocol.VerifyReceiptProof(a.AnchorRoot, protocol.ReceiptEntry{Nonce: s.Nonce, ReceiptLeaf: protocol.ReceiptDigest(s.ChainID, s.Contract, p.Receipt)}, p.Proof)) {
		return fmt.Errorf("sample proof invalid")
	}
	return nil
}

// Load recovers a saved assignment after restart without signing again. An
// attempt marker remains authoritative even when no transaction hash was saved.
func (o Outbox) Load(ctx context.Context, a ledger.Assignment) (Prepared, bool, error) {
	var p Prepared
	unlock, e := o.lock()
	if e != nil {
		return p, false, e
	}
	defer unlock()
	path := filepath.Join(o.Dir, key(a)+".json")
	info, e := os.Lstat(path)
	if e != nil {
		return p, false, e
	}
	if !info.Mode().IsRegular() || info.Size() > 2<<20 {
		return p, false, fmt.Errorf("invalid outbox record")
	}
	raw, e := os.ReadFile(path)
	if e != nil {
		return p, false, e
	}
	if e = json.Unmarshal(raw, &p); e != nil {
		return p, false, e
	}
	if key(p.Assignment) != key(a) {
		return p, false, fmt.Errorf("record identity mismatch")
	}
	if e = o.validatePrepared(ctx, p); e != nil {
		return p, false, e
	}
	_, e = os.Lstat(filepath.Join(o.Dir, key(a)+".attempt"))
	if e == nil {
		return p, true, nil
	}
	if !os.IsNotExist(e) {
		return p, false, e
	}
	return p, false, nil
}

// Evaluator is trusted local code that runs the authenticated predicate and
// stores reproducible reference/comparison objects. It must never simply forward
// an untrusted peer's verdict or evidence envelope.
type Evaluator interface {
	Evaluate(context.Context, ledger.Assignment, verifier.Bundle) (evidence.Envelope, error)
}

// RunOnce composes finalized read, local evaluation, durable preparation and a
// fresh-read send. It neither polls nor retries an uncertain submission.
func (o Outbox) RunOnce(ctx context.Context, nonce protocol.Bytes32, bindings ledger.ManifestBindings, b verifier.Bundle, proof protocol.ReceiptProof, source Source, evaluator Evaluator, signer Signer, sender Sender) (protocol.Bytes32, error) {
	var zero protocol.Bytes32
	if source == nil || evaluator == nil {
		return zero, fmt.Errorf("missing adapter")
	}
	a, e := source.Read(ctx, nonce, bindings)
	if e != nil {
		return zero, e
	}
	if !active(a) {
		return zero, fmt.Errorf("assignment unavailable")
	}
	auth := verifier.Check(ctx, a.Snapshot, b, o.Verifier)
	if auth.Status != verifier.Ready && auth.Status != verifier.Fail {
		return zero, fmt.Errorf("bundle not authenticated")
	}
	env, e := evaluator.Evaluate(ctx, a, b)
	if e != nil {
		return zero, e
	}
	p, e := o.Prepare(ctx, a, b, env, proof, signer)
	if e != nil {
		return zero, e
	}
	return o.Submit(ctx, p, source, sender)
}
