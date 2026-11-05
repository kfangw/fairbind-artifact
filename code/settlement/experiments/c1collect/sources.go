// Package c1collect holds the Go side of the C1 data-API collector: the
// seller-role and truth-reference adapters, the construction of signed
// seller bundles, and the verifier instance that captures its own references
// and judges each response through dataworker.Pipeline. The scheduler, state
// and wrong-answer assignment live in collector.py next to this package.
package c1collect

import (
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/url"
	"sort"
	"strconv"

	"example.org/fairbind/runtime/dataworker"
	"example.org/fairbind/runtime/dataworker/refsource"
)

// Source identifiers of the collection plan (experiments/calibration/c1-config.json).
const (
	BitstampID = "bitstamp:ticker:btcusd"
	GeminiID   = "gemini:pubticker:btcusd"
	BitfinexID = "bitfinex:trades:tBTCUSD"
)

// FieldPrice is the only field a seller-role observation carries.
const FieldPrice = "price"

// BitstampTicker reads GET /api/v2/ticker/btcusd/ on the Bitstamp public API.
// The documented body is an object of strings ("last", "bid", "ask",
// "timestamp", ...). Only "last" is used.
type BitstampTicker struct{}

func (BitstampTicker) ID() string  { return BitstampID }
func (BitstampTicker) URL() string { return "https://www.bitstamp.net/api/v2/ticker/btcusd/" }
func (s BitstampTicker) Parse(r *refsource.Response) (dataworker.Observation, error) {
	return parseLast(s.ID(), r)
}

// GeminiTicker reads GET /v1/pubticker/btcusd on the Gemini public API. The
// documented body is {"bid","ask","last": decimal strings, "volume": {...}}.
// Only "last" is used.
type GeminiTicker struct{}

func (GeminiTicker) ID() string  { return GeminiID }
func (GeminiTicker) URL() string { return "https://api.gemini.com/v1/pubticker/btcusd" }
func (s GeminiTicker) Parse(r *refsource.Response) (dataworker.Observation, error) {
	return parseLast(s.ID(), r)
}

// SellerRegistry returns the two seller-role sources. It is deliberately
// separate from refsource.DefaultRegistry so that a seller-role source can
// never be selected as a reference.
func SellerRegistry() refsource.Registry {
	return refsource.Registry{BitstampID: BitstampTicker{}, GeminiID: GeminiTicker{}}
}

// SellerOrder is the order of seller sources within a cell.
var SellerOrder = []string{BitstampID, GeminiID}

func parseLast(id string, r *refsource.Response) (dataworker.Observation, error) {
	var body map[string]json.RawMessage
	if e := refsource.DecodeJSONBody(r, &body); e != nil {
		return dataworker.Observation{}, e
	}
	var last string
	if raw, ok := body["last"]; !ok || json.Unmarshal(raw, &last) != nil {
		return dataworker.Observation{}, errors.New(`member "last" missing or not a string`)
	}
	v, e := refsource.NormalizeDecimal(last)
	if e != nil {
		return dataworker.Observation{}, fmt.Errorf("last: %w", e)
	}
	if r.Date.Unix() < 0 {
		return dataworker.Observation{}, errors.New("Date before epoch")
	}
	return dataworker.Observation{
		Source: id, ObservedAt: uint64(r.Date.Unix()),
		Values: map[string]string{FieldPrice: v}, Units: map[string]string{FieldPrice: "USD"},
	}, nil
}

// Bitfinex trade history query limits.
const (
	BitfinexPageLimit = 100
	TruthWindowMs     = 10_000
)

// BitfinexTrades reads GET /v2/trades/tBTCUSD/hist with start, end (Unix
// milliseconds, inclusive), sort=-1 and limit=100. The documented body is an
// array of trades [ID, MTS, AMOUNT, PRICE], newest first. It is a truth
// reference only: it never enters a judgment.
type BitfinexTrades struct{}

func (BitfinexTrades) ID() string { return BitfinexID }

// QueryURL is the only URL form accepted for this source.
func (BitfinexTrades) QueryURL(startMs, endMs int64) string {
	return fmt.Sprintf("https://api-pub.bitfinex.com/v2/trades/tBTCUSD/hist?start=%d&end=%d&sort=-1&limit=%d", startMs, endMs, BitfinexPageLimit)
}

// Trade is one parsed trade. Price is a canonical decimal string.
type Trade struct {
	ID    int64  `json:"id"`
	MTS   int64  `json:"mts"`
	Price string `json:"price"`
}

// ParseQuery checks that the object's URL is a well-formed query of this
// source and returns its window.
func (b BitfinexTrades) ParseQuery(rawURL string) (startMs, endMs int64, err error) {
	u, e := url.Parse(rawURL)
	if e != nil {
		return 0, 0, e
	}
	q := u.Query()
	startMs, e1 := strconv.ParseInt(q.Get("start"), 10, 64)
	endMs, e2 := strconv.ParseInt(q.Get("end"), 10, 64)
	if e1 != nil || e2 != nil || b.QueryURL(startMs, endMs) != rawURL {
		return 0, 0, errors.New("not a registered Bitfinex trades query")
	}
	return startMs, endMs, nil
}

// ParseTrades verifies the response of one page. Every trade must lie in the
// queried window and carry a plain decimal price.
func (b BitfinexTrades) ParseTrades(r *refsource.Response) ([]Trade, error) {
	if r.Object.SourceID != b.ID() {
		return nil, errors.New("object does not belong to the Bitfinex source")
	}
	startMs, endMs, e := b.ParseQuery(r.Object.URL)
	if e != nil {
		return nil, e
	}
	var rows [][]json.Number
	if e := refsource.DecodeJSONBody(r, &rows); e != nil {
		return nil, e
	}
	if len(rows) > BitfinexPageLimit {
		return nil, errors.New("more trades than the page limit")
	}
	out := make([]Trade, 0, len(rows))
	for _, row := range rows {
		if len(row) != 4 {
			return nil, errors.New("trade is not [ID, MTS, AMOUNT, PRICE]")
		}
		id, e1 := row[0].Int64()
		mts, e2 := row[1].Int64()
		if e1 != nil || e2 != nil {
			return nil, errors.New("trade ID or MTS is not an integer")
		}
		if mts < startMs || mts > endMs {
			return nil, errors.New("trade outside the queried window")
		}
		p, e := refsource.NormalizeDecimal(row[3].String())
		if e != nil {
			return nil, fmt.Errorf("trade price: %w", e)
		}
		out = append(out, Trade{ID: id, MTS: mts, Price: p})
	}
	return out, nil
}

// Nearest selects the trades whose time is closest to referenceMs and returns
// the median of their prices as an exact decimal. ok is false without trades.
func Nearest(trades []Trade, referenceMs int64) (price string, mts int64, ids []int64, ok bool) {
	if len(trades) == 0 {
		return "", 0, nil, false
	}
	abs := func(x int64) int64 {
		if x < 0 {
			return -x
		}
		return x
	}
	best := abs(trades[0].MTS - referenceMs)
	for _, t := range trades[1:] {
		if d := abs(t.MTS - referenceMs); d < best {
			best = d
		}
	}
	var vals []*big.Rat
	seenMTS := map[int64]bool{}
	for _, t := range trades {
		if abs(t.MTS-referenceMs) != best {
			continue
		}
		r, _ := new(big.Rat).SetString(t.Price)
		vals = append(vals, r)
		ids = append(ids, t.ID)
		seenMTS[t.MTS] = true
	}
	// Two different times can be equally close (before and after); report the
	// earlier one as the trade time and take the median over all of them.
	mts = referenceMs + best
	if seenMTS[referenceMs-best] {
		mts = referenceMs - best
	}
	sort.Slice(vals, func(i, j int) bool { return vals[i].Cmp(vals[j]) < 0 })
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	m := new(big.Rat).Add(vals[(len(vals)-1)/2], vals[len(vals)/2])
	m.Quo(m, big.NewRat(2, 1))
	return dataworker.FormatDecimal(m), mts, ids, true
}
