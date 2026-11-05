package c1collect

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/dataworker"
	"example.org/fairbind/runtime/dataworker/refsource"
	"example.org/fairbind/runtime/verifier"
)

// JudgmentFormat identifies the per-instance judgment record.
const JudgmentFormat = "fairbind/experimental/c1-judgment/v1"

// Plan is the seeded schedule of one verifier instance in one cell. The
// controller derives it from the base seed and the grid time.
type Plan struct {
	ReferenceTime uint64   `json:"reference_time"`
	Instance      int      `json:"instance"`
	StartUnixMs   int64    `json:"start_unix_ms"`
	Order         []string `json:"order"`
	Skip          []string `json:"skip"`
}

// Judgment is one instance's decision on one response, with the full pipeline
// evidence (which carries the raw reference objects it used).
type Judgment struct {
	ResponseID     string          `json:"response_id"`
	Response       []byte          `json:"response"`
	Verdict        string          `json:"verdict"`
	Reason         string          `json:"reason"`
	Error          string          `json:"error,omitempty"`
	EvaluateWallNs int64           `json:"evaluate_wall_ns"`
	EvidenceHash   string          `json:"evidence_keccak256,omitempty"`
	Evidence       json.RawMessage `json:"evidence,omitempty"`
}

// Record is what an instance returns for one cell.
type Record struct {
	Format             string     `json:"format"`
	Plan               Plan       `json:"plan"`
	PolicyFrameHash    string     `json:"policy_frame_sha256"`
	PolicyHash         string     `json:"policy_keccak256"`
	SourceSetHash      string     `json:"source_set_keccak256"`
	Captures           []Summary  `json:"captures"`
	RefsFinishedUnixMs int64      `json:"refs_finished_unix_ms"`
	CasesReceivedMs    int64      `json:"cases_received_unix_ms"`
	JudgedUnixMs       int64      `json:"judged_unix_ms"`
	Judgments          []Judgment `json:"judgments"`
}

// SleepUntil waits for the wall-clock time ms or for ctx.
func SleepUntil(ctx context.Context, ms int64) error {
	d := time.Until(time.UnixMilli(ms))
	if d <= 0 {
		return nil
	}
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-t.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

// CaptureReferences captures the plan's references in order, one after the
// other, starting at the plan's start time. Values are not reported.
func CaptureReferences(ctx context.Context, p Plan, c Capturer, wait func(context.Context, int64) error) ([]Summary, map[string]*refsource.RawObject, int64, error) {
	reg := refsource.DefaultRegistry()
	skip := map[string]bool{}
	for _, s := range p.Skip {
		skip[s] = true
	}
	if e := wait(ctx, p.StartUnixMs); e != nil {
		return nil, nil, 0, e
	}
	objs := map[string]*refsource.RawObject{}
	var out []Summary
	for _, id := range p.Order {
		src, ok := reg[id]
		if !ok {
			return nil, nil, 0, fmt.Errorf("source %q is not a registered reference", id)
		}
		if skip[id] {
			out = append(out, Summary{SourceID: id, URL: src.URL(), Stage: StageSkipped})
			continue
		}
		s, obj := c.One(ctx, id, src.URL(), nil)
		if obj != nil {
			objs[id] = obj
		}
		out = append(out, s)
	}
	return out, objs, time.Now().UnixMilli(), nil
}

// fixed serves exactly the objects this instance captured in this cell.
type fixed struct {
	objs    map[string]*refsource.RawObject
	reasons map[string]string
}

func (f fixed) Obtain(_ context.Context, src refsource.Source, _ uint64) (*refsource.RawObject, error) {
	if o, ok := f.objs[src.ID()]; ok {
		return o, nil
	}
	if r, ok := f.reasons[src.ID()]; ok {
		return nil, errors.New(r)
	}
	return nil, errors.New("not captured")
}

// Judge evaluates each case through dataworker.Pipeline against the objects
// the instance captured. The same objects serve every response of the cell.
func Judge(ctx context.Context, p Plan, captures []Summary, objs map[string]*refsource.RawObject, cases []Case, sig verifier.CastVerifier, opt refsource.VerifyOptions) []Judgment {
	reasons := map[string]string{}
	for _, s := range captures {
		if s.Stage != StageOK && s.Stage != StageInvalid {
			reasons[s.SourceID] = "capture " + s.Stage
		}
	}
	reg := refsource.DefaultRegistry()
	pipe := dataworker.Pipeline{
		Signature:  sig,
		References: refsource.Provider{Registry: reg, Retriever: fixed{objs, reasons}, Verify: opt},
		Decoder:    refsource.Decoder{Registry: reg, Verify: opt},
	}
	pol := PolicyAt(p.ReferenceTime)
	prof := dataworker.Profile{Policy: pol, Sources: dataworker.SourceSet{Sources: pol.Sources}}
	out := make([]Judgment, 0, len(cases))
	for _, c := range cases {
		j := Judgment{ResponseID: c.ResponseID, Response: c.Bundle.Response}
		prof.Snapshot = c.Snapshot
		if c.Bundle.Preimage.ReferenceTime != p.ReferenceTime {
			j.Error = "case reference time differs from the cell"
			out = append(out, j)
			continue
		}
		t0 := time.Now()
		v, ev, err := pipe.Evaluate(ctx, c.Bundle, prof)
		j.EvaluateWallNs = time.Since(t0).Nanoseconds()
		if err != nil {
			j.Error = err.Error()
			out = append(out, j)
			continue
		}
		raw, h, err := ev.Encode()
		if err != nil {
			j.Error = err.Error()
			out = append(out, j)
			continue
		}
		j.Verdict, j.Reason, j.Evidence, j.EvidenceHash = string(v), ev.Reason, raw, fmt.Sprintf("0x%x", h)
		out = append(out, j)
	}
	return out
}

// PolicyHashes returns the per-judgment policy and source set hashes.
func PolicyHashes(referenceTime uint64) (string, string, error) {
	p := PolicyAt(referenceTime)
	ph, e := dataworker.ObjectHash(p)
	if e != nil {
		return "", "", e
	}
	sh, e := dataworker.ObjectHash(dataworker.SourceSet{Sources: p.Sources})
	if e != nil {
		return "", "", e
	}
	return hexBytes(ph), hexBytes(sh), nil
}

func hexBytes(b protocol.Bytes32) string { return fmt.Sprintf("0x%x", b) }

// Rederive re-derives every judgment of a record from its evidence and the
// stored response bytes. It returns the number of judgments checked.
func Rederive(r Record, opt refsource.VerifyOptions) (int, error) {
	if r.Format != JudgmentFormat {
		return 0, errors.New("unsupported judgment format")
	}
	dec := refsource.Decoder{Registry: refsource.DefaultRegistry(), Verify: opt}
	for i, j := range r.Judgments {
		if j.Error != "" {
			return i, fmt.Errorf("judgment %s carries an error: %s", j.ResponseID, j.Error)
		}
		var ev dataworker.Evidence
		d := json.NewDecoder(bytes.NewReader(j.Evidence))
		d.DisallowUnknownFields()
		if e := d.Decode(&ev); e != nil {
			return i, fmt.Errorf("judgment %s: evidence: %w", j.ResponseID, e)
		}
		_, h, e := ev.Encode()
		if e != nil || hexBytes(h) != j.EvidenceHash {
			return i, fmt.Errorf("judgment %s: evidence hash", j.ResponseID)
		}
		v, e := dataworker.Rederive(ev, j.Response, dec)
		if e != nil {
			return i, fmt.Errorf("judgment %s: %w", j.ResponseID, e)
		}
		if string(v) != j.Verdict || ev.Reason != j.Reason || ev.ReferenceTime != r.Plan.ReferenceTime {
			return i, fmt.Errorf("judgment %s: recorded decision differs from evidence", j.ResponseID)
		}
	}
	return len(r.Judgments), nil
}
