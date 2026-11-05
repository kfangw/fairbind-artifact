// Command refcapture captures raw replay objects from the registered reference
// sources, or replays a directory of saved objects, and prints the resulting
// observations.
//
//	go run ./runtime/dataworker/refsource/cmd/refcapture -out DIR
//	go run ./runtime/dataworker/refsource/cmd/refcapture -replay DIR -reference-time UNIX
package main

import (
	"context"
	"crypto/x509"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"example.org/fairbind/runtime/dataworker"
	"example.org/fairbind/runtime/dataworker/refsource"
)

func main() {
	out := flag.String("out", "", "directory for captured raw objects (live mode)")
	replay := flag.String("replay", "", "directory of saved raw objects (replay mode)")
	sources := flag.String("sources", "", "comma-separated source IDs (default: all registered)")
	refTime := flag.Uint64("reference-time", 0, "reference time in Unix seconds for replay selection (default: now)")
	roots := flag.String("roots", "", "PEM file of trusted roots (default: system pool)")
	synthetic := flag.Bool("allow-synthetic", false, "accept synthetic test objects in replay mode")
	timeout := flag.Duration("timeout", 15*time.Second, "per-source capture timeout")
	flag.Parse()
	if (*out == "") == (*replay == "") {
		fail("exactly one of -out or -replay is required")
	}
	reg := refsource.DefaultRegistry()
	ids := strings.Split(*sources, ",")
	if *sources == "" {
		ids = ids[:0]
		for id := range reg {
			ids = append(ids, id)
		}
		sort.Strings(ids)
	}
	opt := refsource.VerifyOptions{AllowSynthetic: *synthetic}
	if *roots != "" {
		pem, e := os.ReadFile(*roots)
		if e != nil {
			fail(e.Error())
		}
		opt.Roots = x509.NewCertPool()
		if !opt.Roots.AppendCertsFromPEM(pem) {
			fail("no certificates in " + *roots)
		}
	}
	p := refsource.Provider{Registry: reg, Verify: opt, AllowPartial: true}
	var records []refsource.Record
	p.OnRecord = func(r refsource.Record) { records = append(records, r) }
	t := *refTime
	if t == 0 {
		t = uint64(time.Now().Unix())
	}
	if *out != "" {
		proxy, e := refsource.ProxyFromEnvironment()
		if e != nil {
			fail(e.Error())
		}
		p.Retriever = refsource.Live{Capturer: refsource.Capturer{Roots: opt.Roots, Timeout: *timeout, Proxy: proxy}}
		p.Sink = &refsource.DirSink{Dir: *out}
	} else {
		r, e := refsource.LoadReplay(*replay, opt)
		if e != nil {
			fail(e.Error())
		}
		p.Retriever = r
	}
	_, err := p.Retrieve(context.Background(), dataworker.SourceSet{Sources: ids}, t)
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	enc.Encode(map[string]any{"reference_time": t, "records": records})
	if err != nil {
		fmt.Fprintln(os.Stderr, "refcapture:", err)
		os.Exit(1)
	}
	for _, r := range records {
		if r.Error != "" {
			os.Exit(1)
		}
	}
}

func fail(msg string) {
	fmt.Fprintln(os.Stderr, "refcapture:", msg)
	os.Exit(2)
}
