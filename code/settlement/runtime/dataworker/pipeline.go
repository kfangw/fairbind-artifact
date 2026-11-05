package dataworker

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"regexp"
	"sort"
	"strings"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/verifier"
)

// Verdict is the three-way result of the data predicate pipeline.
type Verdict string

const (
	Pass         Verdict = "PASS"
	Fail         Verdict = "FAIL"
	Inconclusive Verdict = "INCONCLUSIVE"
)

// ErrNotJudged is returned when the bundle does not pass the input gate with
// READY or FAIL. Such a bundle is neither PASS, FAIL nor INCONCLUSIVE: the
// verifier does not judge a receipt that does not authenticate.
var ErrNotJudged = errors.New("bundle did not pass the input gate; not judged")

// Object formats of the pipeline evidence. They are experimental layouts bound
// to PolicyID, not normative protocol encodings.
const (
	EvidenceFormat     = "fairbind/experimental/data-evidence/v1"
	ReferenceSetFormat = "fairbind/experimental/data-reference-set/v1"
	ComparisonFormat   = "fairbind/experimental/data-comparison/v1"
)

// Limits on the reference collection.
const (
	MaxReferenceObjects = 64
	MaxReplayObjectSize = 4 << 20
)

// ReplayObject is one raw reference response kept verbatim. ObjectID is the
// lowercase hex SHA-256 of Raw. Raw is encoded as base64 in evidence.
type ReplayObject struct {
	Source   string `json:"source"`
	ObjectID string `json:"objectId"`
	Raw      []byte `json:"raw"`
}

// Unavailable records a source that yielded no usable observation.
type Unavailable struct {
	Source string `json:"source"`
	Reason string `json:"reason"`
}

// Collection is what a ReplaySource retrieved for one reference time. Objects
// holds every raw object obtained, including ones that later fail to decode.
type Collection struct {
	Objects     []ReplayObject
	Unavailable []Unavailable
}

// ReplaySource is trusted operator code that retrieves raw reference objects
// for the committed source set. It never receives seller-supplied data. A
// source that cannot be retrieved is listed in Unavailable; an error means the
// source as a whole is not configured or failed before any retrieval.
type ReplaySource interface {
	Collect(ctx context.Context, set SourceSet, referenceTime uint64) (Collection, error)
}

// ReplayDecoder derives an observation from one raw object. It is the only
// path from raw bytes to observations, both when evaluating and when a second
// verifier re-derives a verdict from evidence.
type ReplayDecoder interface {
	Decode(ReplayObject) (Observation, error)
}

// Profile is the trusted input of one evaluation: the finalized snapshot and
// the manifests the operator holds for its profile. The manifests are used only
// if their hashes equal the commitment the seller signed.
type Profile struct {
	Snapshot verifier.Snapshot
	Policy   Policy
	Sources  SourceSet
}

// Pipeline chains the input gate, reference collection and the exact decimal
// median comparison.
type Pipeline struct {
	Signature  verifier.CastVerifier
	References ReplaySource
	Decoder    ReplayDecoder
	// Timeout bounds reference collection. Zero means 15 seconds.
	Timeout time.Duration
}

// ReferenceSet is the retained reference material. Its canonical hash is the
// reference set hash (the envelope's referenceResponsesHash).
type ReferenceSet struct {
	Format        string         `json:"format"`
	ReferenceTime uint64         `json:"referenceTime"`
	SourceSetHash string         `json:"sourceSetHash"`
	Objects       []ReplayObject `json:"objects"`
	Unavailable   []Unavailable  `json:"unavailable"`
}

// Comparison is the decision record. Observations are derived from the
// reference set objects by the decoder; Excluded lists observations that did
// not count toward the quorum and why.
type Comparison struct {
	Format              string            `json:"format"`
	PolicyID            string            `json:"policyId"`
	TolerancePolicyHash string            `json:"tolerancePolicyHash"`
	ReferenceSetHash    string            `json:"referenceSetHash"`
	Observations        []Observation     `json:"observations"`
	Excluded            []Unavailable     `json:"excluded"`
	Sources             []string          `json:"sources"`
	Medians             map[string]string `json:"medians"`
	Verdict             string            `json:"verdict"`
	Reason              string            `json:"reason"`
}

// Evidence is the full pipeline output. With the response bytes and a
// ReplayDecoder it is sufficient to re-derive the verdict (see Rederive).
type Evidence struct {
	Format              string       `json:"format"`
	PolicyID            string       `json:"policyId"`
	PredicateID         string       `json:"predicateId"`
	Nonce               string       `json:"nonce"`
	ResponseHash        string       `json:"responseHash"`
	PredicateCommitment string       `json:"predicateCommitment"`
	ReferenceTime       uint64       `json:"referenceTime"`
	SourceSetHash       string       `json:"sourceSetHash"`
	TolerancePolicyHash string       `json:"tolerancePolicyHash"`
	Gate                string       `json:"gate"`
	SourceSet           SourceSet    `json:"sourceSet"`
	Policy              Policy       `json:"policy"`
	References          ReferenceSet `json:"references"`
	ReferenceSetHash    string       `json:"referenceSetHash"`
	Comparison          Comparison   `json:"comparison"`
	ComparisonHash      string       `json:"comparisonHash"`
	Verdict             string       `json:"verdict"`
	Reason              string       `json:"reason"`
}

func hex32(h protocol.Bytes32) string { return fmt.Sprintf("0x%x", h) }

// Encode returns the canonical bytes of the evidence and their Keccak-256.
func (e Evidence) Encode() ([]byte, protocol.Bytes32, error) {
	raw, err := CanonicalObject(e)
	if err != nil {
		return nil, protocol.Bytes32{}, err
	}
	return raw, protocol.Keccak256(raw), nil
}

// Evaluate runs gate -> reference collection -> comparison. It returns
// ErrNotJudged (wrapped with the gate reason) when the bundle does not
// authenticate. Otherwise the verdict and evidence are always set together.
func (p Pipeline) Evaluate(ctx context.Context, b verifier.Bundle, prof Profile) (Verdict, Evidence, error) {
	s := prof.Snapshot
	g := verifier.Check(ctx, s, b, p.Signature)
	if g.Status != verifier.Ready && g.Status != verifier.Fail {
		return "", Evidence{}, fmt.Errorf("%w: %s", ErrNotJudged, g.Reason)
	}
	ev := Evidence{
		Format: EvidenceFormat, PolicyID: hex32(PolicyID), PredicateID: hex32(s.PredicateID), Nonce: hex32(s.Nonce),
		ResponseHash: hex32(b.Receipt.ResponseHash), PredicateCommitment: hex32(b.Receipt.PredicateCommitment),
		ReferenceTime: b.Preimage.ReferenceTime, SourceSetHash: hex32(b.Preimage.SourceSetHash),
		TolerancePolicyHash: hex32(b.Preimage.TolerancePolicyHash), Gate: g.Reason,
		SourceSet: normalizeSet(prof.Sources), Policy: normalizePolicy(prof.Policy),
	}
	refs := ReferenceSet{Format: ReferenceSetFormat, ReferenceTime: ev.ReferenceTime, SourceSetHash: ev.SourceSetHash, Objects: []ReplayObject{}, Unavailable: []Unavailable{}}
	decide := func(v Verdict, reason string, c *Comparison) (Verdict, Evidence, error) {
		if c == nil {
			c = &Comparison{Verdict: string(v), Reason: reason}
		}
		out, err := finish(ev, refs, *c)
		if err != nil {
			return "", Evidence{}, err
		}
		return Verdict(out.Verdict), out, nil
	}
	// A seller-signed receipt with an empty commitment, or an opened commitment
	// that contradicts the registered claims, is a seller violation.
	if g.Status == verifier.Fail {
		return decide(Fail, g.Reason, nil)
	}
	if s.ClassID != 1 || s.PredicateID != PolicyID {
		return decide(Inconclusive, "unsupported_predicate", nil)
	}
	// The operator's manifests are usable only when they are the ones the
	// seller committed to; otherwise the verifier lacks the committed input.
	if h, err := ObjectHash(prof.Policy); err != nil || h != b.Preimage.TolerancePolicyHash {
		return decide(Inconclusive, "tolerance_policy_unavailable", nil)
	}
	if h, err := ObjectHash(prof.Sources); err != nil || h != b.Preimage.SourceSetHash {
		return decide(Inconclusive, "source_set_unavailable", nil)
	}
	pol := prof.Policy
	if !validPolicy(pol, prof.Sources) {
		return decide(Inconclusive, "policy_configuration", nil)
	}
	// The policy fixes the reference time; a signed preimage that names another
	// time contradicts the seller's own registered policy.
	if pol.ReferenceTime != b.Preimage.ReferenceTime {
		return decide(Fail, "reference_time_contradicts_policy", nil)
	}
	if p.References == nil || p.Decoder == nil {
		return decide(Inconclusive, "references_unavailable", nil)
	}
	timeout := p.Timeout
	if timeout == 0 {
		timeout = 15 * time.Second
	}
	cctx, cancel := context.WithTimeout(ctx, timeout)
	col, err := p.References.Collect(cctx, prof.Sources, pol.ReferenceTime)
	cancel()
	if err != nil {
		refs.Unavailable = append(refs.Unavailable, Unavailable{Source: "*", Reason: sanitize(err.Error())})
		return decide(Inconclusive, "references_unavailable", nil)
	}
	if refs, err = checkCollection(col, refs, prof.Sources); err != nil {
		return decide(Inconclusive, "references_unavailable", nil)
	}
	c := derive(pol, b.Response, refs, p.Decoder)
	return decide(Verdict(c.Verdict), c.Reason, &c)
}

func checkCollection(col Collection, refs ReferenceSet, set SourceSet) (ReferenceSet, error) {
	if len(col.Objects) > MaxReferenceObjects || len(col.Unavailable) > MaxReferenceObjects {
		return refs, errors.New("too many reference objects")
	}
	allowed := map[string]bool{}
	for _, s := range set.Sources {
		allowed[s] = true
	}
	for _, o := range col.Objects {
		if !allowed[o.Source] || len(o.Raw) > MaxReplayObjectSize || o.ObjectID != sha256Hex(o.Raw) {
			return refs, errors.New("reference object outside the source set or with a wrong identifier")
		}
		refs.Objects = append(refs.Objects, ReplayObject{Source: o.Source, ObjectID: o.ObjectID, Raw: append([]byte(nil), o.Raw...)})
	}
	for _, u := range col.Unavailable {
		refs.Unavailable = append(refs.Unavailable, Unavailable{Source: sanitize(u.Source), Reason: sanitize(u.Reason)})
	}
	return refs, nil
}

// derive decodes every object in refs and applies the committed comparison.
func derive(pol Policy, response []byte, refs ReferenceSet, dec ReplayDecoder) Comparison {
	var obs []Observation
	var excluded []Unavailable
	for _, o := range refs.Objects {
		ob, err := dec.Decode(o)
		if err == nil && ob.Source != o.Source {
			err = errors.New("observation source differs from object source")
		}
		if err != nil {
			excluded = append(excluded, Unavailable{Source: o.Source, Reason: sanitize("decode: " + err.Error())})
			continue
		}
		obs = append(obs, ob)
	}
	return Compare(pol, response, obs, excluded)
}

func finish(ev Evidence, refs ReferenceSet, c Comparison) (Evidence, error) {
	rh, err := ObjectHash(refs)
	if err != nil {
		return Evidence{}, fmt.Errorf("reference set encoding: %w", err)
	}
	c.Format, c.PolicyID, c.TolerancePolicyHash, c.ReferenceSetHash = ComparisonFormat, ev.PolicyID, ev.TolerancePolicyHash, hex32(rh)
	c = normalizeComparison(c)
	ch, err := ObjectHash(c)
	if err != nil {
		return Evidence{}, fmt.Errorf("comparison encoding: %w", err)
	}
	ev.References, ev.ReferenceSetHash, ev.Comparison, ev.ComparisonHash = refs, hex32(rh), c, hex32(ch)
	ev.Verdict, ev.Reason = c.Verdict, c.Reason
	if _, _, err = ev.Encode(); err != nil {
		return Evidence{}, fmt.Errorf("evidence encoding: %w", err)
	}
	return ev, nil
}

// Rederive recomputes the verdict from evidence, the exact response bytes and
// a decoder, as a second verifier would. It checks the response hash, the
// policy and source set hashes, the reference set hash, and that decoding and
// comparison reproduce the recorded comparison byte for byte.
func Rederive(ev Evidence, response []byte, dec ReplayDecoder) (Verdict, error) {
	if ev.Format != EvidenceFormat || ev.PolicyID != hex32(PolicyID) {
		return "", errors.New("unsupported evidence format")
	}
	if hex32(protocol.ResponseHash(response)) != ev.ResponseHash {
		return "", errors.New("response does not match evidence")
	}
	rh, err := ObjectHash(ev.References)
	if err != nil || hex32(rh) != ev.ReferenceSetHash {
		return "", errors.New("reference set hash mismatch")
	}
	want, err := CanonicalObject(ev.Comparison)
	if err != nil || hex32(protocol.Keccak256(want)) != ev.ComparisonHash {
		return "", errors.New("comparison hash mismatch")
	}
	var c Comparison
	if len(ev.References.Objects) == 0 && len(ev.Comparison.Observations) == 0 && len(ev.Comparison.Excluded) == 0 {
		// The pipeline stopped before comparing (gate FAIL, unavailable
		// manifests or references). The recorded reason is the decision; it
		// can never be PASS, which requires a reference quorum.
		if ev.Comparison.Verdict == string(Pass) {
			return "", errors.New("PASS without references")
		}
		c = ev.Comparison
	} else {
		ph, e1 := ObjectHash(ev.Policy)
		sh, e2 := ObjectHash(ev.SourceSet)
		if e1 != nil || e2 != nil || hex32(ph) != ev.TolerancePolicyHash || hex32(sh) != ev.SourceSetHash {
			return "", errors.New("manifest hash mismatch")
		}
		c = derive(ev.Policy, response, ev.References, dec)
		c.Format, c.PolicyID, c.TolerancePolicyHash, c.ReferenceSetHash = ComparisonFormat, ev.PolicyID, ev.TolerancePolicyHash, ev.ReferenceSetHash
		c = normalizeComparison(c)
	}
	got, err := CanonicalObject(c)
	if err != nil || !bytes.Equal(got, want) {
		return "", errors.New("re-derived comparison differs from evidence")
	}
	if c.Verdict != ev.Verdict {
		return "", errors.New("verdict differs from comparison")
	}
	return Verdict(c.Verdict), nil
}

func validPolicy(p Policy, set SourceSet) bool {
	if len(p.Sources) == 0 || len(p.Sources) > 64 || len(p.Sources) != len(set.Sources) || len(p.Fields) == 0 || len(p.Fields) > 64 || p.Quorum == 0 || p.Quorum > uint64(len(p.Sources)) {
		return false
	}
	seen := map[string]bool{}
	for i, id := range p.Sources {
		if id == "" || seen[id] || id != set.Sources[i] {
			return false
		}
		seen[id] = true
	}
	for _, f := range p.Fields {
		for _, v := range []string{f.Absolute, f.Relative, f.Spread} {
			r, ok := parseDecimal(v)
			if !ok || r.Sign() < 0 {
				return false
			}
		}
	}
	return true
}

var decimalRE = regexp.MustCompile(`^-?[0-9]+(\.[0-9]+)?$`)

func parseDecimal(s string) (*big.Rat, bool) {
	if len(s) > 128 || !decimalRE.MatchString(s) {
		return nil, false
	}
	return new(big.Rat).SetString(s)
}

// FormatDecimal writes r as an exact plain decimal. Medians of decimal inputs
// always have a terminating expansion; any other value is written as a/b.
func FormatDecimal(r *big.Rat) string {
	d := new(big.Int).Set(r.Denom())
	two, five, zero := big.NewInt(2), big.NewInt(5), new(big.Int)
	n2, n5 := 0, 0
	m := new(big.Int)
	for m.Mod(d, two).Cmp(zero) == 0 {
		d.Div(d, two)
		n2++
	}
	for m.Mod(d, five).Cmp(zero) == 0 {
		d.Div(d, five)
		n5++
	}
	if d.Cmp(big.NewInt(1)) != 0 {
		return r.RatString()
	}
	n := n2
	if n5 > n {
		n = n5
	}
	return r.FloatString(n)
}

// Compare applies the committed decimal-median rule. All selected fields are
// required. At least quorum distinct policy sources must have an observation
// within max_skew of the reference time, with every selected field present as
// a decimal in the committed unit. Those sources must agree within each
// reference_spread. The response must then lie within absolute + relative *
// |median| of the exact median for every field.
//
// INCONCLUSIVE covers only the reference side: invalid numeric policy,
// duplicate or unregistered sources, quorum not reached, or disagreeing
// references. Once the references establish the medians, a response that is
// not a JSON object, lacks a selected field, or carries a non-decimal value is
// FAIL, since the seller signed those bytes.
func Compare(p Policy, response []byte, obs []Observation, excluded []Unavailable) Comparison {
	c := Comparison{Observations: obs, Excluded: excluded}
	out := func(v Verdict, reason string) Comparison {
		c.Verdict, c.Reason = string(v), reason
		return c
	}
	type lim struct{ abs, rel, spread *big.Rat }
	limits := map[string]lim{}
	for k, f := range p.Fields {
		a, ok1 := parseDecimal(f.Absolute)
		r, ok2 := parseDecimal(f.Relative)
		s, ok3 := parseDecimal(f.Spread)
		if !ok1 || !ok2 || !ok3 || a.Sign() < 0 || r.Sign() < 0 || s.Sign() < 0 {
			return out(Inconclusive, "invalid numeric policy")
		}
		limits[k] = lim{a, r, s}
	}
	allowed := map[string]bool{}
	for _, s := range p.Sources {
		allowed[s] = true
	}
	seen := map[string]bool{}
	type row struct {
		source string
		values map[string]*big.Rat
	}
	var valid []row
	for _, o := range obs {
		if seen[o.Source] {
			return out(Inconclusive, "duplicate source")
		}
		seen[o.Source] = true
		if !allowed[o.Source] {
			return out(Inconclusive, "unregistered source")
		}
		skew := o.ObservedAt - p.ReferenceTime
		if o.ObservedAt < p.ReferenceTime {
			skew = p.ReferenceTime - o.ObservedAt
		}
		if skew > p.MaxSkew {
			c.Excluded = append(c.Excluded, Unavailable{o.Source, "outside max_skew"})
			continue
		}
		vals := map[string]*big.Rat{}
		reason := ""
		for k, f := range p.Fields {
			v, ok := parseDecimal(o.Values[k])
			if !ok {
				reason = "field " + k + " missing or not decimal"
				break
			}
			if o.Units[k] != f.Unit {
				reason = "field " + k + " unit mismatch"
				break
			}
			vals[k] = v
		}
		if reason != "" {
			c.Excluded = append(c.Excluded, Unavailable{o.Source, sanitize(reason)})
			continue
		}
		valid = append(valid, row{o.Source, vals})
	}
	if uint64(len(valid)) < p.Quorum {
		return out(Inconclusive, "reference quorum unavailable")
	}
	medians := map[string]*big.Rat{}
	c.Medians = map[string]string{}
	for k := range p.Fields {
		vs := make([]*big.Rat, len(valid))
		for i, r := range valid {
			vs[i] = r.values[k]
		}
		sort.Slice(vs, func(i, j int) bool { return vs[i].Cmp(vs[j]) < 0 })
		if new(big.Rat).Sub(vs[len(vs)-1], vs[0]).Cmp(limits[k].spread) > 0 {
			c.Medians = nil
			return out(Inconclusive, "references disagree")
		}
		m := new(big.Rat).Add(vs[(len(vs)-1)/2], vs[len(vs)/2])
		m.Quo(m, big.NewRat(2, 1))
		medians[k] = m
		c.Medians[k] = FormatDecimal(m)
	}
	for _, r := range valid {
		c.Sources = append(c.Sources, r.source)
	}
	sort.Strings(c.Sources)
	body, err := strictObject(response)
	if err != nil {
		return out(Fail, "response is not a JSON object")
	}
	keys := make([]string, 0, len(medians))
	for k := range medians {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if _, ok := body[k]; !ok {
			return out(Fail, "required field absent")
		}
	}
	for _, k := range keys {
		var s string
		if json.Unmarshal(body[k], &s) != nil {
			return out(Fail, "response value is not a decimal string")
		}
		v, ok := parseDecimal(s)
		if !ok {
			return out(Fail, "response value is not a decimal string")
		}
		m := medians[k]
		bound := new(big.Rat).Mul(limits[k].rel, new(big.Rat).Abs(m))
		bound.Add(bound, limits[k].abs)
		if new(big.Rat).Abs(new(big.Rat).Sub(v, m)).Cmp(bound) > 0 {
			return out(Fail, "tolerance exceeded")
		}
	}
	return out(Pass, "all selected fields within tolerance")
}

// strictObject decodes one JSON object and rejects duplicate members and
// trailing data.
func strictObject(raw []byte) (map[string]json.RawMessage, error) {
	d := json.NewDecoder(bytes.NewReader(raw))
	t, err := d.Token()
	if err != nil || t != json.Delim('{') {
		return nil, errors.New("not an object")
	}
	out := map[string]json.RawMessage{}
	for d.More() {
		k, err := d.Token()
		if err != nil {
			return nil, err
		}
		key, _ := k.(string)
		if _, dup := out[key]; dup {
			return nil, errors.New("duplicate member")
		}
		var v json.RawMessage
		if err = d.Decode(&v); err != nil {
			return nil, err
		}
		out[key] = v
	}
	if _, err = d.Token(); err != nil {
		return nil, err
	}
	if _, err = d.Token(); err != io.EOF {
		return nil, errors.New("trailing data")
	}
	return out, nil
}

func sha256Hex(b []byte) string {
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}

// sanitize keeps reasons inside the canonical ASCII subset.
func sanitize(s string) string {
	s = strings.Map(func(r rune) rune {
		if r < 32 || r > 126 || r == '<' || r == '>' || r == '&' {
			return '_'
		}
		return r
	}, s)
	if len(s) > 200 {
		s = s[:200]
	}
	return s
}

func normalizeSet(s SourceSet) SourceSet {
	if s.Sources == nil {
		s.Sources = []string{}
	}
	return s
}

func normalizePolicy(p Policy) Policy {
	if p.Sources == nil {
		p.Sources = []string{}
	}
	if p.Fields == nil {
		p.Fields = map[string]Field{}
	}
	return p
}

func normalizeComparison(c Comparison) Comparison {
	if c.Observations == nil {
		c.Observations = []Observation{}
	}
	for i, o := range c.Observations {
		if o.Values == nil {
			o.Values = map[string]string{}
		}
		if o.Units == nil {
			o.Units = map[string]string{}
		}
		c.Observations[i] = o
	}
	if c.Excluded == nil {
		c.Excluded = []Unavailable{}
	}
	if c.Sources == nil {
		c.Sources = []string{}
	}
	if c.Medians == nil {
		c.Medians = map[string]string{}
	}
	return c
}
