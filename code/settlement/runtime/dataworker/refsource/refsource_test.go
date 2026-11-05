package refsource_test

import (
	"bytes"
	"context"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"example.org/fairbind/runtime/dataworker"
	"example.org/fairbind/runtime/dataworker/refsource"
)

const refTime = 1790000000

var (
	coinbaseID = refsource.CoinbaseTicker{Product: "BTC-USD"}.ID()
	krakenID   = refsource.KrakenTicker{Pair: "XBTUSD"}.ID()
	synthetic  = refsource.VerifyOptions{AllowSynthetic: true}
)

func replay(t *testing.T) refsource.Replay {
	t.Helper()
	r, e := refsource.LoadReplay("../testdata/refsource/replay", synthetic)
	if e != nil || len(r.Objects) != 3 {
		t.Fatal(e, len(r.Objects))
	}
	return r
}

func provider(r refsource.Retriever) refsource.Provider {
	return refsource.Provider{Registry: refsource.DefaultRegistry(), Retriever: r, Verify: synthetic}
}

func TestNormalizeDecimal(t *testing.T) {
	for in, want := range map[string]string{"64229.80000": "64229.8", "64231.57": "64231.57", "007.0": "7", "0.000": "0", "0.0100": "0.01", "100": "100"} {
		if got, e := refsource.NormalizeDecimal(in); e != nil || got != want {
			t.Fatal(in, got, e)
		}
	}
	for _, in := range []string{"", "-1", "+1", "1e3", "6.423157e4", ".5", "5.", "1,000", " 1", "NaN", strings.Repeat("9", 41)} {
		if _, e := refsource.NormalizeDecimal(in); e == nil {
			t.Fatal("accepted", in)
		}
	}
}

func TestReplayParseNormalize(t *testing.T) {
	var recs []refsource.Record
	p := provider(replay(t))
	p.OnRecord = func(r refsource.Record) { recs = append(recs, r) }
	obs, e := p.Retrieve(context.Background(), dataworker.SourceSet{Sources: []string{coinbaseID, krakenID}}, refTime)
	if e != nil {
		t.Fatal(e)
	}
	want := []dataworker.Observation{
		{Source: coinbaseID, ObservedAt: refTime, Values: map[string]string{"price": "64231.57", "bid": "64231.56", "ask": "64231.57"}, Units: map[string]string{"price": "USD", "bid": "USD", "ask": "USD"}},
		{Source: krakenID, ObservedAt: refTime + 1, Values: map[string]string{"price": "64229.8", "bid": "64229.7", "ask": "64229.8"}, Units: map[string]string{"price": "USD", "bid": "USD", "ask": "USD"}},
	}
	g, _ := json.Marshal(obs)
	w, _ := json.Marshal(want)
	if !bytes.Equal(g, w) {
		t.Fatalf("%s\n%s", g, w)
	}
	if len(recs) != 2 || len(recs[0].ObjectID) != 64 || recs[0].Error != "" {
		t.Fatalf("%+v", recs)
	}
	// Replay selection is by the Date header nearest the reference time.
	old, e := p.Retrieve(context.Background(), dataworker.SourceSet{Sources: []string{coinbaseID}}, refTime-9000)
	if e != nil || old[0].ObservedAt != refTime-10000 || old[0].Values["price"] != "63012.01" {
		t.Fatal(old, e)
	}
}

func TestSyntheticRejectedByDefault(t *testing.T) {
	o, e := refsource.Load("../testdata/refsource/replay/synthetic-coinbase-btc-usd-1790000000.json")
	if e != nil {
		t.Fatal(e)
	}
	if _, e := refsource.Verify(o, refsource.VerifyOptions{}); e == nil {
		t.Fatal("synthetic object accepted without AllowSynthetic")
	}
	p := provider(replay(t))
	p.Verify = refsource.VerifyOptions{}
	if _, e := p.Retrieve(context.Background(), dataworker.SourceSet{Sources: []string{coinbaseID}}, refTime); e == nil {
		t.Fatal("provider accepted synthetic object")
	}
}

func TestTamperedRawObject(t *testing.T) {
	load := func() *refsource.RawObject {
		o, e := refsource.Load("../testdata/refsource/replay/synthetic-kraken-xbtusd-1790000001.json")
		if e != nil {
			t.Fatal(e)
		}
		if _, e := refsource.Verify(o, synthetic); e != nil {
			t.Fatal(e)
		}
		return o
	}
	cases := map[string]func(*refsource.RawObject){
		"body byte": func(o *refsource.RawObject) { o.ResponseRaw[len(o.ResponseRaw)-20] ^= 1 },
		"head text": func(o *refsource.RawObject) {
			o.ResponseHead = strings.Replace(o.ResponseHead, "cloudflare", "cloudflarf", 1)
		},
		"http url":     func(o *refsource.RawObject) { o.URL = strings.Replace(o.URL, "https", "http", 1) },
		"request path": func(o *refsource.RawObject) { o.URL = strings.Replace(o.URL, "XBTUSD", "ETHUSD", 1) },
		"format":       func(o *refsource.RawObject) { o.Format = "other" },
		"date window":  func(o *refsource.RawObject) { o.StartedAtMs -= 3600_000; o.FinishedAtMs -= 3600_000 },
		"trailing data": func(o *refsource.RawObject) {
			o.ResponseRaw = append(o.ResponseRaw, 'x')
			o.ResponseSHA256 = refsource.SHA256Hex(o.ResponseRaw)
		},
	}
	for name, mutate := range cases {
		o := load()
		mutate(o)
		if _, e := refsource.Verify(o, synthetic); e == nil {
			t.Fatal("accepted tampered object:", name)
		}
	}
	// A duplicate member in the evidence file itself is rejected.
	if _, e := refsource.Decode([]byte(`{"format":"a","format":"b"}`)); e == nil {
		t.Fatal("duplicate member accepted")
	}
}

func TestMalformedResponsesDoNotParse(t *testing.T) {
	reg := refsource.DefaultRegistry()
	files, _ := filepath.Glob("../testdata/refsource/malformed/*.json")
	if len(files) != 5 {
		t.Fatal(files)
	}
	for _, f := range files {
		o, e := refsource.Load(f)
		if e != nil {
			t.Fatal(f, e)
		}
		r, e := refsource.Verify(o, synthetic)
		if e != nil {
			t.Fatal(f, e)
		}
		if obs, e := reg[o.SourceID].Parse(r); e == nil {
			t.Fatal("parsed malformed fixture", f, obs)
		}
	}
}

func TestSourceBinding(t *testing.T) {
	r := replay(t)
	for _, o := range r.Objects {
		if o.SourceID == krakenID {
			o.SourceID = coinbaseID // Kraken bytes presented as the Coinbase source
		}
	}
	p := provider(r)
	if _, e := p.Retrieve(context.Background(), dataworker.SourceSet{Sources: []string{coinbaseID}}, refTime+1); e == nil {
		t.Fatal("object for another endpoint accepted")
	}
	if _, e := provider(replay(t)).Retrieve(context.Background(), dataworker.SourceSet{Sources: []string{"unregistered"}}, refTime); e == nil {
		t.Fatal("unregistered source accepted")
	}
}

// compare runs the experimental comparator with the same payload shape that
// dataworker.Worker.Evaluate sends after its binding gate.
func compare(t *testing.T, p dataworker.Policy, response string, obs []dataworker.Observation) dataworker.Result {
	t.Helper()
	py, e := exec.LookPath("python3")
	if e != nil {
		t.Skip("python3 unavailable")
	}
	comparator, _ := filepath.Abs("../../predicates/data_experiment.py")
	payload, _ := json.Marshal(map[string]any{"policyId": fmt.Sprintf("0x%x", dataworker.PolicyID), "policy": p, "responseBase64": []byte(response), "observations": obs})
	cmd := exec.Command(py, comparator)
	cmd.Stdin = bytes.NewReader(payload)
	out, e := cmd.Output()
	if e != nil {
		t.Fatal(e)
	}
	var r dataworker.Result
	if e := json.Unmarshal(out, &r); e != nil {
		t.Fatal(e, string(out))
	}
	return r
}

// verdict follows Worker.Evaluate: a provider error is INCONCLUSIVE before comparison.
func verdict(t *testing.T, prov refsource.Provider, p dataworker.Policy, response string) dataworker.Result {
	t.Helper()
	obs, e := prov.Retrieve(context.Background(), dataworker.SourceSet{Sources: p.Sources}, p.ReferenceTime)
	if e != nil {
		return dataworker.Result{Verdict: "INCONCLUSIVE", Reason: "references_unavailable"}
	}
	return compare(t, p, response, obs)
}

func TestVerdictsFromReplayedReferences(t *testing.T) {
	policy := dataworker.Policy{
		Sources: []string{coinbaseID, krakenID}, Quorum: 2, ReferenceTime: refTime, MaxSkew: 30,
		Fields: map[string]dataworker.Field{"price": {Unit: "USD", Absolute: "5", Relative: "0.001", Spread: "50"}},
	}
	full := provider(replay(t))
	// Median of 64231.57 and 64229.8 is 64230.685; the bound is 5 + 0.001*64230.685.
	if r := verdict(t, full, policy, `{"price":"64230.10"}`); r.Verdict != "PASS" || r.Medians["price"] != "12846137/200" {
		t.Fatalf("%+v", r)
	}
	if r := verdict(t, full, policy, `{"price":"64295"}`); r.Verdict != "PASS" {
		t.Fatalf("%+v", r)
	}
	if r := verdict(t, full, policy, `{"price":"64500"}`); r.Verdict != "FAIL" || r.Reason != "tolerance exceeded" {
		t.Fatalf("%+v", r)
	}
	if r := verdict(t, full, policy, `{"size":"1"}`); r.Verdict != "FAIL" || r.Reason != "required field absent" {
		t.Fatalf("%+v", r)
	}

	// Reference unavailable: the Kraken object is missing.
	partial := replay(t)
	var kept []*refsource.RawObject
	for _, o := range partial.Objects {
		if o.SourceID != krakenID {
			kept = append(kept, o)
		}
	}
	partial.Objects = kept
	missing := provider(partial)
	if r := verdict(t, missing, policy, `{"price":"64230.10"}`); r.Verdict != "INCONCLUSIVE" || r.Reason != "references_unavailable" {
		t.Fatalf("%+v", r)
	}
	// With AllowPartial the comparison applies the quorum and still cannot decide.
	missing.AllowPartial = true
	if r := verdict(t, missing, policy, `{"price":"64500"}`); r.Verdict != "INCONCLUSIVE" || r.Reason != "reference quorum unavailable" {
		t.Fatalf("%+v", r)
	}
	// Reference unavailable at the committed time: the nearest saved objects
	// are outside the policy skew, even though a seller response is far off.
	late := policy
	late.ReferenceTime = refTime + 3600
	if r := verdict(t, full, late, `{"price":"1"}`); r.Verdict != "INCONCLUSIVE" || r.Reason != "reference quorum unavailable" {
		t.Fatalf("%+v", r)
	}
	// A failed source response (503) leaves the reference unavailable.
	bad, e := refsource.LoadReplay("../testdata/refsource/malformed", synthetic)
	if e != nil {
		t.Fatal(e)
	}
	if r := verdict(t, provider(bad), policy, `{"price":"64230.10"}`); r.Verdict != "INCONCLUSIVE" {
		t.Fatalf("%+v", r)
	}
	// Sources that disagree by more than the committed spread are INCONCLUSIVE.
	tight := policy
	tight.Fields = map[string]dataworker.Field{"price": {Unit: "USD", Absolute: "5", Relative: "0.001", Spread: "1"}}
	if r := verdict(t, full, tight, `{"price":"64230.10"}`); r.Verdict != "INCONCLUSIVE" || r.Reason != "references disagree" {
		t.Fatalf("%+v", r)
	}
}

// TestCaptureOverTLS runs the live capture path against a local TLS server and
// replays the stored object with chain verification.
func TestCaptureOverTLS(t *testing.T) {
	const date = "Mon, 21 Sep 2026 14:13:20 GMT"
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/products/BTC-USD/ticker" || r.Header.Get("User-Agent") == "" || r.Header.Get("Accept-Encoding") != "identity" {
			http.Error(w, "bad request", 400)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Date", date)
		w.Write([]byte(`{"ask":"64231.57","bid":"64231.56","volume":"1","trade_id":1,"price":"64231.57","size":"0.1","time":"2026-09-21T14:13:19.5Z"}`))
	}))
	srv.StartTLS()
	defer srv.Close()
	roots := x509.NewCertPool()
	roots.AddCert(srv.Certificate())
	clock, _ := http.ParseTime(date)
	c := refsource.Capturer{Roots: roots, DialAddr: srv.Listener.Addr().String(), Now: func() time.Time { return clock }}
	const url = "https://example.com/products/BTC-USD/ticker"
	o, e := c.Capture(context.Background(), coinbaseID, url)
	if e != nil {
		t.Fatal(e)
	}
	if o.TLS.ServerName != "example.com" || len(o.TLS.PeerCertificates) == 0 || o.TLS.VerifiedChainRoot == "" || o.TLS.Version == "" || !strings.HasPrefix(o.ResponseHead, "HTTP/1.1 200 OK\r\n") {
		t.Fatalf("%+v", o.TLS)
	}
	dir := t.TempDir()
	sink := &refsource.DirSink{Dir: dir}
	id, e := sink.Put(o)
	if e != nil {
		t.Fatal(e)
	}
	if again, e := sink.Put(o); e != nil || again != id {
		t.Fatal("sink is not content addressed", e)
	}
	loaded, e := refsource.LoadReplay(dir, refsource.VerifyOptions{Roots: roots})
	if e != nil || len(loaded.Objects) != 1 {
		t.Fatal(e)
	}
	r, e := refsource.Verify(loaded.Objects[0], refsource.VerifyOptions{Roots: roots})
	if e != nil {
		t.Fatal(e)
	}
	obs, e := refsource.CoinbaseTicker{Product: "BTC-USD", Quote: "USD"}.Parse(r)
	if e != nil || obs.Values["price"] != "64231.57" || obs.ObservedAt != uint64(clock.Unix()) {
		t.Fatal(obs, e)
	}
	// The recorded chain does not verify under the system roots, and a
	// captured object cannot be relabelled as synthetic to skip the check.
	if _, e := refsource.Verify(loaded.Objects[0], refsource.VerifyOptions{}); e == nil {
		t.Fatal("test chain verified under system roots")
	}
	loaded.Objects[0].Capture.Synthetic = true
	if _, e := refsource.Verify(loaded.Objects[0], synthetic); e == nil {
		t.Fatal("captured chain accepted as synthetic")
	}
	// Chain validation happens at capture time as well.
	c.Roots = x509.NewCertPool()
	_, e = c.Capture(context.Background(), coinbaseID, url)
	var ce *refsource.CaptureError
	if !errors.As(e, &ce) || ce.Stage != refsource.StageConnect {
		t.Fatal("untrusted server accepted or failure not at the connection stage: ", e)
	}
}

// TestCaptureFailureStages checks that a capture failure says whether any HTTP
// response bytes arrived: a refused connection is a connection-stage failure,
// a server that closes after the handshake is an exchange failure.
func TestCaptureFailureStages(t *testing.T) {
	ln, e := net.Listen("tcp", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	addr := ln.Addr().String()
	ln.Close()
	var ce *refsource.CaptureError
	c := refsource.Capturer{DialAddr: addr, Timeout: 2 * time.Second}
	if _, e := c.Capture(context.Background(), coinbaseID, "https://example.com/x"); !errors.As(e, &ce) || ce.Stage != refsource.StageConnect {
		t.Fatal("refused connection: ", e)
	}
	srv := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hj, _ := w.(http.Hijacker)
		conn, _, _ := hj.Hijack()
		conn.Close()
	}))
	srv.StartTLS()
	defer srv.Close()
	roots := x509.NewCertPool()
	roots.AddCert(srv.Certificate())
	c = refsource.Capturer{Roots: roots, DialAddr: srv.Listener.Addr().String(), Timeout: 2 * time.Second}
	if _, e := c.Capture(context.Background(), coinbaseID, "https://example.com/x"); !errors.As(e, &ce) || ce.Stage != refsource.StageExchange {
		t.Fatal("closed after handshake: ", e)
	}
}
