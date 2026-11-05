// Command c1tool is the Go side of the C1 data-API collector. The Python
// scheduler (experiments/c1collect/collector.py) calls it; it is not meant to
// be run by hand except for the diagnostic subcommands.
//
//	c1tool frame                                  print the policy frame and its hash
//	c1tool capture -role R -sources A,B -dir D    capture sources now, print summaries
//	c1tool truth -reference-time T -dir D         one truth lookup (all pages)
//	c1tool bundle < responses.json                build signed seller bundles
//	c1tool instance -plan JSON -dir D < cases     one verifier instance for one cell
//	c1tool rederive FILE...                       re-derive judgment records
//	c1tool objects DIR...                         decode and verify raw objects
package main

import (
	"context"
	"crypto/x509"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"time"

	"example.org/fairbind/experiments/c1collect"
	"example.org/fairbind/runtime/dataworker/refsource"
	"example.org/fairbind/runtime/verifier"
)

func main() {
	if len(os.Args) < 2 {
		fail(2, "usage: c1tool frame|capture|truth|bundle|instance|rederive|objects ...")
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	cmd, args := os.Args[1], os.Args[2:]
	switch cmd {
	case "frame":
		frame()
	case "capture":
		capture(ctx, args)
	case "truth":
		truth(ctx, args)
	case "bundle":
		bundle(ctx, args)
	case "instance":
		instance(ctx, args)
	case "rederive":
		rederive(args)
	case "objects":
		objects(args)
	default:
		fail(2, "unknown subcommand "+cmd)
	}
}

func fail(code int, msg string) {
	fmt.Fprintln(os.Stderr, "c1tool:", msg)
	os.Exit(code)
}

func emit(v any) {
	b, e := json.Marshal(v)
	if e != nil {
		fail(1, e.Error())
	}
	os.Stdout.Write(append(b, '\n'))
}

type common struct {
	dir, log, roots string
	timeout         time.Duration
}

func (c *common) register(fs *flag.FlagSet) {
	fs.StringVar(&c.dir, "dir", "", "directory for raw objects")
	fs.StringVar(&c.log, "log", "", "request log file (one line per request, appended)")
	fs.StringVar(&c.roots, "roots", "", "PEM file of trusted roots (default: system pool)")
	fs.DurationVar(&c.timeout, "timeout", 10*time.Second, "per-request timeout")
}

func (c *common) capturer(role string) c1collect.Capturer {
	opt := refsource.VerifyOptions{}
	if c.roots != "" {
		pem, e := os.ReadFile(c.roots)
		if e != nil {
			fail(2, e.Error())
		}
		opt.Roots = x509.NewCertPool()
		if !opt.Roots.AppendCertsFromPEM(pem) {
			fail(2, "no certificates in "+c.roots)
		}
	}
	proxy, e := refsource.ProxyFromEnvironment()
	if e != nil {
		fail(2, e.Error())
	}
	return c1collect.Capturer{
		Capture: refsource.Capturer{Roots: opt.Roots, Timeout: c.timeout, Proxy: proxy, UserAgent: "fairbind-c1collect/1"},
		Verify:  opt, Dir: c.dir, Log: c1collect.RequestLog{Path: c.log}, Role: role,
	}
}

func frame() {
	b, e := c1collect.FrameJSON()
	if e != nil {
		fail(1, e.Error())
	}
	h, _ := c1collect.ComputeFrameHash()
	emit(map[string]any{"frame": json.RawMessage(b), "frame_sha256": h, "expected_sha256": c1collect.FrameHash,
		"reference_order": c1collect.ReferenceOrder(), "seller_order": c1collect.SellerOrder})
	if h != c1collect.FrameHash {
		os.Exit(1)
	}
}

// capture fetches the listed sources one after another. Seller-role and
// generator captures report the parsed price; this subcommand is controller
// side only.
func capture(ctx context.Context, args []string) {
	fs := flag.NewFlagSet("capture", flag.ExitOnError)
	var c common
	c.register(fs)
	role := fs.String("role", "", "seller or generator")
	sources := fs.String("sources", "", "comma-separated source IDs")
	fs.Parse(args)
	var reg refsource.Registry
	switch *role {
	case "seller":
		reg = c1collect.SellerRegistry()
	case "generator":
		reg = refsource.DefaultRegistry()
	default:
		fail(2, "-role must be seller or generator")
	}
	cp := c.capturer(*role)
	var out []c1collect.Summary
	for _, id := range strings.Split(*sources, ",") {
		src, ok := reg[id]
		if !ok {
			fail(2, "source "+id+" is not registered for role "+*role)
		}
		s, _ := cp.One(ctx, id, src.URL(), c1collect.PriceParser(src))
		out = append(out, s)
	}
	emit(map[string]any{"captures": out})
}

func truth(ctx context.Context, args []string) {
	fs := flag.NewFlagSet("truth", flag.ExitOnError)
	var c common
	c.register(fs)
	t := fs.Uint64("reference-time", 0, "grid time in Unix seconds")
	fs.Parse(args)
	if *t == 0 {
		fail(2, "-reference-time is required")
	}
	emit(c.capturer("truth").LookupTruth(ctx, *t))
}

type responseIn struct {
	ResponseID string `json:"response_id"`
	Body       []byte `json:"body"`
}

func bundle(ctx context.Context, args []string) {
	fs := flag.NewFlagSet("bundle", flag.ExitOnError)
	cast := fs.String("cast", "cast", "pinned cast executable used to sign")
	fs.Parse(args)
	var in struct {
		ReferenceTime uint64       `json:"reference_time"`
		Responses     []responseIn `json:"responses"`
	}
	d := json.NewDecoder(os.Stdin)
	d.DisallowUnknownFields()
	if e := d.Decode(&in); e != nil {
		fail(2, "input: "+e.Error())
	}
	cases := []c1collect.Case{}
	for _, r := range in.Responses {
		c, e := c1collect.BuildCase(ctx, r.ResponseID, r.Body, in.ReferenceTime, c1collect.CastSigner(*cast))
		if e != nil {
			fail(1, e.Error())
		}
		cases = append(cases, c)
	}
	emit(map[string]any{"cases": cases})
}

// instance captures its references on the plan's schedule, then reads the
// cell's cases from stdin and judges them. If stdin closes before cases
// arrive, the controller is gone and the instance exits without output.
func instance(ctx context.Context, args []string) {
	fs := flag.NewFlagSet("instance", flag.ExitOnError)
	var c common
	c.register(fs)
	planJSON := fs.String("plan", "", "instance plan (JSON)")
	cast := fs.String("cast", "cast", "pinned cast executable used by the input gate")
	caseWait := fs.Duration("case-timeout", 120*time.Second, "how long to wait for cases after capturing")
	fs.Parse(args)
	var p c1collect.Plan
	if e := json.Unmarshal([]byte(*planJSON), &p); e != nil || p.ReferenceTime == 0 || p.Instance < 1 {
		fail(2, "invalid -plan")
	}
	cp := c.capturer(fmt.Sprintf("instance-%d", p.Instance))
	type input struct {
		b []byte
		e error
	}
	in := make(chan input, 1)
	go func() {
		b, e := io.ReadAll(os.Stdin)
		in <- input{b, e}
	}()
	var got *input
	gone := errors.New("controller closed the case channel")
	wait := func(ctx context.Context, ms int64) error {
		d := time.Until(time.UnixMilli(ms))
		if d < 0 {
			d = 0
		}
		t := time.NewTimer(d)
		defer t.Stop()
		for {
			select {
			case <-t.C:
				return nil
			case <-ctx.Done():
				return ctx.Err()
			case r := <-in:
				got = &r
				if len(r.b) == 0 {
					return gone
				}
			}
		}
	}
	caps, objs, done, e := c1collect.CaptureReferences(ctx, p, cp, wait)
	if e != nil {
		fail(3, e.Error())
	}
	if got == nil {
		select {
		case r := <-in:
			got = &r
		case <-ctx.Done():
			fail(3, "interrupted")
		case <-time.After(*caseWait):
			fail(3, "no cases")
		}
	}
	if len(got.b) == 0 {
		fail(3, gone.Error())
	}
	received := time.Now().UnixMilli()
	var cs struct {
		Cases []c1collect.Case `json:"cases"`
	}
	if e := json.Unmarshal(got.b, &cs); e != nil {
		fail(2, "cases: "+e.Error())
	}
	ph, sh, _ := c1collect.PolicyHashes(p.ReferenceTime)
	rec := c1collect.Record{Format: c1collect.JudgmentFormat, Plan: p, PolicyFrameHash: c1collect.FrameHash, PolicyHash: ph, SourceSetHash: sh,
		Captures: caps, RefsFinishedUnixMs: done, CasesReceivedMs: received}
	rec.Judgments = c1collect.Judge(ctx, p, caps, objs, cs.Cases, verifier.CastVerifier{Path: *cast}, cp.Verify)
	rec.JudgedUnixMs = time.Now().UnixMilli()
	emit(rec)
}

// rederive prints only counts: records, judgments re-derived, failures.
func rederive(args []string) {
	fs := flag.NewFlagSet("rederive", flag.ExitOnError)
	roots := fs.String("roots", "", "PEM file of trusted roots (default: system pool)")
	fs.Parse(args)
	opt := rootsOpt(*roots)
	records, judged := 0, 0
	var problems []string
	for _, f := range fs.Args() {
		b, e := os.ReadFile(f)
		var r c1collect.Record
		if e == nil {
			d := json.NewDecoder(strings.NewReader(string(b)))
			d.DisallowUnknownFields()
			e = d.Decode(&r)
		}
		n := 0
		if e == nil {
			n, e = c1collect.Rederive(r, opt)
		}
		records++
		judged += n
		if e != nil {
			problems = append(problems, filepath.Base(filepath.Dir(f))+"/"+filepath.Base(f)+": "+e.Error())
		}
	}
	emit(map[string]any{"records": records, "judgments_rederived": judged, "problems": problems})
	if len(problems) > 0 {
		os.Exit(1)
	}
}

func rootsOpt(path string) refsource.VerifyOptions {
	opt := refsource.VerifyOptions{}
	if path != "" {
		pem, e := os.ReadFile(path)
		if e != nil {
			fail(2, e.Error())
		}
		opt.Roots = x509.NewCertPool()
		if !opt.Roots.AppendCertsFromPEM(pem) {
			fail(2, "no certificates in "+path)
		}
	}
	return opt
}

// objects decodes every raw object in the given directories, checks that the
// file name carries its object ID prefix and verifies the recorded session.
func objects(args []string) {
	fs := flag.NewFlagSet("objects", flag.ExitOnError)
	roots := fs.String("roots", "", "PEM file of trusted roots (default: system pool)")
	fs.Parse(args)
	opt := rootsOpt(*roots)
	count := 0
	var problems []string
	for _, dir := range fs.Args() {
		names, _ := filepath.Glob(filepath.Join(dir, "*.json"))
		sort.Strings(names)
		for _, n := range names {
			// An instance directory also holds its judgment record, which
			// is not a raw object and stays closed here.
			if filepath.Base(n) == "judgment.json" {
				continue
			}
			count++
			o, e := refsource.Load(n)
			if e == nil {
				var id string
				if id, e = o.ObjectID(); e == nil && !strings.HasSuffix(filepath.Base(n), "-"+id[:16]+".json") {
					e = errors.New("file name does not carry the object ID")
				}
			}
			if e == nil {
				_, e = refsource.Verify(o, opt)
			}
			if e != nil {
				problems = append(problems, n+": "+e.Error())
			}
		}
	}
	emit(map[string]any{"objects": count, "problems": problems})
	if len(problems) > 0 {
		os.Exit(1)
	}
}
