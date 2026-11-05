package refsource

import (
	"context"
	"encoding/json"
	"errors"

	"example.org/fairbind/runtime/dataworker"
)

var (
	_ dataworker.ReplaySource  = Provider{}
	_ dataworker.ReplayDecoder = Decoder{}
)

// Collect implements dataworker.ReplaySource. It obtains one raw object per
// source and returns every object it obtained, in source-set order, as the
// compact JSON encoding whose SHA-256 is the object ID. It does not parse the
// objects: observations are derived later by Decoder, the same path a second
// verifier uses. A source whose object cannot be obtained is listed as
// unavailable; the comparison then applies the quorum.
func (p Provider) Collect(ctx context.Context, set dataworker.SourceSet, referenceTime uint64) (dataworker.Collection, error) {
	if p.Retriever == nil || len(set.Sources) == 0 {
		return dataworker.Collection{}, errors.New("reference provider not configured")
	}
	var c dataworker.Collection
	for _, id := range set.Sources {
		fail := func(reason string) {
			c.Unavailable = append(c.Unavailable, dataworker.Unavailable{Source: id, Reason: reason})
		}
		src, ok := p.Registry[id]
		if !ok {
			fail("source not registered")
			continue
		}
		obj, e := p.Retriever.Obtain(ctx, src, referenceTime)
		if e != nil {
			fail(e.Error())
			continue
		}
		if obj.SourceID != id || obj.URL != src.URL() {
			fail("raw object does not belong to this source")
			continue
		}
		if p.Sink != nil {
			if _, e := p.Sink.Put(obj); e != nil {
				fail("retaining raw object: " + e.Error())
				continue
			}
		}
		raw, e := json.Marshal(obj)
		if e != nil {
			fail("encoding raw object")
			continue
		}
		c.Objects = append(c.Objects, dataworker.ReplayObject{Source: id, ObjectID: SHA256Hex(raw), Raw: raw})
	}
	return c, nil
}

// Decoder implements dataworker.ReplayDecoder over a Registry. It checks the
// object identifier, decodes the raw object strictly, requires it to belong to
// the registered endpoint of its source, verifies it and parses it.
type Decoder struct {
	Registry Registry
	Verify   VerifyOptions
}

func (d Decoder) Decode(r dataworker.ReplayObject) (dataworker.Observation, error) {
	if SHA256Hex(r.Raw) != r.ObjectID {
		return dataworker.Observation{}, errors.New("object identifier mismatch")
	}
	src, ok := d.Registry[r.Source]
	if !ok {
		return dataworker.Observation{}, errors.New("source not registered")
	}
	obj, e := Decode(r.Raw)
	if e != nil {
		return dataworker.Observation{}, e
	}
	if obj.SourceID != r.Source || obj.URL != src.URL() {
		return dataworker.Observation{}, errors.New("raw object does not belong to this source")
	}
	resp, e := Verify(obj, d.Verify)
	if e != nil {
		return dataworker.Observation{}, e
	}
	return src.Parse(resp)
}
