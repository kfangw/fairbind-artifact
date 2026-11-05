package refsource

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"mime"
	"net/http"
	"regexp"
	"strings"
	"time"

	"example.org/fairbind/runtime/dataworker"
)

// Source is one registered reference endpoint. Parse turns a verified response
// into an observation whose values are canonical decimal strings.
type Source interface {
	ID() string
	URL() string
	Parse(*Response) (dataworker.Observation, error)
}

// Registry maps source identifiers to adapters. Only operator configuration
// may populate it; source identifiers in a policy select entries but never
// define endpoints.
type Registry map[string]Source

// DefaultRegistry returns the two BTC/USD ticker sources described in README.md.
func DefaultRegistry() Registry {
	r := Registry{}
	for _, s := range []Source{
		CoinbaseTicker{Product: "BTC-USD", Quote: "USD"},
		KrakenTicker{Pair: "XBTUSD", ResultKey: "XXBTZUSD", Quote: "USD"},
	} {
		r[s.ID()] = s
	}
	return r
}

// Observation field names produced by both ticker adapters.
const (
	FieldPrice = "price" // last trade price
	FieldBid   = "bid"   // best bid
	FieldAsk   = "ask"   // best ask
)

var decimalRE = regexp.MustCompile(`^[0-9]{1,40}(\.[0-9]{1,40})?$`)

// NormalizeDecimal returns the canonical form of a nonnegative plain decimal
// string: no exponent, no sign, no leading zeros in the integer part and no
// trailing zeros in the fraction. "64229.80000" becomes "64229.8".
func NormalizeDecimal(s string) (string, error) {
	if !decimalRE.MatchString(s) {
		return "", fmt.Errorf("unsupported decimal %q", s)
	}
	i, f, _ := strings.Cut(s, ".")
	i = strings.TrimLeft(i, "0")
	if i == "" {
		i = "0"
	}
	f = strings.TrimRight(f, "0")
	if f == "" {
		return i, nil
	}
	return i + "." + f, nil
}

// DecodeJSONBody is decodeJSONBody for adapters outside this package: it
// requires status 200 and application/json, rejects duplicate members and
// decodes the body into v with json.Number for numbers.
func DecodeJSONBody(r *Response, v any) error { return decodeJSONBody(r, v) }

// decodeJSONBody checks the status and media type, rejects duplicate members
// and decodes the body into v.
func decodeJSONBody(r *Response, v any) error {
	if r.Status != http.StatusOK {
		return fmt.Errorf("status %d", r.Status)
	}
	mt, _, e := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if e != nil || mt != "application/json" {
		return errors.New("response is not application/json")
	}
	if e := checkNoDuplicates(r.Body); e != nil {
		return e
	}
	d := json.NewDecoder(bytes.NewReader(r.Body))
	d.UseNumber()
	return d.Decode(v)
}

func observation(id string, r *Response, quote string, price, bid, ask string) (dataworker.Observation, error) {
	vals := map[string]string{}
	for k, v := range map[string]string{FieldPrice: price, FieldBid: bid, FieldAsk: ask} {
		n, e := NormalizeDecimal(v)
		if e != nil {
			return dataworker.Observation{}, fmt.Errorf("%s: %w", k, e)
		}
		vals[k] = n
	}
	if r.Date.Unix() < 0 {
		return dataworker.Observation{}, errors.New("Date before epoch")
	}
	return dataworker.Observation{
		Source:     id,
		ObservedAt: uint64(r.Date.Unix()),
		Values:     vals,
		Units:      map[string]string{FieldPrice: quote, FieldBid: quote, FieldAsk: quote},
	}, nil
}

// CoinbaseTicker reads GET /products/{product}/ticker on the Coinbase Exchange
// public REST API. The documented body is an object with string members
// "price", "bid", "ask", "size", "volume", "time" and integer "trade_id".
type CoinbaseTicker struct {
	Product string
	Quote   string
	// MaxTradeAge rejects a ticker whose last trade is older than this relative
	// to the Date header. Zero means 5 minutes.
	MaxTradeAge time.Duration
}

func (c CoinbaseTicker) ID() string { return "coinbase-exchange:ticker:" + c.Product }
func (c CoinbaseTicker) URL() string {
	return "https://api.exchange.coinbase.com/products/" + c.Product + "/ticker"
}
func (c CoinbaseTicker) Parse(r *Response) (dataworker.Observation, error) {
	var raw map[string]json.RawMessage
	if e := decodeJSONBody(r, &raw); e != nil {
		return dataworker.Observation{}, e
	}
	str := map[string]string{}
	for _, name := range []string{"price", "bid", "ask", "time"} {
		var s string
		if e := json.Unmarshal(raw[name], &s); e != nil || raw[name] == nil {
			return dataworker.Observation{}, fmt.Errorf("member %q missing or not a string", name)
		}
		str[name] = s
	}
	trade, e := time.Parse(time.RFC3339Nano, str["time"])
	if e != nil {
		return dataworker.Observation{}, errors.New("malformed trade time")
	}
	age := c.MaxTradeAge
	if age == 0 {
		age = 5 * time.Minute
	}
	if trade.After(r.Date.Add(5*time.Second)) || r.Date.Sub(trade) > age {
		return dataworker.Observation{}, errors.New("last trade time outside the allowed age")
	}
	return observation(c.ID(), r, c.Quote, str["price"], str["bid"], str["ask"])
}

// KrakenTicker reads GET /0/public/Ticker?pair={pair} on the Kraken spot REST
// API. The documented body is {"error":[...],"result":{PAIR:{...}}} where
// "a" (ask), "b" (bid) and "c" (last trade) are arrays whose first element is
// the price as a decimal string. The result key is Kraken's internal pair name,
// which differs from the request pair (XBTUSD is returned as XXBTZUSD).
type KrakenTicker struct {
	Pair      string
	ResultKey string
	Quote     string
}

func (k KrakenTicker) ID() string { return "kraken:ticker:" + k.Pair }
func (k KrakenTicker) URL() string {
	return "https://api.kraken.com/0/public/Ticker?pair=" + k.Pair
}
func (k KrakenTicker) Parse(r *Response) (dataworker.Observation, error) {
	var body struct {
		Error  []string                              `json:"error"`
		Result map[string]map[string]json.RawMessage `json:"result"`
	}
	if e := decodeJSONBody(r, &body); e != nil {
		return dataworker.Observation{}, e
	}
	if body.Error == nil || len(body.Error) != 0 {
		return dataworker.Observation{}, fmt.Errorf("kraken error %v", body.Error)
	}
	if len(body.Result) != 1 {
		return dataworker.Observation{}, errors.New("expected exactly one result pair")
	}
	t, ok := body.Result[k.ResultKey]
	if !ok {
		return dataworker.Observation{}, fmt.Errorf("result pair %q absent", k.ResultKey)
	}
	first := func(name string) (string, error) {
		var arr []json.RawMessage
		if e := json.Unmarshal(t[name], &arr); e != nil || len(arr) < 2 {
			return "", fmt.Errorf("member %q", name)
		}
		var s string
		if e := json.Unmarshal(arr[0], &s); e != nil {
			return "", fmt.Errorf("member %q price is not a string", name)
		}
		return s, nil
	}
	price, e1 := first("c")
	bid, e2 := first("b")
	ask, e3 := first("a")
	if e := errors.Join(e1, e2, e3); e != nil {
		return dataworker.Observation{}, e
	}
	return observation(k.ID(), r, k.Quote, price, bid, ask)
}
