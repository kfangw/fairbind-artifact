package refsource

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	"example.org/fairbind/runtime/dataworker"
)

// Retriever supplies the raw object for one source at one reference time.
type Retriever interface {
	Obtain(ctx context.Context, src Source, referenceTime uint64) (*RawObject, error)
}

// Sink retains raw objects. It is called before the object is verified or
// parsed, so failed and malformed responses are kept as well.
type Sink interface {
	Put(*RawObject) (string, error)
}

// Record describes the outcome for one source of one Retrieve call.
type Record struct {
	SourceID    string                  `json:"source_id"`
	ObjectID    string                  `json:"object_id,omitempty"`
	Observation *dataworker.Observation `json:"observation,omitempty"`
	Error       string                  `json:"error,omitempty"`
}

// Provider implements dataworker.ReferenceProvider over a Registry and a
// Retriever. Live and replay modes differ only in the Retriever; parsing and
// normalization always start from a raw object.
type Provider struct {
	Registry  Registry
	Retriever Retriever
	Sink      Sink
	Verify    VerifyOptions
	// AllowPartial returns the observations that succeeded when some sources
	// fail, leaving the quorum decision to the comparison. By default any
	// failure is an error, which the worker reports as INCONCLUSIVE.
	AllowPartial bool
	// OnRecord, if set, receives one record per requested source.
	OnRecord func(Record)
}

var _ dataworker.ReferenceProvider = Provider{}

func (p Provider) Retrieve(ctx context.Context, set dataworker.SourceSet, referenceTime uint64) ([]dataworker.Observation, error) {
	if p.Retriever == nil || len(set.Sources) == 0 {
		return nil, errors.New("reference provider not configured")
	}
	var out []dataworker.Observation
	var errs []error
	for _, id := range set.Sources {
		rec := Record{SourceID: id}
		obs, e := p.one(ctx, id, referenceTime, &rec)
		if e != nil {
			rec.Error = e.Error()
			errs = append(errs, fmt.Errorf("%s: %w", id, e))
		} else {
			rec.Observation = &obs
			out = append(out, obs)
		}
		if p.OnRecord != nil {
			p.OnRecord(rec)
		}
	}
	if len(errs) > 0 && (!p.AllowPartial || len(out) == 0) {
		return nil, errors.Join(errs...)
	}
	return out, nil
}

func (p Provider) one(ctx context.Context, id string, t uint64, rec *Record) (dataworker.Observation, error) {
	src, ok := p.Registry[id]
	if !ok {
		return dataworker.Observation{}, errors.New("source not registered")
	}
	obj, e := p.Retriever.Obtain(ctx, src, t)
	if e != nil {
		return dataworker.Observation{}, e
	}
	if obj.SourceID != id || obj.URL != src.URL() {
		return dataworker.Observation{}, errors.New("raw object does not belong to this source")
	}
	if p.Sink != nil {
		oid, e := p.Sink.Put(obj)
		if e != nil {
			return dataworker.Observation{}, fmt.Errorf("retaining raw object: %w", e)
		}
		rec.ObjectID = oid
	} else if oid, e := obj.ObjectID(); e == nil {
		rec.ObjectID = oid
	}
	resp, e := Verify(obj, p.Verify)
	if e != nil {
		return dataworker.Observation{}, e
	}
	return src.Parse(resp)
}

// Live captures each source now. The reference time is not used to select
// data: a live ticker reports the current quote, and the comparison rejects
// observations outside the policy's skew.
type Live struct{ Capturer Capturer }

func (l Live) Obtain(ctx context.Context, src Source, _ uint64) (*RawObject, error) {
	return l.Capturer.Capture(ctx, src.ID(), src.URL())
}

// Replay serves saved raw objects. For each source it picks the object whose
// server Date header is closest to the reference time, breaking ties by object
// ID, so the result depends only on the stored objects.
type Replay struct {
	Objects []*RawObject
	Verify  VerifyOptions
}

// LoadReplay reads every *.json file in dir as a raw object.
func LoadReplay(dir string, opt VerifyOptions) (Replay, error) {
	names, e := filepath.Glob(filepath.Join(dir, "*.json"))
	if e != nil {
		return Replay{}, e
	}
	sort.Strings(names)
	r := Replay{Verify: opt}
	for _, n := range names {
		o, e := Load(n)
		if e != nil {
			return Replay{}, fmt.Errorf("%s: %w", filepath.Base(n), e)
		}
		r.Objects = append(r.Objects, o)
	}
	return r, nil
}

func (r Replay) Obtain(_ context.Context, src Source, t uint64) (*RawObject, error) {
	var best *RawObject
	var bestDist uint64
	var bestID string
	for _, o := range r.Objects {
		if o.SourceID != src.ID() {
			continue
		}
		resp, e := Verify(o, r.Verify)
		if e != nil {
			continue
		}
		d := uint64(resp.Date.Unix())
		if d > t {
			d -= t
		} else {
			d = t - d
		}
		id, _ := o.ObjectID()
		if best == nil || d < bestDist || (d == bestDist && id < bestID) {
			best, bestDist, bestID = o, d, id
		}
	}
	if best == nil {
		return nil, errors.New("no replay object for source")
	}
	return best, nil
}

// DirSink writes each object to Dir as <object id>.json. Existing files with the
// same name are left unchanged, since the name is the content hash.
type DirSink struct {
	Dir string
	mu  sync.Mutex
}

func (s *DirSink) Put(o *RawObject) (string, error) {
	b, e := json.MarshalIndent(o, "", "  ")
	if e != nil {
		return "", e
	}
	id, e := o.ObjectID()
	if e != nil {
		return "", e
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if e := os.MkdirAll(s.Dir, 0o755); e != nil {
		return "", e
	}
	name := filepath.Join(s.Dir, sanitize(o.SourceID)+"-"+id[:16]+".json")
	f, e := os.OpenFile(name, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if errors.Is(e, os.ErrExist) {
		return id, nil
	}
	if e != nil {
		return "", e
	}
	_, e = f.Write(append(b, '\n'))
	if e2 := f.Close(); e == nil {
		e = e2
	}
	return id, e
}

func sanitize(s string) string {
	return strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '.' {
			return r
		}
		return '_'
	}, s)
}
