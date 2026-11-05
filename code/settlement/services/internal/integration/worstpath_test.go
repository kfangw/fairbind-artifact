package integration

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/buyer"
	"example.org/fairbind/services/internal/casepath"
	"example.org/fairbind/services/internal/x402"
)

// Worst-path dry run of the service harness: the services carry out the
// worst-path directives of experiments/controller/worstpath.py on one sampled
// bad sale, and the harness measures L (settlement block to confirmed-failure
// block) and the keeper delay sum kappa_Sigma, to compare with L_actual of
// experiments/operating-point.json, measured on the contract alone by
// contracts/test/WorstPathLength.t.sol.
//
// The harness only advances the chain. It mines to the block before each
// deadline the case, epoch or review view names (and to the deadline itself,
// for calls due in the block after it), then waits until every service has
// completed a pass at that head and no transaction is pending, so that a call a
// service times to the next block lands in it.

// directiveFiles writes one directive file per role with the blocks the
// controller builds (experiments/controller/runner.py): worst_path for the
// verifier, seller, keeper and buyer, and keeper_delay for the keeper.
func directiveFiles(t *testing.T, profileDoc string, profileID int, kappa uint64) map[string]string {
	t.Helper()
	dir := t.TempDir()
	script := `
import json, sys
sys.path.insert(0, 'experiments')
from controller import worstpath
doc = json.load(open(sys.argv[1]))
profile = next(p for p in doc['profiles'] if p['profileId'] == int(sys.argv[2]))
blocks = worstpath.directives(profile)
for role, block in blocks.items():
    d = dict(seed=1, kind='hold_period_grid', parameters={'keeper_delay_budget_blocks': int(sys.argv[3])}, worst_path=block)
    if role == 'keeper':
        d['keeper_delay'] = worstpath.keeper_delay(int(sys.argv[3]))
    json.dump(d, open(sys.argv[4] + '/' + role + '.json', 'w'), indent=2)
print(json.dumps(worstpath.schedule(profile)))
`
	cmd := exec.Command("python3", "-c", script, profileDoc, strconv.Itoa(profileID), strconv.FormatUint(kappa, 10), dir)
	cmd.Dir = repoRoot()
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("worst-path directives: %v\n%s", err, out)
	}
	t.Logf("worst-path schedule: %s", strings.TrimSpace(string(out)))
	files := map[string]string{}
	for _, role := range []string{"verifier", "seller", "keeper", "buyer"} {
		files[role] = filepath.Join(dir, role+".json")
	}
	return files
}

// setPoll rewrites one polling field of a service configuration.
func setPoll(t *testing.T, path, field string, value int) {
	t.Helper()
	var cfg map[string]any
	readJSON(t, path, &cfg)
	cfg[field] = value
	raw, _ := json.MarshalIndent(cfg, "", "  ")
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatal(err)
	}
}

// StartArgs launches a service binary with explicit arguments.
func (e *Env) StartArgs(name, binary string, args ...string) *Proc {
	e.t.Helper()
	logPath := filepath.Join(e.RunDir, "logs", name+".log")
	os.MkdirAll(filepath.Dir(logPath), 0o755)
	f, err := os.Create(logPath)
	if err != nil {
		e.t.Fatal(err)
	}
	cmd := exec.Command(filepath.Join(binDir, binary), args...)
	cmd.Dir, cmd.Stdout, cmd.Stderr = repoRoot(), f, f
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err = cmd.Start(); err != nil {
		e.t.Fatal(err)
	}
	f.Close()
	p := &Proc{Name: name, Log: logPath, cmd: cmd}
	e.procs[name] = p
	return p
}

// pacer advances the chain from deadline to deadline while the directed
// services act.
type pacer struct {
	e        *Env
	progress []string
	nonce    protocol.Bytes32
	epoch    uint32
	kappa    uint64
	halts    int
}

// startDirected starts every service with its directive and a progress file.
func (e *Env) startDirected(files map[string]string) *pacer {
	e.t.Helper()
	pd := filepath.Join(e.RunDir, "progress")
	os.MkdirAll(pd, 0o755)
	p := &pacer{e: e}
	prog := func(name string) string {
		f := filepath.Join(pd, name+".json")
		p.progress = append(p.progress, f)
		return f
	}
	setPoll(e.t, e.D.Services.Keeper, "pollIntervalMs", 200)
	e.StartArgs("keeper", "fairbind-keeper", "-config", e.D.Services.Keeper, "-directive", files["keeper"], "-progress", prog("keeper"))
	for _, v := range e.D.Verifiers {
		name := fmt.Sprintf("verifier-%d", v.VerifierID)
		e.StartArgs(name, "fairbind-verifier", "-config", v.Config, "-directive", files["verifier"], "-progress", prog(name))
	}
	e.Start("facilitator", "fairbind-facilitator", e.D.Services.Facilitator)
	e.waitHTTP(e.D.URLs["facilitator"] + "/supported")
	e.StartArgs("seller", "fairbind-seller", "-config", e.D.Services.Seller, "-directive", files["seller"], "-progress", prog("seller"))
	e.waitHTTP(e.D.Seller.URL + "/fairbind/claims")
	e.StartArgs("buyer", "fairbind-buyer", "-config", e.D.Services.Buyer, "-directive", files["buyer"])
	e.waitHTTP(e.D.URLs["buyer"] + "/purchases")
	return p
}

func (p *pacer) reported() (uint64, string) {
	low := ^uint64(0)
	who := ""
	for _, f := range p.progress {
		var v struct{ Head uint64 }
		raw, err := os.ReadFile(f)
		if err != nil || json.Unmarshal(raw, &v) != nil {
			return 0, filepath.Base(f)
		}
		if v.Head < low {
			low, who = v.Head, filepath.Base(f)
		}
	}
	return low, who
}

// settle waits until every directed service completed a pass at the current
// head and the head did not move meanwhile (no call was sent).
func (p *pacer) settle() uint64 {
	p.e.t.Helper()
	deadline := time.Now().Add(90 * time.Second)
	for time.Now().Before(deadline) {
		h := p.e.Head()
		low, _ := p.reported()
		if low >= h {
			if p.e.Head() == h {
				return h
			}
			continue
		}
		time.Sleep(50 * time.Millisecond)
	}
	low, who := p.reported()
	p.e.dumpLogs()
	p.e.t.Fatalf("services did not report head %d (lowest %d from %s)", p.e.Head(), low, who)
	return 0
}

// view is the state the pacer derives deadlines from.
type view struct {
	caseWords, reviewWords, anchorWords []uint64
	reseals                             uint64
}

func (p *pacer) read() view {
	e := p.e
	var v view
	for _, w := range e.CallWords("getCase(bytes32)", p.nonce[:]) {
		v.caseWords = append(v.caseWords, w.Uint64())
	}
	for _, w := range e.CallWords("getReview(bytes32)", p.nonce[:]) {
		v.reviewWords = append(v.reviewWords, w.Uint64())
	}
	for _, w := range e.CallWords("getAnchor(uint32,uint24)", word(uint64(e.D.Seller.SellerID)), word(uint64(p.epoch))) {
		v.anchorWords = append(v.anchorWords, w.Uint64())
	}
	v.reseals = e.CallWords("getReviewReseals(bytes32)", p.nonce[:])[0].Uint64()
	return v
}

func (v view) key() string {
	return fmt.Sprint(v.caseWords, v.reviewWords, v.anchorWords, v.reseals)
}

// stops returns the blocks the pacer halts at: the block before every pending
// deadline and the deadline itself, each also shifted by kappa.
func (p *pacer) stops(v view, head uint64) []uint64 {
	prof := p.e.Profile()
	d := prof.Deadlines
	var ds []uint64
	switch v.anchorWords[11] {
	case 0:
		ds = append(ds, prof.AnchorDeadline(p.epoch))
	case 1, 2:
		ds = append(ds, v.anchorWords[7], v.anchorWords[7]+uint64(d.OpenBlocks))
	}
	c := v.caseWords
	// serveDue, challengeUntil, publishDue, judgeDue, evidenceDue, appealUntil
	ds = append(ds, c[6], c[7], c[8], c[10], c[11], v.reviewWords[0])
	if c[9] != 0 {
		ds = append(ds, c[9], c[9]+uint64(d.SealBlocks))
	}
	set := map[uint64]bool{}
	for _, x := range ds {
		if x == 0 {
			continue
		}
		for _, s := range []uint64{x - 1, x, x - 1 + p.kappa, x + p.kappa} {
			if s > head {
				set[s] = true
			}
		}
	}
	var out []uint64
	for s := range set {
		out = append(out, s)
	}
	sort.Slice(out, func(i, j int) bool { return out[i] < out[j] })
	return out
}

// run advances until the case is final or the limit is reached.
func (p *pacer) run(limit uint64) {
	e := p.e
	e.t.Helper()
	for {
		head := p.settle()
		v := p.read()
		if v.caseWords[15] == uint64(caseFinal) {
			return
		}
		st := p.stops(v, head)
		if len(st) == 0 || st[0] > limit {
			e.dumpLogs()
			e.t.Fatalf("no pending deadline at block %d (case %v)", head, v.caseWords)
		}
		e.MineTo(st[0])
		p.halts++
		for {
			h := p.settle()
			nv := p.read()
			if nv.key() == v.key() && h == e.Head() {
				break
			}
			v = nv
		}
	}
}

type dryRun struct {
	Kappa    uint64
	Settled  uint64
	Final    uint64
	L        uint64
	KappaSum uint64
	Minus    int64
	Worst    bool
	Mismatch []string
	Calls    []casepath.Delay
}

// runWorstPath deploys the profile document, starts the directed services,
// settles one purchase in the first block of an epoch and paces the chain
// until its case is final.
func runWorstPath(t *testing.T, profileDoc string, profileID int, kappa uint64) dryRun {
	files := directiveFiles(t, profileDoc, profileID, kappa)
	// Every assignment of a case needs a verifier that has not taken part in
	// it, drawn within minVerifiers rounds; the worst path makes 3 *
	// maxAssignments = 9 assignments. At the admitted minimum of 14 verifiers
	// the last draw misses with probability (8/14)^14, about 4e-4 (ADR 0023);
	// register 40, as contracts/test/WorstPathLength.t.sol does, for (8/40)^14.
	t.Setenv("FAIRBIND_VERIFIERS", "40")
	e := deploy(t, profileDoc)
	if keep := os.Getenv("FAIRBIND_KEEP_LOGS"); keep != "" {
		// Runs before the run directory is removed: keep the service logs.
		t.Cleanup(func() {
			dst := filepath.Join(keep, strings.NewReplacer("/", "_", "=", "_").Replace(t.Name()))
			exec.Command("cp", "-r", filepath.Join(e.RunDir, "logs"), dst).Run()
		})
	}
	p := e.startDirected(files)
	prof := e.Profile()
	// The seller pays the appeal deposit from its owner account.
	owner := e.D.Seller.Owner
	for _, args := range [][]string{{"mint(address,uint256)", owner, "1000000000000"}, {"approve(address,uint256)", e.D.Contract, "1000000000000"}} {
		cmd := exec.Command("cast", append([]string{"send", "--rpc-url", e.D.RPCURL, "--unlocked", "--from", owner, e.D.Token}, args...)...)
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("cast send %v: %v\n%s", args, err, out)
		}
	}
	// Settle in the first block of an epoch: the epoch boundary is as late as it can be.
	next := prof.EpochAt(e.Head()+3) + 1
	start := prof.EpochStart(next)
	e.MineTo(start - 1)
	r := e.Buy(e.D.URLs["buyer"], quoteURL(e.D.Seller.URL))
	if r.State != buyer.StateReceived || r.Nonce == nil {
		e.dumpLogs()
		t.Fatalf("purchase state %s (%s)", r.State, r.Reason)
	}
	p.nonce = protocol.Bytes32(*r.Nonce)
	pur := e.Purchase(p.nonce)
	p.epoch, p.kappa = pur.Epoch, kappa
	if pur.SettledBlock != start {
		t.Errorf("settled at block %d, not at the epoch start %d", pur.SettledBlock, start)
	}
	t.Logf("settled %s at block %d (epoch %d starts at %d)", x402.H32(p.nonce), pur.SettledBlock, pur.Epoch, start)
	began := time.Now()
	p.run(pur.SettledBlock + 200_000)
	c := e.CaseDetail(p.nonce)
	if c.FinalVerdict != 2 { // FAIL
		e.dumpLogs()
		t.Fatalf("final verdict %d, want FAIL", c.FinalVerdict)
	}
	f, err := os.Open(filepath.Join(e.RunDir, "logs", "keeper.log"))
	if err != nil {
		t.Fatal(err)
	}
	calls, err := casepath.ParseKeeperLog(f)
	f.Close()
	if err != nil {
		t.Fatal(err)
	}
	cases, err := casepath.Collect(ctx, casepath.NewRPC(e.D.RPCURL, e.D.Contract), e.D.Seller.SellerID, calls)
	if err != nil {
		t.Fatal(err)
	}
	if len(cases) != 1 {
		t.Fatalf("%d effective-detection cases", len(cases))
	}
	cs := cases[0]
	obs, err := os.Create(filepath.Join(e.RunDir, "observations.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	casepath.WriteRows(obs, casepath.Rows(fmt.Sprintf("dry-run-kappa-%d", kappa), cases, true))
	obs.Close()
	t.Logf("case final at block %d after %d pacer stops in %s; observations in %s", cs.ConfirmedBlock, p.halts,
		time.Since(began).Round(time.Second), filepath.Join(e.RunDir, "observations.jsonl"))
	for _, k := range cs.KeeperCalls {
		t.Logf("  keeper %-22s due %6d at %6d delay %d", k.Action, k.Due-cs.SettledBlock, k.Block-cs.SettledBlock, k.Delay)
	}
	return dryRun{Kappa: kappa, Settled: cs.SettledBlock, Final: cs.ConfirmedBlock,
		L: cs.CasePathBlocks, KappaSum: cs.KeeperDelaySum, Minus: cs.CasePathMinusKeeper, Worst: cs.WorstPath,
		Mismatch: cs.WorstPathMismatch, Calls: cs.KeeperCalls}
}

// TestWorstPathDirectiveDataAPI is the dry run of the worst-path directives on
// data-api-fast-v1 with forced sampling: kappa = 0 must reproduce L_actual =
// 29,680 blocks and kappa = 100 must lengthen it by exactly kappa.
func TestWorstPathDirectiveDataAPI(t *testing.T) {
	const lActual = 29_680
	doc := forcedSampleProfile(t)
	for _, kappa := range []uint64{0, 100} {
		t.Run(fmt.Sprintf("kappa=%d", kappa), func(t *testing.T) {
			r := runWorstPath(t, doc, 3, kappa)
			t.Logf("RESULT profile=data-api-fast-v1 kappa=%d L=%d kappa_sigma=%d L_minus_kappa=%d worst_path=%v expected_L=%d",
				kappa, r.L, r.KappaSum, r.Minus, r.Worst, lActual+kappa)
			if !r.Worst {
				t.Errorf("case left the worst path: %v", r.Mismatch)
			}
			if r.KappaSum != kappa {
				t.Errorf("kappa_Sigma %d, want %d", r.KappaSum, kappa)
			}
			if r.L != lActual+kappa {
				t.Errorf("L = %d, want %d", r.L, lActual+kappa)
			}
		})
	}
}

// openWeightsTimingProfile writes a profile document with the parameters of
// open-weights-standard-v1 of profiles/local-evaluation-v1.json (epoch, every
// deadline, maxAssignments, margin and windows, and its amounts), judged as a
// data-api service: classId 1 and the experimental decimal-median predicate,
// which the verifiers run over the replay fixtures, since the local deployment
// has no open-weights seller route or inference pipeline. The worst-path length
// depends only on the epoch, the deadlines and maxAssignments. samplePpm = PPM
// and recheckPpm = 0 as in forcedSampleProfile.
func openWeightsTimingProfile(t *testing.T) string {
	var doc map[string]any
	readJSON(t, filepath.Join(repoRoot(), "profiles", "local-evaluation-v1.json"), &doc)
	var keep []any
	for _, p := range doc["profiles"].([]any) {
		pm := p.(map[string]any)
		if pm["profileId"].(float64) != 4 {
			continue
		}
		params := pm["parameters"].(map[string]any)
		params["classId"] = 1
		params["samplePpm"] = ppm
		params["recheckPpm"] = 0
		params["predicateId"] = experimentalDataPredicate
		pm["name"] = "open-weights-standard-v1-timing-data-predicate"
		keep = append(keep, pm)
	}
	doc["profiles"] = keep
	doc["derivedFrom"] = "profiles/local-evaluation-v1.json open-weights-standard-v1: classId=1, samplePpm=1000000, recheckPpm=0, predicateId=" + experimentalDataPredicate
	path := filepath.Join(t.TempDir(), "profile.json")
	raw, _ := json.MarshalIndent(doc, "", "  ")
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

// TestWorstPathDirectiveOpenWeightsTiming is the dry run on the windows of
// open-weights-standard-v1: kappa = 0 must reproduce L_actual = 91,180 blocks.
func TestWorstPathDirectiveOpenWeightsTiming(t *testing.T) {
	const lActual = 91_180
	r := runWorstPath(t, openWeightsTimingProfile(t), 4, 0)
	t.Logf("RESULT profile=open-weights-standard-v1(timing) kappa=0 L=%d kappa_sigma=%d L_minus_kappa=%d worst_path=%v expected_L=%d",
		r.L, r.KappaSum, r.Minus, r.Worst, lActual)
	if !r.Worst {
		t.Errorf("case left the worst path: %v", r.Mismatch)
	}
	if r.KappaSum != 0 || r.L != lActual {
		t.Errorf("L = %d, kappa_Sigma = %d, want %d and 0", r.L, r.KappaSum, lActual)
	}
}
