// Package inference connects authenticated class-2 bundles to the Python
// re-execution pipeline in evaluate.py. The Go side runs the input gate; only a
// bundle the gate reports READY or FAIL is passed to the subprocess.
package inference

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/verifier"
)

// Verdict is the three-way result of the inference predicate pipeline.
type Verdict string

const (
	Pass         Verdict = "PASS"
	Fail         Verdict = "FAIL"
	Inconclusive Verdict = "INCONCLUSIVE"
)

// ErrNotJudged is returned when the bundle does not pass the input gate with
// READY or FAIL. No subprocess is started for such a bundle.
var ErrNotJudged = errors.New("bundle did not pass the input gate; not judged")

// EvidenceFormat is the experimental layout written by evaluate.py.
const EvidenceFormat = "fairbind/experimental/inference-evidence/v1"

// MaxOutputBytes bounds the subprocess output.
const MaxOutputBytes = 8 << 20

// PredicateID is OPEN_WEIGHTS_TOPLOC_V1.
var PredicateID = mustHash("0xdc77e562812ea60a876f258021aea1da480f6035092b70aa11ca0f5ae1dae9ad")

func mustHash(s string) (h protocol.Bytes32) {
	b, err := hex.DecodeString(s[2:])
	if err != nil || len(b) != 32 {
		panic("invalid bytes32")
	}
	copy(h[:], b)
	return h
}

// Profile is the trusted input of one evaluation: the finalized snapshot, and
// the configuration manifests and local weight directories this verifier holds,
// keyed by their committed hashes. A missing entry makes the result
// INCONCLUSIVE; it never substitutes another model or configuration.
type Profile struct {
	Snapshot verifier.Snapshot
	Configs  map[protocol.Bytes32][]byte
	Models   map[protocol.Bytes32]string
}

// Pipeline runs gate -> evaluate.py. Python and Script are trusted operator
// configuration; bundle content never selects an executable or path.
type Pipeline struct {
	Signature      verifier.CastVerifier
	Python, Script string
	// Timeout bounds one re-execution. Zero means 10 minutes.
	Timeout time.Duration
}

// Evidence is the canonical evidence object returned by evaluate.py together
// with the fields a caller needs. Raw holds the exact canonical bytes and Hash
// their Keccak-256.
type Evidence struct {
	Raw                  []byte
	Hash                 protocol.Bytes32
	Verdict, Reason      string
	InputHash            string
	ModelHash            string
	ConfigHash           string
	ToplocCommitment     string
	ReproducedCommitment string
	SellerOutputHash     string
	ReexecutedOutputHash string
	RecordHash           string
	Record               []byte
}

func hex32(h protocol.Bytes32) string { return "0x" + hex.EncodeToString(h[:]) }

type wireGate struct {
	Status string `json:"status"`
	Reason string `json:"reason"`
}
type wireBundle struct {
	Gate                wireGate          `json:"gate"`
	Claims              string            `json:"claims"`
	Preimage            map[string]string `json:"preimage"`
	PredicateCommitment string            `json:"predicateCommitment"`
	Request             string            `json:"request"`
	Response            string            `json:"response"`
	Nonce               string            `json:"nonce"`
}
type wireProfile struct {
	Configs map[string]string `json:"configs"`
	Models  map[string]string `json:"models"`
}
type wireOutput struct {
	Verdict      string `json:"verdict"`
	Evidence     string `json:"evidence"`
	EvidenceHash string `json:"evidenceHash"`
	NotJudged    string `json:"notJudged"`
}

// Evaluate authenticates the bundle and, when admitted, re-executes the
// committed model through evaluate.py. The request body of the canonical
// request carries the prompt token IDs and the response body the output
// token IDs and the TOPLOC trace (see evaluate.py). An error means no verdict:
// either the bundle was not judged (ErrNotJudged) or the local runtime failed.
func (p Pipeline) Evaluate(ctx context.Context, b verifier.Bundle, prof Profile) (Verdict, Evidence, error) {
	s := prof.Snapshot
	g := verifier.Check(ctx, s, b, p.Signature)
	if g.Status != verifier.Ready && g.Status != verifier.Fail {
		return "", Evidence{}, fmt.Errorf("%w: %s", ErrNotJudged, g.Reason)
	}
	if s.ClassID != 2 || s.PredicateID != PredicateID {
		return "", Evidence{}, errors.New("not an open-weights profile")
	}
	if p.Python == "" || p.Script == "" {
		return "", Evidence{}, errors.New("inference runtime not configured")
	}
	enc := base64.StdEncoding.EncodeToString
	in := struct {
		Bundle  wireBundle  `json:"bundle"`
		Profile wireProfile `json:"profile"`
	}{
		Bundle: wireBundle{Gate: wireGate{string(g.Status), g.Reason}, Claims: enc(b.Claims),
			Preimage:            map[string]string{"toplocCommitment": hex32(b.Preimage.ToplocCommitment), "modelHash": hex32(b.Preimage.ModelHash), "configHash": hex32(b.Preimage.ConfigHash)},
			PredicateCommitment: hex32(b.Receipt.PredicateCommitment), Request: enc(b.Request.Body), Response: enc(b.Response), Nonce: hex32(s.Nonce)},
		Profile: wireProfile{Configs: map[string]string{}, Models: map[string]string{}},
	}
	for h, c := range prof.Configs {
		in.Profile.Configs[hex32(h)] = enc(c)
	}
	for h, dir := range prof.Models {
		in.Profile.Models[hex32(h)] = dir
	}
	payload, err := json.Marshal(in)
	if err != nil {
		return "", Evidence{}, err
	}
	timeout := p.Timeout
	if timeout == 0 {
		timeout = 10 * time.Minute
	}
	cctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(cctx, p.Python, p.Script)
	cmd.Stdin = bytes.NewReader(payload)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return "", Evidence{}, err
	}
	if err = cmd.Start(); err != nil {
		return "", Evidence{}, fmt.Errorf("inference runtime: %w", err)
	}
	out, readErr := io.ReadAll(io.LimitReader(stdout, MaxOutputBytes+1))
	if err = cmd.Wait(); err != nil || readErr != nil || len(out) > MaxOutputBytes {
		return "", Evidence{}, fmt.Errorf("inference runtime failed: %v %s", err, bytes.TrimSpace(stderr.Bytes()))
	}
	return decodeOutput(out, s, b, g)
}

func decodeOutput(out []byte, s verifier.Snapshot, b verifier.Bundle, g verifier.Result) (Verdict, Evidence, error) {
	var w wireOutput
	d := json.NewDecoder(bytes.NewReader(out))
	d.DisallowUnknownFields()
	if err := d.Decode(&w); err != nil {
		return "", Evidence{}, fmt.Errorf("inference output: %w", err)
	}
	if w.NotJudged != "" {
		// The Go gate admitted the bundle, so this is a runtime inconsistency.
		return "", Evidence{}, fmt.Errorf("inference runtime refused an admitted bundle: %s", w.NotJudged)
	}
	raw := []byte(w.Evidence)
	fields, err := canonicalEvidence(raw)
	if err != nil {
		return "", Evidence{}, err
	}
	ev := Evidence{Raw: raw, Hash: protocol.Keccak256(raw)}
	if hex32(ev.Hash) != w.EvidenceHash {
		return "", Evidence{}, errors.New("evidence hash mismatch")
	}
	str := func(k string) string { v, _ := fields[k].(string); return v }
	ev.Verdict, ev.Reason = str("verdict"), str("reason")
	ev.InputHash, ev.ModelHash, ev.ConfigHash, ev.ToplocCommitment = str("inputHash"), str("modelHash"), str("configHash"), str("toplocCommitment")
	ev.ReproducedCommitment, ev.SellerOutputHash, ev.ReexecutedOutputHash = str("reproducedCommitment"), str("sellerOutputHash"), str("reexecutedOutputHash")
	ev.Record = []byte(str("record"))
	if c, ok := fields["comparison"].(map[string]any); ok {
		ev.RecordHash, _ = c["recordHash"].(string)
	}
	v := Verdict(ev.Verdict)
	switch {
	case str("format") != EvidenceFormat || fields["version"] != json.Number("1"):
		return "", Evidence{}, errors.New("unsupported evidence format")
	case v != Pass && v != Fail && v != Inconclusive || w.Verdict != ev.Verdict:
		return "", Evidence{}, errors.New("invalid verdict")
	case str("nonce") != hex32(s.Nonce) || str("predicateCommitment") != hex32(b.Receipt.PredicateCommitment) ||
		ev.ModelHash != hex32(b.Preimage.ModelHash) || ev.ConfigHash != hex32(b.Preimage.ConfigHash) ||
		ev.ToplocCommitment != hex32(b.Preimage.ToplocCommitment) || ev.InputHash != hex32(protocol.Keccak256(b.Request.Body)) ||
		str("responseBodyHash") != hex32(protocol.Keccak256(b.Response)):
		return "", Evidence{}, errors.New("evidence does not bind the authenticated bundle")
	case g.Status == verifier.Fail && v != Fail:
		return "", Evidence{}, errors.New("gate FAIL must yield FAIL")
	case len(ev.Record) > 0 && ev.RecordHash != hex32(protocol.Keccak256(ev.Record)):
		return "", Evidence{}, errors.New("comparison record hash mismatch")
	}
	return v, ev, nil
}

// canonicalEvidence accepts only the exact canonical encoding: sorted keys,
// no whitespace, no duplicates, integers only.
func canonicalEvidence(raw []byte) (map[string]any, error) {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var v map[string]any
	if err := d.Decode(&v); err != nil {
		return nil, fmt.Errorf("evidence: %w", err)
	}
	if _, err := d.Token(); err != io.EOF {
		return nil, errors.New("evidence: trailing data")
	}
	var buf bytes.Buffer
	e := json.NewEncoder(&buf)
	e.SetEscapeHTML(false)
	if err := e.Encode(v); err != nil || !bytes.Equal(bytes.TrimSuffix(buf.Bytes(), []byte("\n")), raw) {
		return nil, errors.New("evidence is not canonical")
	}
	return v, nil
}
