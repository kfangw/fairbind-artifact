package integration

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/buyer"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/keeper"
)

var (
	ctx    = context.Background()
	binDir string
)

func repoRoot() string {
	_, file, _, _ := runtime.Caller(0)
	return filepath.Join(filepath.Dir(file), "..", "..", "..")
}

func TestMain(m *testing.M) {
	if os.Getenv("FAIRBIND_INTEGRATION") != "1" {
		fmt.Println("integration tests skipped; set FAIRBIND_INTEGRATION=1 (make integration-check)")
		os.Exit(0)
	}
	for _, tool := range []string{"anvil", "cast", "forge", "python3"} {
		if _, err := exec.LookPath(tool); err != nil {
			fmt.Fprintf(os.Stderr, "integration: %s not on PATH\n", tool)
			os.Exit(1)
		}
	}
	dir, err := os.MkdirTemp("", "fairbind-integration-bin")
	if err != nil {
		panic(err)
	}
	build := exec.Command("go", "build", "-o", dir+string(os.PathSeparator),
		"./services/keeper/cmd/fairbind-keeper", "./services/verifier/cmd/fairbind-verifier",
		"./services/facilitator/cmd/fairbind-facilitator", "./services/seller/cmd/fairbind-seller",
		"./services/buyer/cmd/fairbind-buyer")
	build.Dir, build.Stdout, build.Stderr = repoRoot(), os.Stderr, os.Stderr
	if err = build.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "integration: building the service binaries failed:", err)
		os.Exit(1)
	}
	binDir = dir
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

// Deployment is the part of deployment.json the tests read.
type Deployment struct {
	ChainID  uint64 `json:"chainId"`
	RPCURL   string `json:"rpcUrl"`
	Contract string `json:"contract"`
	Token    string `json:"token"`
	Build    string `json:"build"`
	Profiles []struct {
		ProfileID     uint32 `json:"profileId"`
		ParameterHash string `json:"parameterHash"`
	} `json:"profiles"`
	Seller struct {
		SellerID  uint32 `json:"sellerId"`
		BondID    uint32 `json:"bondId"`
		ProfileID uint32 `json:"profileId"`
		Owner     string `json:"owner"`
		URL       string `json:"url"`
	} `json:"seller"`
	Verifiers []struct {
		VerifierID uint32 `json:"verifierId"`
		Config     string `json:"config"`
	} `json:"verifiers"`
	Roles map[string]struct {
		Address string `json:"address"`
	} `json:"roles"`
	Services struct {
		Keeper, Facilitator, Seller, Buyer, Buyer2 string
		Verifiers                                  []string
	} `json:"services"`
	URLs       map[string]string `json:"urls"`
	SetupBlock uint64            `json:"setupBlock"`
}

// Env is one deployment with its running processes.
type Env struct {
	t        *testing.T
	RunDir   string
	D        Deployment
	View     *chain.RPC
	procs    map[string]*Proc
	mined    uint64
	contract protocol.Address
}

// Proc is one service subprocess.
type Proc struct {
	Name string
	Log  string
	cmd  *exec.Cmd
}

func freePort(t *testing.T) int {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

// deploy runs scripts/deploy-local.sh with a new Anvil and returns the
// deployment. Anvil reports finalized = head - 2 (--slots-in-an-epoch 1).
func deploy(t *testing.T, profileDoc string) *Env {
	t.Helper()
	run := t.TempDir()
	anvilPort := freePort(t)
	basePort := freePort(t) // the four service ports follow; collisions are unlikely on a test host
	cmd := exec.Command(filepath.Join(repoRoot(), "scripts", "deploy-local.sh"), profileDoc, run)
	cmd.Env = append(os.Environ(), "FAIRBIND_ANVIL_PORT="+strconv.Itoa(anvilPort),
		"FAIRBIND_ANVIL_ARGS=--slots-in-an-epoch 1", "FAIRBIND_BASE_PORT="+strconv.Itoa(basePort), "FAIRBIND_RPC_URL=")
	var out bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &out
	err := cmd.Run()
	t.Cleanup(func() {
		if raw, err := os.ReadFile(filepath.Join(run, "anvil.pid")); err == nil {
			if pid, err := strconv.Atoi(strings.TrimSpace(string(raw))); err == nil {
				syscall.Kill(pid, syscall.SIGTERM)
			}
		}
	})
	if err != nil {
		t.Fatalf("deploy-local.sh: %v\n%s", err, out.String())
	}
	e := &Env{t: t, RunDir: run, procs: map[string]*Proc{}}
	readJSON(t, filepath.Join(run, "deployment.json"), &e.D)
	e.contract = addr(t, e.D.Contract)
	if e.View, err = chain.NewRPC(ctx, chain.RPCConfig{URL: e.D.RPCURL, ChainID: e.D.ChainID, Contract: chain.Address(e.contract)}); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(e.stopAll)
	t.Logf("deployed %s build at %s, setup block %d, run directory %s", e.D.Build, e.D.Contract, e.D.SetupBlock, run)
	return e
}

func readJSON(t *testing.T, path string, v any) {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(raw, v); err != nil {
		t.Fatalf("%s: %v", path, err)
	}
}

func addr(t *testing.T, s string) protocol.Address {
	t.Helper()
	a, err := keeper.ParseHexAddress(strings.ToLower(s))
	if err != nil {
		t.Fatalf("address %q: %v", s, err)
	}
	return a
}

// Start launches a service binary with its configuration.
func (e *Env) Start(name, binary, config string) *Proc {
	e.t.Helper()
	logPath := filepath.Join(e.RunDir, "logs", name+".log")
	os.MkdirAll(filepath.Dir(logPath), 0o755)
	f, err := os.Create(logPath)
	if err != nil {
		e.t.Fatal(err)
	}
	cmd := exec.Command(filepath.Join(binDir, binary), "-config", config)
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

// Stop sends SIGTERM and waits; a process that does not exit is killed.
func (e *Env) Stop(name string) {
	p := e.procs[name]
	if p == nil {
		return
	}
	delete(e.procs, name)
	p.cmd.Process.Signal(syscall.SIGTERM)
	done := make(chan struct{})
	go func() { p.cmd.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		p.cmd.Process.Kill()
		<-done
	}
}

func (e *Env) stopAll() {
	for name := range e.procs {
		e.Stop(name)
	}
}

// StartAll starts the keeper, every verifier, the facilitator, the seller and
// the buyer, and waits until the HTTP services answer.
func (e *Env) StartAll() {
	e.t.Helper()
	e.Start("keeper", "fairbind-keeper", e.D.Services.Keeper)
	for i, v := range e.D.Verifiers {
		e.Start(fmt.Sprintf("verifier-%d", e.D.Verifiers[i].VerifierID), "fairbind-verifier", v.Config)
	}
	e.Start("facilitator", "fairbind-facilitator", e.D.Services.Facilitator)
	e.waitHTTP(e.D.URLs["facilitator"] + "/supported")
	e.Start("seller", "fairbind-seller", e.D.Services.Seller)
	e.waitHTTP(e.D.Seller.URL + "/fairbind/claims")
	e.Start("buyer", "fairbind-buyer", e.D.Services.Buyer)
	e.waitHTTP(e.D.URLs["buyer"] + "/purchases")
}

func (e *Env) waitHTTP(u string) {
	e.t.Helper()
	deadline := time.Now().Add(30 * time.Second)
	for time.Now().Before(deadline) {
		if resp, err := http.Get(u); err == nil {
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				return
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	e.dumpLogs()
	e.t.Fatalf("%s did not answer", u)
}

func (e *Env) dumpLogs() {
	for name, p := range e.procs {
		raw, _ := os.ReadFile(p.Log)
		lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
		if len(lines) > 15 {
			lines = lines[len(lines)-15:]
		}
		e.t.Logf("---- %s (last lines of %s)\n%s", name, p.Log, strings.Join(lines, "\n"))
	}
}

// LogContains reports whether a process log contains s.
func (e *Env) LogContains(name, s string) bool {
	raw, _ := os.ReadFile(filepath.Join(e.RunDir, "logs", name+".log"))
	return strings.Contains(string(raw), s)
}

// KeeperSent reports whether the keeper log records a sent transaction for action.
func (e *Env) KeeperSent(action string) bool {
	raw, _ := os.ReadFile(filepath.Join(e.RunDir, "logs", "keeper.log"))
	for _, line := range strings.Split(string(raw), "\n") {
		var l struct{ Action, Status string }
		if json.Unmarshal([]byte(line), &l) == nil && l.Action == action && l.Status == "sent" {
			return true
		}
	}
	return false
}

func (e *Env) rpc(method string, params ...any) json.RawMessage {
	e.t.Helper()
	body, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
	resp, err := http.Post(e.D.RPCURL, "application/json", bytes.NewReader(body))
	if err != nil {
		e.t.Fatal(err)
	}
	defer resp.Body.Close()
	var out struct {
		Result json.RawMessage `json:"result"`
		Error  any             `json:"error"`
	}
	if err = json.NewDecoder(resp.Body).Decode(&out); err != nil || out.Error != nil {
		e.t.Fatalf("%s: %v %v", method, err, out.Error)
	}
	return out.Result
}

// Head returns the latest block number.
func (e *Env) Head() uint64 {
	e.t.Helper()
	n, err := e.View.BlockNumber(ctx)
	if err != nil {
		e.t.Fatal(err)
	}
	return n
}

// Mine mines n empty blocks at once.
func (e *Env) Mine(n uint64) {
	// Anvil mines about 350 empty blocks a second; chunks keep each call short.
	const chunk = 2000
	began := time.Now()
	for left := n; left > 0; {
		k := min(left, chunk)
		e.rpc("anvil_mine", "0x"+strconv.FormatUint(k, 16))
		left -= k
	}
	e.mined += n
	if n > chunk {
		e.t.Logf("mined %d blocks in %s", n, time.Since(began).Round(time.Second))
	}
}

// MineTo mines until the head is at least b.
func (e *Env) MineTo(b uint64) {
	if h := e.Head(); h < b {
		e.Mine(b - h)
	}
}

// Wait polls cond until it holds. While waiting it mines one block per poll
// when mine is set, so that finalized views (head - 2) move forward.
func (e *Env) Wait(what string, timeout time.Duration, mine bool, cond func() (bool, string)) {
	e.t.Helper()
	deadline := time.Now().Add(timeout)
	last := ""
	for time.Now().Before(deadline) {
		ok, state := cond()
		if ok {
			e.t.Logf("ok at block %d: %s (%s)", e.Head(), what, state)
			return
		}
		last = state
		if mine {
			e.Mine(1)
		}
		time.Sleep(500 * time.Millisecond)
	}
	e.dumpLogs()
	e.t.Fatalf("timed out at block %d waiting for %s; last observed: %s", e.Head(), what, last)
}

// Balance returns the deployment token balance of an address.
func (e *Env) Balance(a string) *big.Int {
	e.t.Helper()
	out, err := exec.Command("cast", "call", "--rpc-url", e.D.RPCURL, e.D.Token, "balanceOf(address)(uint256)", a).Output()
	if err != nil {
		e.t.Fatal(err)
	}
	n, ok := new(big.Int).SetString(strings.Fields(string(out))[0], 10)
	if !ok {
		e.t.Fatalf("balance output %q", out)
	}
	return n
}

// Logs returns the logs of one event signature emitted by the contract.
func (e *Env) Logs(signature string) []struct {
	Topics []string `json:"topics"`
	Data   string   `json:"data"`
} {
	e.t.Helper()
	topic := protocol.Keccak256([]byte(signature))
	raw := e.rpc("eth_getLogs", map[string]any{"address": e.D.Contract, "fromBlock": "0x0", "toBlock": "latest",
		"topics": []string{x402.H32(topic).String()}})
	var logs []struct {
		Topics []string `json:"topics"`
		Data   string   `json:"data"`
	}
	if err := json.Unmarshal(raw, &logs); err != nil {
		e.t.Fatal(err)
	}
	return logs
}

// Word returns the i-th 32-byte word of hex log data.
func Word(data string, i int) *big.Int {
	d := strings.TrimPrefix(data, "0x")
	n, _ := new(big.Int).SetString(d[64*i:64*(i+1)], 16)
	return n
}

// CallWords calls a view of the contract at the latest block and returns the
// 32-byte words of its result. args are already 32-byte words.
func (e *Env) CallWords(signature string, args ...[]byte) []*big.Int {
	e.t.Helper()
	selector := protocol.Keccak256([]byte(signature))
	data := append([]byte(nil), selector[:4]...)
	for _, a := range args {
		data = append(data, a...)
	}
	raw := e.rpc("eth_call", map[string]string{"to": e.D.Contract, "data": "0x" + hex.EncodeToString(data)}, "latest")
	var out string
	if err := json.Unmarshal(raw, &out); err != nil {
		e.t.Fatal(err)
	}
	var words []*big.Int
	for i := 0; i < (len(out)-2)/64; i++ {
		words = append(words, Word(out[2:], i))
	}
	return words
}

// CaseView is the part of getCase the tests read beyond chain.Case.
type CaseView struct {
	State, Stage, Attempt, InitialVerdict, FinalVerdict uint8
	AssignedVerifierID                                  uint32
	RandomBlock, JudgeDue                               uint64
}

func (e *Env) CaseDetail(nonce protocol.Bytes32) CaseView {
	w := e.CallWords("getCase(bytes32)", nonce[:])
	return CaseView{State: uint8(w[15].Uint64()), Stage: uint8(w[19].Uint64()), Attempt: uint8(w[20].Uint64()),
		InitialVerdict: uint8(w[21].Uint64()), FinalVerdict: uint8(w[22].Uint64()),
		AssignedVerifierID: uint32(w[12].Uint64()), RandomBlock: w[9].Uint64(), JudgeDue: w[10].Uint64()}
}

// SealDeadline reads getAnchor(sellerId, epoch).sealDeadline.
func (e *Env) SealDeadline(epoch uint32) uint64 {
	w := e.CallWords("getAnchor(uint32,uint24)", word(uint64(e.D.Seller.SellerID)), word(uint64(epoch)))
	return w[7].Uint64()
}

func word(v uint64) []byte {
	b := make([]byte, 32)
	new(big.Int).SetUint64(v).FillBytes(b)
	return b
}

func (e *Env) Purchase(nonce protocol.Bytes32) chain.Purchase {
	e.t.Helper()
	p, err := e.View.GetPurchase(ctx, nonce)
	if err != nil {
		e.t.Fatal(err)
	}
	return p
}

func (e *Env) PurchaseState(nonce protocol.Bytes32) uint8 {
	e.t.Helper()
	s, err := e.View.PurchaseState(ctx, nonce)
	if err != nil {
		e.t.Fatal(err)
	}
	return s
}

func (e *Env) Case(nonce protocol.Bytes32) chain.Case {
	e.t.Helper()
	c, err := e.View.GetCase(ctx, nonce)
	if err != nil {
		e.t.Fatal(err)
	}
	return c
}

func (e *Env) Anchor(epoch uint32) chain.Anchor {
	e.t.Helper()
	a, err := e.View.GetAnchor(ctx, e.D.Seller.SellerID, epoch)
	if err != nil {
		e.t.Fatal(err)
	}
	return a
}

func (e *Env) Bond() chain.Bond {
	e.t.Helper()
	b, err := e.View.GetBond(ctx, e.D.Seller.BondID)
	if err != nil {
		e.t.Fatal(err)
	}
	return b
}

func (e *Env) Profile() chain.Profile {
	e.t.Helper()
	p, err := e.View.GetProfile(ctx, e.D.Seller.ProfileID)
	if err != nil {
		e.t.Fatal(err)
	}
	return p
}

// Buy posts a purchase to a buyer control API and returns the record.
func (e *Env) Buy(buyerURL, resourceURL string) *buyer.Record {
	e.t.Helper()
	// Every canonical header of the profile (accept, content-type, x-model) must be present.
	req := buyer.Request{Method: "GET", URL: resourceURL,
		Headers: [][2]string{{"Accept", "application/json"}, {"Content-Type", "application/json"}, {"X-Model", "quote-v1"}}}
	body, _ := json.Marshal(req)
	resp, err := http.Post(buyerURL+"/purchases", "application/json", bytes.NewReader(body))
	if err != nil {
		e.t.Fatal(err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	var r buyer.Record
	if resp.StatusCode != http.StatusOK || json.Unmarshal(raw, &r) != nil {
		e.dumpLogs()
		e.t.Fatalf("purchase answered %d: %s", resp.StatusCode, raw)
	}
	return &r
}

// BuyerRecord reads a purchase record from a buyer's data directory.
func (e *Env) BuyerRecord(role string, key x402.H16) buyer.Record {
	e.t.Helper()
	files, _ := filepath.Glob(filepath.Join(e.RunDir, "services", role, "data", "purchases", "*.json"))
	for _, f := range files {
		var r buyer.Record
		readJSON(e.t, f, &r)
		if r.Key == key {
			return r
		}
	}
	e.t.Fatalf("%s has no record for %s", role, key)
	return buyer.Record{}
}

// SellerRecord reads the seller's purchase record for a nonce.
func (e *Env) SellerRecord(nonce protocol.Bytes32) map[string]any {
	e.t.Helper()
	var r map[string]any
	readJSON(e.t, filepath.Join(e.RunDir, "services", "seller", "data", "purchases", x402.H32(nonce).String()+".json"), &r)
	return r
}

// withholdProxy forwards to the seller but, while armed, drops the answer
// to paid requests: the seller settles and responds, the buyer never sees it.
type withholdProxy struct {
	target *url.URL
	armed  atomic.Bool
	srv    *httptest.Server
}

func newWithholdProxy(t *testing.T, seller string) *withholdProxy {
	u, err := url.Parse(seller)
	if err != nil {
		t.Fatal(err)
	}
	p := &withholdProxy{target: u}
	p.srv = httptest.NewServer(p)
	t.Cleanup(p.srv.Close)
	return p
}

func (p *withholdProxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	out, err := http.NewRequestWithContext(r.Context(), r.Method, p.target.String()+r.URL.RequestURI(), r.Body)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	out.Header = r.Header.Clone()
	resp, err := http.DefaultTransport.RoundTrip(out)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if p.armed.Load() && r.Header.Get(x402.HeaderPaymentSignature) != "" && resp.StatusCode/100 == 2 {
		http.Error(w, "response withheld", http.StatusBadGateway)
		return
	}
	for k, vs := range resp.Header {
		for _, v := range vs {
			w.Header().Add(k, v)
		}
	}
	w.WriteHeader(resp.StatusCode)
	w.Write(body)
}
