package c1collect_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"fmt"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"example.org/fairbind/experiments/c1collect"
	"example.org/fairbind/runtime/dataworker/refsource"
	"example.org/fairbind/runtime/verifier"
)

var synthetic = refsource.VerifyOptions{AllowSynthetic: true}

func load(t *testing.T, path string) *refsource.Response {
	t.Helper()
	o, e := refsource.Load(filepath.Join("testdata", path))
	if e != nil {
		t.Fatal(e)
	}
	r, e := refsource.Verify(o, synthetic)
	if e != nil {
		t.Fatal(path, e)
	}
	return r
}

func TestFrameHash(t *testing.T) {
	h, e := c1collect.ComputeFrameHash()
	if e != nil || h != c1collect.FrameHash {
		t.Fatal(h, e)
	}
}

func TestSellerAdaptersOnRecordedResponses(t *testing.T) {
	cases := map[string]struct {
		src  refsource.Source
		want string
	}{
		"recorded/bitstamp_ticker_btcusd.json":  {c1collect.BitstampTicker{}, "85284.45"},
		"recorded/gemini_pubticker_btcusd.json": {c1collect.GeminiTicker{}, "85296.99"},
	}
	for path, c := range cases {
		r := load(t, path)
		if r.Object.SourceID != c.src.ID() || r.Object.URL != c.src.URL() {
			t.Fatal(path, "fixture does not belong to its source")
		}
		o, e := c.src.Parse(r)
		if e != nil || o.Values["price"] != c.want || o.Units["price"] != "USD" || o.ObservedAt != uint64(r.Date.Unix()) || len(o.Values) != 1 {
			t.Fatal(path, o, e)
		}
	}
	// Seller-role sources can never be selected as references and vice versa.
	ref, sel := refsource.DefaultRegistry(), c1collect.SellerRegistry()
	for id := range sel {
		if _, ok := ref[id]; ok {
			t.Fatal(id, "is registered as a reference")
		}
	}
	for id := range ref {
		if _, ok := sel[id]; ok {
			t.Fatal(id, "is registered as a seller")
		}
	}
}

func TestSellerAdaptersRejectMalformed(t *testing.T) {
	for path, src := range map[string]refsource.Source{
		"synthetic/bitstamp-429.json":          c1collect.BitstampTicker{},
		"synthetic/bitstamp-exponent.json":     c1collect.BitstampTicker{},
		"synthetic/gemini-missing-last.json":   c1collect.GeminiTicker{},
		"synthetic/gemini-duplicate-last.json": c1collect.GeminiTicker{},
		"synthetic/gemini-503.json":            c1collect.GeminiTicker{},
	} {
		if o, e := src.Parse(load(t, path)); e == nil {
			t.Fatal(path, "parsed:", o)
		}
	}
	if r := load(t, "synthetic/bitstamp-429.json"); r.Status != 429 {
		t.Fatal(r.Status)
	}
}

func TestBitfinexTradesAndNearest(t *testing.T) {
	b := c1collect.BitfinexTrades{}
	trades, e := b.ParseTrades(load(t, "synthetic/bitfinex-window.json"))
	if e != nil || len(trades) != 4 {
		t.Fatal(trades, e)
	}
	const ref = int64(1790000000) * 1000
	p, mts, ids, ok := c1collect.Nearest(trades, ref)
	// Two trades 400 ms either side: median of 85001.25 and 85003.
	if !ok || p != "85002.125" || mts != ref-400 || fmt.Sprint(ids) != "[1003 1004]" {
		t.Fatal(p, mts, ids, ok)
	}
	if p, _, _, _ := c1collect.Nearest(trades[:1], ref); p != "85010.5" {
		t.Fatal(p)
	}
	if empty, e := b.ParseTrades(load(t, "synthetic/bitfinex-empty.json")); e != nil || len(empty) != 0 {
		t.Fatal(empty, e)
	} else if _, _, _, ok := c1collect.Nearest(empty, ref); ok {
		t.Fatal("nearest trade without trades")
	}
	for _, path := range []string{"synthetic/bitfinex-error.json", "synthetic/bitfinex-exponent.json", "synthetic/bitfinex-outside.json"} {
		if tr, e := b.ParseTrades(load(t, path)); e == nil {
			t.Fatal(path, tr)
		}
	}
	r := load(t, "synthetic/bitfinex-window.json")
	r.Object.URL = strings.Replace(r.Object.URL, "limit=100", "limit=1000", 1)
	if _, e := b.ParseTrades(r); e == nil {
		t.Fatal("unregistered query accepted")
	}
}

// tlsServer serves handler over TLS with a self-signed certificate valid for
// hosts, and returns a capturer that dials it for every host.
func tlsServer(t *testing.T, hosts []string, handler http.Handler) (c1collect.Capturer, func()) {
	t.Helper()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	tmpl := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: hosts[0]}, DNSNames: hosts,
		NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), IsCA: true, BasicConstraintsValid: true,
		KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	der, e := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if e != nil {
		t.Fatal(e)
	}
	cert, _ := x509.ParseCertificate(der)
	srv := httptest.NewUnstartedServer(handler)
	srv.TLS = &tls.Config{Certificates: []tls.Certificate{{Certificate: [][]byte{der}, PrivateKey: key}}}
	srv.StartTLS()
	roots := x509.NewCertPool()
	roots.AddCert(cert)
	opt := refsource.VerifyOptions{Roots: roots}
	c := c1collect.Capturer{Capture: refsource.Capturer{Roots: roots, DialAddr: srv.Listener.Addr().String(), Timeout: 5 * time.Second}, Verify: opt, Dir: t.TempDir()}
	return c, srv.Close
}

func TestLookupTruthPagesTheWindow(t *testing.T) {
	ref := time.Now().Unix()
	// 250 trades, one every 80 ms from ref-9.9 s, served newest first in pages of 100.
	var all [][]any
	for i := 0; i < 250; i++ {
		mts := ref*1000 - 9900 + int64(i)*80
		all = append(all, []any{i + 1, mts, 0.01, json.Number(fmt.Sprintf("85%03d.5", i))})
	}
	var mu sync.Mutex
	var queries []string
	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		queries = append(queries, r.URL.RawQuery)
		mu.Unlock()
		q := r.URL.Query()
		start, _ := strconv.ParseInt(q.Get("start"), 10, 64)
		end, _ := strconv.ParseInt(q.Get("end"), 10, 64)
		var page [][]any
		for i := len(all) - 1; i >= 0 && len(page) < 100; i-- {
			if m := all[i][1].(int64); m >= start && m <= end {
				page = append(page, all[i])
			}
		}
		w.Header().Set("Content-Type", "application/json; charset=utf-8")
		json.NewEncoder(w).Encode(page)
	})
	c, stop := tlsServer(t, []string{"api-pub.bitfinex.com"}, handler)
	defer stop()
	res := c.LookupTruth(context.Background(), uint64(ref))
	// Trade i is at ref-9900+80i ms; the nearest to ref is i=124 (ref+20 ms).
	if !res.OK || res.Price != "85124.5" || res.LatencyMs != 20 || !res.SplitQuery || len(res.Pages) != 3 || res.TradesInWin != 249 {
		t.Fatalf("%+v %v", res, queries)
	}
	for _, p := range res.Pages {
		if p.Stage != c1collect.StageOK || p.ObjectFile == "" {
			t.Fatal(p)
		}
	}
	// A rate-limited lookup fails with the HTTP status recorded.
	c2, stop2 := tlsServer(t, []string{"api-pub.bitfinex.com"}, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `["error",11010,"ratelimit: error"]`, 429)
	}))
	defer stop2()
	res = c2.LookupTruth(context.Background(), uint64(ref))
	if res.OK || len(res.Pages) != 1 || res.Pages[0].HTTPStatus != 429 || !res.Pages[0].GotResponse() {
		t.Fatalf("%+v", res)
	}
}

func TestCaptureSummaryStages(t *testing.T) {
	ln, _ := net.Listen("tcp", "127.0.0.1:0")
	addr := ln.Addr().String()
	ln.Close()
	logPath := filepath.Join(t.TempDir(), "requests.log")
	c := c1collect.Capturer{Capture: refsource.Capturer{DialAddr: addr, Timeout: 2 * time.Second}, Log: c1collect.RequestLog{Path: logPath}, Role: "seller"}
	s, obj := c.One(context.Background(), c1collect.BitstampID, c1collect.BitstampTicker{}.URL(), nil)
	if obj != nil || s.Stage != refsource.StageConnect || s.GotResponse() {
		t.Fatal(s)
	}
	c2, stop := tlsServer(t, []string{"www.bitstamp.net"}, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "slow down", 429)
	}))
	defer stop()
	c2.Log = c.Log
	s, obj = c2.One(context.Background(), c1collect.BitstampID, c1collect.BitstampTicker{}.URL(), c1collect.PriceParser(c1collect.BitstampTicker{}))
	if obj == nil || s.Stage != c1collect.StageInvalid || s.HTTPStatus != 429 || !s.GotResponse() || s.Value != "" {
		t.Fatal(s)
	}
	if _, e := os.Stat(filepath.Join(c2.Dir, s.ObjectFile)); e != nil {
		t.Fatal("failed response not retained: ", e)
	}
	b, _ := os.ReadFile(logPath)
	if strings.Count(string(b), "\n") != 2 {
		t.Fatalf("request log: %q", b)
	}
}

func referenceServer(t *testing.T, coinbase, kraken string, seen *[]string, mu *sync.Mutex) (c1collect.Capturer, func()) {
	return tlsServer(t, []string{"api.exchange.coinbase.com", "api.kraken.com"}, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		*seen = append(*seen, r.Host)
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		switch r.Host {
		case "api.exchange.coinbase.com":
			fmt.Fprintf(w, `{"ask":"%[1]s","bid":"%[1]s","volume":"1","trade_id":1,"price":"%[1]s","size":"0.1","time":"%[2]s"}`, coinbase, time.Now().UTC().Format(time.RFC3339Nano))
		default:
			fmt.Fprintf(w, `{"error":[],"result":{"XXBTZUSD":{"a":["%[1]s","1","1"],"b":["%[1]s","1","1"],"c":["%[1]s","0.1"]}}}`, kraken)
		}
	}))
}

func TestInstanceCapturesOnPlanAndJudges(t *testing.T) {
	var mu sync.Mutex
	var seen []string
	c, stop := referenceServer(t, "85000", "85100", &seen, &mu)
	defer stop()
	ref := uint64(time.Now().Unix())
	coinbase, kraken := c1collect.ReferenceOrder()[0], c1collect.ReferenceOrder()[1]
	plan := c1collect.Plan{ReferenceTime: ref, Instance: 2, StartUnixMs: time.Now().Add(300 * time.Millisecond).UnixMilli(), Order: []string{kraken, coinbase}}
	started := time.Now()
	caps, objs, done, e := c1collect.CaptureReferences(context.Background(), plan, c, c1collect.SleepUntil)
	if e != nil || len(caps) != 2 || len(objs) != 2 || done < plan.StartUnixMs {
		t.Fatal(caps, e)
	}
	if time.Since(started) < 250*time.Millisecond || strings.Join(seen, ",") != "api.kraken.com,api.exchange.coinbase.com" {
		t.Fatal("plan order or start time not respected: ", seen)
	}
	for _, s := range caps {
		if s.Stage != c1collect.StageOK || s.Value != "" {
			t.Fatal("instance capture summary: ", s)
		}
	}
	var cases []c1collect.Case
	for i, body := range []string{`{"price":"85050"}`, `{"price":"90000"}`, `{}`} {
		cs, e := c1collect.BuildCase(context.Background(), fmt.Sprintf("r%d", i), []byte(body), ref, c1collect.CastSigner(""))
		if e != nil {
			t.Fatal("public-fixture signing unavailable: ", e)
		}
		cases = append(cases, cs)
	}
	js := c1collect.Judge(context.Background(), plan, caps, objs, cases, verifier.CastVerifier{}, c.Verify)
	got := []string{}
	for _, j := range js {
		got = append(got, j.Verdict+"/"+j.Error)
	}
	if strings.Join(got, ",") != "PASS/,FAIL/,FAIL/" {
		t.Fatal(got)
	}
	rec := c1collect.Record{Format: c1collect.JudgmentFormat, Plan: plan, Captures: caps, Judgments: js}
	if n, e := c1collect.Rederive(rec, c.Verify); e != nil || n != 3 {
		t.Fatal(n, e)
	}
	rec.Judgments[1].Verdict = "PASS"
	if _, e := c1collect.Rederive(rec, c.Verify); e == nil {
		t.Fatal("altered verdict re-derived")
	}
	// A reference skipped under the 429 rule is not requested and the quorum fails.
	seen = nil
	plan.Skip = []string{kraken}
	plan.StartUnixMs = 0
	caps, objs, _, _ = c1collect.CaptureReferences(context.Background(), plan, c, c1collect.SleepUntil)
	if len(seen) != 1 || caps[0].Stage != c1collect.StageSkipped {
		t.Fatal(seen, caps)
	}
	js = c1collect.Judge(context.Background(), plan, caps, objs, cases[:1], verifier.CastVerifier{}, c.Verify)
	if js[0].Verdict != "INCONCLUSIVE" {
		t.Fatal(js[0].Verdict, js[0].Reason)
	}
}
