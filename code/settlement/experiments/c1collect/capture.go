package c1collect

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"time"

	"example.org/fairbind/runtime/dataworker/refsource"
)

// Capture outcome stages. StageOK and StageInvalid mean that a complete HTTP
// response was recorded; StageResponse means response bytes arrived but the
// response was incomplete. The refsource stages connect and exchange mean no
// HTTP response arrived. StageSkipped marks a request not sent because of the
// 429 rule.
const (
	StageOK      = "ok"
	StageInvalid = "invalid"
	StageSkipped = "skipped_429"
)

// Summary describes one capture attempt. Value is filled only for callers on
// the controller side (seller captures and the adaptive generator); verifier
// instances never report values.
type Summary struct {
	SourceID   string `json:"source_id"`
	URL        string `json:"url,omitempty"`
	Stage      string `json:"stage"`
	HTTPStatus int    `json:"http_status,omitempty"`
	Error      string `json:"error,omitempty"`
	ObjectID   string `json:"object_id,omitempty"`
	ObjectFile string `json:"object_file,omitempty"`
	StartedMs  int64  `json:"started_unix_ms"`
	FinishedMs int64  `json:"finished_unix_ms"`
	Value      string `json:"value,omitempty"`
	DateUnix   int64  `json:"date_unix,omitempty"`
}

// GotResponse reports whether the attempt received any HTTP response bytes.
func (s Summary) GotResponse() bool {
	return s.Stage == StageOK || s.Stage == StageInvalid || s.Stage == refsource.StageResponse
}

// RequestLog appends one line per HTTP request before the request is sent, so
// that the requests of a cell that never completes can still be counted.
type RequestLog struct{ Path string }

func (l RequestLog) Note(role, source, url string) error {
	if l.Path == "" {
		return nil
	}
	f, e := os.OpenFile(l.Path, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o644)
	if e != nil {
		return e
	}
	line, _ := json.Marshal(map[string]any{"t_ms": time.Now().UnixMilli(), "role": role, "source": source, "url": url})
	_, e = f.Write(append(line, '\n'))
	if e2 := f.Close(); e == nil {
		e = e2
	}
	return e
}

// Capturer bundles what one capture needs.
type Capturer struct {
	Capture refsource.Capturer
	Verify  refsource.VerifyOptions
	Dir     string // raw objects are stored here (content addressed)
	Log     RequestLog
	Role    string
}

// ParseFunc turns a verified response into a value and its server time.
type ParseFunc func(*refsource.Response) (value string, date int64, err error)

// One performs one GET of url, stores the raw object when one was produced and
// classifies the outcome. obj is nil when no object was produced.
func (c Capturer) One(ctx context.Context, sourceID, url string, parse ParseFunc) (Summary, *refsource.RawObject) {
	s := Summary{SourceID: sourceID, URL: url}
	if e := c.Log.Note(c.Role, sourceID, url); e != nil {
		s.Stage, s.Error = refsource.StageConnect, "request log: "+e.Error()
		return s, nil
	}
	s.StartedMs = time.Now().UnixMilli()
	obj, e := c.Capture.Capture(ctx, sourceID, url)
	s.FinishedMs = time.Now().UnixMilli()
	if e != nil {
		var ce *refsource.CaptureError
		s.Stage = refsource.StageConnect
		if errors.As(e, &ce) {
			s.Stage = ce.Stage
		}
		s.Error = e.Error()
		return s, nil
	}
	s.StartedMs, s.FinishedMs = obj.StartedAtMs, obj.FinishedAtMs
	if c.Dir != "" {
		sink := &refsource.DirSink{Dir: c.Dir}
		id, e := sink.Put(obj)
		if e != nil {
			s.Stage, s.Error = StageInvalid, "storing raw object: "+e.Error()
			return s, obj
		}
		s.ObjectID = id
		s.ObjectFile = objectFileName(obj, id)
	} else if id, e := obj.ObjectID(); e == nil {
		s.ObjectID = id
	}
	resp, e := refsource.Verify(obj, c.Verify)
	if e != nil {
		s.Stage, s.Error = StageInvalid, "verify: "+e.Error()
		return s, obj
	}
	s.HTTPStatus = resp.Status
	if parse == nil {
		s.Stage = StageOK
		return s, obj
	}
	v, d, e := parse(resp)
	if e != nil {
		s.Stage, s.Error = StageInvalid, "parse: "+e.Error()
		return s, obj
	}
	s.Stage, s.Value, s.DateUnix = StageOK, v, d
	return s, obj
}

// objectFileName mirrors refsource.DirSink naming.
func objectFileName(o *refsource.RawObject, id string) string {
	safe := []rune(o.SourceID)
	for i, r := range safe {
		if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '.') {
			safe[i] = '_'
		}
	}
	return string(safe) + "-" + id[:16] + ".json"
}

// PriceParser parses a registered ticker source into its price field.
func PriceParser(src refsource.Source) ParseFunc {
	return func(r *refsource.Response) (string, int64, error) {
		o, e := src.Parse(r)
		if e != nil {
			return "", 0, e
		}
		return o.Values[FieldPrice], int64(o.ObservedAt), nil
	}
}

// TruthResult is the outcome of one truth lookup attempt (all pages).
type TruthResult struct {
	Format        string    `json:"format"`
	ReferenceTime uint64    `json:"reference_time"`
	OK            bool      `json:"ok"`
	Price         string    `json:"price,omitempty"`
	TradeMTS      int64     `json:"trade_mts,omitempty"`
	LatencyMs     int64     `json:"latency_ms,omitempty"`
	TradeIDs      []int64   `json:"trade_ids,omitempty"`
	TradesInWin   int       `json:"trades_in_window"`
	Pages         []Summary `json:"pages"`
	SplitQuery    bool      `json:"split_query"`
	MsTruncated   bool      `json:"millisecond_truncated,omitempty"`
	Failure       string    `json:"failure,omitempty"`
	LookupStarted int64     `json:"lookup_started_unix_ms"`
}

// MaxTruthPages bounds one lookup.
const MaxTruthPages = 50

// LookupTruth queries Bitfinex trades in reference_time +- 10 s, paging by
// moving end backwards when a page is full, and selects the trade(s) nearest
// to the reference time.
func (c Capturer) LookupTruth(ctx context.Context, referenceTime uint64) TruthResult {
	src := BitfinexTrades{}
	ref := int64(referenceTime) * 1000
	start, end := ref-TruthWindowMs, ref+TruthWindowMs
	res := TruthResult{Format: "fairbind/experimental/c1-truth/v1", ReferenceTime: referenceTime, LookupStarted: time.Now().UnixMilli(), Pages: []Summary{}}
	seen := map[int64]Trade{}
	for page := 0; ; page++ {
		if page >= MaxTruthPages {
			res.Failure = "page limit reached"
			return res
		}
		var trades []Trade
		s, obj := c.One(ctx, src.ID(), src.QueryURL(start, end), nil)
		if obj != nil && s.Stage == StageOK {
			resp, _ := refsource.Verify(obj, c.Verify)
			var e error
			if trades, e = src.ParseTrades(resp); e != nil {
				s.Stage, s.Error = StageInvalid, "parse: "+e.Error()
			}
		}
		res.Pages = append(res.Pages, s)
		if s.Stage != StageOK {
			res.Failure = fmt.Sprintf("page %d: %s", page, s.Stage)
			return res
		}
		for _, t := range trades {
			seen[t.ID] = t
		}
		if len(trades) < BitfinexPageLimit {
			break
		}
		res.SplitQuery = true
		min := trades[0].MTS
		for _, t := range trades {
			if t.MTS < min {
				min = t.MTS
			}
		}
		if min == end {
			// A full page within one millisecond: step past it.
			res.MsTruncated = true
			min = end - 1
		}
		end = min
		if end < start {
			break
		}
	}
	all := make([]Trade, 0, len(seen))
	for _, t := range seen {
		all = append(all, t)
	}
	res.TradesInWin = len(all)
	p, mts, ids, ok := Nearest(all, ref)
	if !ok {
		res.Failure = "no trades in window"
		return res
	}
	res.OK, res.Price, res.TradeMTS, res.LatencyMs, res.TradeIDs = true, p, mts, mts-ref, ids
	return res
}
