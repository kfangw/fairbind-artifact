package integration

import (
	"encoding/json"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"testing"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/buyer"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
)

// Case states and verdicts beyond those in the chain package
// (contract-interface-v1 section 2).
const (
	caseInitialVerdict uint8 = 6
	caseFinal          uint8 = 13
	verdictPass        uint8 = 1
	freezeClaimClosed  uint8 = 3
	ppm                      = 1_000_000
)

// experimentalDataPredicate is the decimal-median predicate the verifiers'
// data pipeline is registered under (runtime/dataworker.PolicyID).
const experimentalDataPredicate = "0x1a320b649fe0216a2d3ed2e6692f214cc0784cd6ec04bf3ef6cd230418f3ddd7"

// forcedSampleProfile writes a profile document with the data-api profile of
// profiles/local-evaluation-v1.json, changed in samplePpm = PPM (every
// purchase is sampled), recheckPpm = 0 (a PASS is not rechecked, so the path
// has one judgment) and predicateId = the experimental decimal-median
// predicate, which the verifiers judge with the data pipeline over the replay
// fixtures (scripts/local_setup.py). The normative DATA_API_REFERENCE_V1 has
// no pipeline and would be judged INCONCLUSIVE. All three are admitted by the
// production registry; the deploy step recomputes parameterHash.
func forcedSampleProfile(t *testing.T) string {
	var doc map[string]any
	readJSON(t, filepath.Join(repoRoot(), "profiles", "local-evaluation-v1.json"), &doc)
	profiles := doc["profiles"].([]any)
	var keep []any
	for _, p := range profiles {
		pm := p.(map[string]any)
		if pm["profileId"].(float64) != 3 {
			continue
		}
		params := pm["parameters"].(map[string]any)
		params["samplePpm"] = ppm
		params["recheckPpm"] = 0
		params["predicateId"] = experimentalDataPredicate
		pm["name"] = "data-api-fast-v1-forced-sample"
		keep = append(keep, pm)
	}
	doc["profiles"] = keep
	doc["derivedFrom"] = "profiles/local-evaluation-v1.json: samplePpm=1000000, recheckPpm=0, predicateId=" + experimentalDataPredicate
	path := filepath.Join(t.TempDir(), "profile.json")
	raw, _ := json.MarshalIndent(doc, "", "  ")
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func quoteURL(base string) string { return base + "/v1/quote?symbol=ETH-USD" }

// TestNormalPathSampledPass drives one purchase through settlement, receipt,
// anchor, seal, sampling, a PASS verdict, the deferral and release.
func TestNormalPathSampledPass(t *testing.T) {
	e := deploy(t, forcedSampleProfile(t))
	start := e.Head()
	e.StartAll()
	prof := e.Profile()
	owner := e.D.Seller.Owner
	buyerAddr := e.D.Roles["buyer"].Address
	sellerBefore, buyerBefore := e.Balance(owner), e.Balance(buyerAddr)

	// 402 -> payment -> settle -> response and receipt.
	r := e.Buy(e.D.URLs["buyer"], quoteURL(e.D.Seller.URL))
	if r.State != buyer.StateReceived || r.Nonce == nil || r.Receipt == nil {
		e.dumpLogs()
		t.Fatalf("purchase state %s (%s)", r.State, r.Reason)
	}
	nonce := protocol.Bytes32(*r.Nonce)
	p := e.Purchase(nonce)
	if !p.Exists() || p.FinancialState != chain.FinDeferred || p.Value != 10_000 {
		t.Fatalf("purchase after settle: %+v", p)
	}
	if got := new(big.Int).Sub(buyerBefore, e.Balance(buyerAddr)); got.Cmp(big.NewInt(int64(p.Value))) != 0 {
		t.Fatalf("buyer paid %s, want %d", got, p.Value)
	}
	if s := e.SellerRecord(nonce); s["state"] != "delivered" || s["receipt"] == nil {
		t.Fatalf("seller record %v", s["state"])
	}
	if br := e.BuyerRecord("buyer", r.Key); br.State != buyer.StateReceived || br.Response == nil {
		t.Fatalf("buyer record %s", br.State)
	}
	t.Logf("settled %s at block %d in epoch %d (value %d)", x402.H32(nonce), p.SettledBlock, p.Epoch, p.Value)

	// Anchor: the seller anchors in the window after the next epoch.
	e.MineTo(prof.AnchorBase(p.Epoch))
	e.Wait("anchor", 60*time.Second, false, func() (bool, string) {
		a := e.Anchor(p.Epoch)
		return a.State == chain.EpochAnchored, fmt.Sprintf("anchor state %d", a.State)
	})
	a := e.Anchor(p.Epoch)
	if a.Count != 1 {
		t.Fatalf("anchor count %d", a.Count)
	}
	e.Wait("buyer inclusion proof", 30*time.Second, false, func() (bool, string) {
		br := e.BuyerRecord("buyer", r.Key)
		return br.State == buyer.StateProven, br.State
	})

	// Seal after the beacon block; the keeper seals, opens the sample and assigns.
	e.MineTo(a.RandomBlock + 1)
	e.Wait("seal", 60*time.Second, true, func() (bool, string) {
		a := e.Anchor(p.Epoch)
		return a.State == chain.EpochSealed, fmt.Sprintf("anchor state %d", a.State)
	})
	e.Wait("sample opened and verifier assigned", 60*time.Second, true, func() (bool, string) {
		c := e.Case(nonce)
		return c.State == chain.CaseJudging && c.AssignedVerifierID != 0, fmt.Sprintf("case state %d verifier %d", c.State, c.AssignedVerifierID)
	})
	if !e.KeeperSent("seal") || !e.KeeperSent("openSample") {
		t.Fatal("keeper log does not show seal and openSample")
	}
	c := e.CaseDetail(nonce)
	if st := e.PurchaseState(nonce); st != chain.FinHeld {
		t.Fatalf("purchase state %s after openSample, want HELD", chain.FinancialStateName(st))
	}
	vname := fmt.Sprintf("verifier-%d", c.AssignedVerifierID)
	t.Logf("case opened by sampling; verifier %d assigned, judgeDue %d", c.AssignedVerifierID, c.JudgeDue)

	// The assigned verifier redelivers from the seller and judges.
	judged := false
	deadline := time.Now().Add(90 * time.Second)
	for time.Now().Before(deadline) {
		if e.Case(nonce).State == caseInitialVerdict {
			judged = true
			break
		}
		if e.Head()+8 < c.JudgeDue {
			e.Mine(1)
		}
		time.Sleep(500 * time.Millisecond)
	}
	if !judged {
		var vs map[string]any
		readJSON(t, filepath.Join(e.RunDir, "services", "verifier", fmt.Sprint(c.AssignedVerifierID), "state", "state.json"), &vs)
		e.dumpLogs()
		t.Fatalf("verifier %d did not judge before block %d; case state %d; verifier state %v; log %s",
			c.AssignedVerifierID, e.Head(), e.Case(nonce).State, vs["entries"], filepath.Join(e.RunDir, "logs", vname+".log"))
	}
	c = e.CaseDetail(nonce)
	if c.InitialVerdict != verdictPass {
		e.dumpLogs()
		t.Fatalf("initial verdict %d, want PASS (log of %s)", c.InitialVerdict, vname)
	}
	t.Logf("initial verdict PASS by verifier %d at block %d", c.AssignedVerifierID, e.Head())

	// Appeal window, then the keeper's openAutoRecheck finalizes (recheckPpm = 0).
	// While an initial verdict waits, randomBlock = appealUntil + 1.
	e.MineTo(c.RandomBlock + 2)
	e.Wait("case final", 60*time.Second, true, func() (bool, string) {
		c := e.CaseDetail(nonce)
		return c.State == caseFinal, fmt.Sprintf("case state %d", c.State)
	})
	if c = e.CaseDetail(nonce); c.FinalVerdict != verdictPass {
		t.Fatalf("final verdict %d", c.FinalVerdict)
	}

	// Deferral: release needs claimUntil, the sample open window, releaseBlock and retainUntil.
	p = e.Purchase(nonce)
	release := max(p.ClaimUntil+1, p.ReleaseBlock, p.RetainUntil, e.SealDeadline(p.Epoch)+uint64(prof.Deadlines.OpenBlocks)+1)
	e.MineTo(release - 3)
	if st := e.PurchaseState(nonce); st == chain.FinReleased {
		t.Fatalf("released before the deferral ended")
	}
	e.MineTo(release)
	e.Wait("release", 60*time.Second, true, func() (bool, string) {
		st := e.PurchaseState(nonce)
		return st == chain.FinReleased, chain.FinancialStateName(st)
	})
	if got := new(big.Int).Sub(e.Balance(owner), sellerBefore); got.Cmp(big.NewInt(int64(p.Value))) != 0 {
		t.Fatalf("seller paid %s, want %d", got, p.Value)
	}
	t.Logf("normal path: %d blocks from setup to release (%d mined explicitly)", e.Head()-start, e.mined)
}

// TestNonDeliveryUnservedRefundAndForfeit withholds a response, lets the
// seller fail to serve, refunds the buyer, and forfeits the frozen remainder.
func TestNonDeliveryUnservedRefundAndForfeit(t *testing.T) {
	e := deploy(t, filepath.Join(repoRoot(), "profiles", "local-evaluation-v1.json"))
	start := e.Head()
	e.StartAll()
	e.Start("buyer2", "fairbind-buyer", e.D.Services.Buyer2)
	e.waitHTTP(e.D.URLs["buyer2"] + "/purchases")
	proxy := newWithholdProxy(t, e.D.Seller.URL)
	prof := e.Profile()
	owner := e.D.Seller.Owner
	buyerAddr := e.D.Roles["buyer"].Address
	treasury, pool := e.D.Roles["penaltyTreasury"].Address, e.D.Roles["verifierRewardPool"].Address
	sellerBefore, buyerBefore := e.Balance(owner), e.Balance(buyerAddr)
	treasuryBefore, poolBefore := e.Balance(treasury), e.Balance(pool)
	lockedBefore := e.CallWords("getLockedForfeit()")[0]

	// Purchase A by the second buyer is delivered normally; that buyer then stops
	// and never claims, so A stays in the frozen pool until it is forfeited.
	ra := e.Buy(e.D.URLs["buyer2"], quoteURL(e.D.Seller.URL))
	if ra.State != buyer.StateReceived {
		e.dumpLogs()
		t.Fatalf("purchase A state %s (%s)", ra.State, ra.Reason)
	}
	nonceA := protocol.Bytes32(*ra.Nonce)
	e.Stop("buyer2")

	// Purchase B: the seller settles and responds, the proxy withholds the response.
	proxy.armed.Store(true)
	rb := e.Buy(e.D.URLs["buyer"], quoteURL(proxy.srv.URL))
	if rb.State != buyer.StateOffered || rb.Nonce == nil {
		t.Fatalf("purchase B state %s (%s), want offered", rb.State, rb.Reason)
	}
	nonceB := protocol.Bytes32(*rb.Nonce)
	pb := e.Purchase(nonceB)
	if !pb.Exists() || pb.FinancialState != chain.FinDeferred {
		t.Fatalf("purchase B not settled: %+v", pb)
	}
	if s := e.SellerRecord(nonceB); s["state"] != "delivered" {
		t.Fatalf("seller record of B %v", s["state"])
	}
	v := new(big.Int).SetUint64(pb.Value)
	// The seller fails from here on: it never serves.
	e.Stop("seller")

	// NON_DELIVERY dispute after responseDue; it opens SERVE_WAIT (ServeRequested).
	e.MineTo(pb.ResponseDue + 1)
	e.Wait("NON_DELIVERY dispute", 60*time.Second, false, func() (bool, string) {
		c := e.Case(nonceB)
		return c.State == chain.CaseServeWait, fmt.Sprintf("case state %d", c.State)
	})
	cb := e.Case(nonceB)
	if cb.Trigger != chain.TriggerNonDelivery || cb.Requester != addr(t, buyerAddr) || e.PurchaseState(nonceB) != chain.FinHeld {
		t.Fatalf("case after dispute %+v, purchase %s", cb, chain.FinancialStateName(e.PurchaseState(nonceB)))
	}
	if n := len(e.Logs("ServeRequested(bytes32,address,uint64,uint64)")); n != 1 {
		t.Fatalf("%d ServeRequested events", n)
	}
	deposit := new(big.Int).Sub(new(big.Int).Sub(buyerBefore, e.Balance(buyerAddr)), v)
	t.Logf("dispute opened; serveDue %d; buyer deposit %s", cb.ServeDue, deposit)

	// The serve deadline passes: timeoutServe -> UNSERVED, bond frozen, claim window open.
	e.MineTo(cb.ServeDue + 1)
	e.Wait("UNSERVED and buyer refund", 60*time.Second, true, func() (bool, string) {
		br := e.BuyerRecord("buyer", rb.Key)
		return br.State == buyer.StateRefunded, fmt.Sprintf("case %d, buyer %s", e.Case(nonceB).State, br.State)
	})
	if c := e.Case(nonceB); c.State != chain.CaseUnserved {
		t.Fatalf("case state %d, want UNSERVED", c.State)
	}
	if st := e.PurchaseState(nonceB); st != chain.FinRefunded {
		t.Fatalf("purchase B %s, want REFUNDED", chain.FinancialStateName(st))
	}
	if got := e.Balance(buyerAddr); got.Cmp(buyerBefore) != 0 {
		t.Fatalf("buyer balance %s after refund, want %s (price and deposit returned)", got, buyerBefore)
	}
	refunds := e.Logs("Refunded(bytes32,address,uint256,uint8)")
	if len(refunds) != 1 || Word(refunds[0].Data, 0).Cmp(v) != 0 {
		t.Fatalf("Refunded events %v, want one of %s", refunds, v)
	}
	b := e.Bond()
	if b.FreezeState != chain.FreezeClaimOpen {
		t.Fatalf("bond freeze state %d, want CLAIM_OPEN", b.FreezeState)
	}
	if st := e.PurchaseState(nonceA); st != chain.FinFrozenClaimable {
		t.Fatalf("purchase A %s, want FROZEN_CLAIMABLE", chain.FinancialStateName(st))
	}
	t.Logf("UNSERVED; buyer refunded %s; bond frozen at %d, claim window until %d; timeoutServe sent by the keeper: %v",
		v, b.FreezeBlock, b.ClaimUntilBlock, e.KeeperSent("timeoutServe"))

	// The seller also misses the anchor of the epoch; the keeper records the
	// failure, a second confirmed failure, which extends the claim window and
	// moves the frozen window to its block (ADR 0021).
	firstFreeze := b.FreezeBlock
	e.MineTo(prof.AnchorDeadline(pb.Epoch) + 1)
	e.Wait("anchor timeout", 60*time.Second, true, func() (bool, string) {
		a := e.Anchor(pb.Epoch)
		return a.State == chain.EpochFailed, fmt.Sprintf("anchor state %d", a.State)
	})
	b = e.Bond()
	if b.FreezeState != chain.FreezeClaimOpen || b.FreezeBlock <= firstFreeze {
		t.Fatalf("after the missed anchor: freeze state %d, freeze block %d, want CLAIM_OPEN moved past %d",
			b.FreezeState, b.FreezeBlock, firstFreeze)
	}
	t.Logf("epoch %d failed; frozen window moved to %d; claim window until %d", pb.Epoch, b.FreezeBlock, b.ClaimUntilBlock)

	// Nobody claims A; after the claim window the keeper forfeits the remainder.
	e.MineTo(b.ClaimUntilBlock - 3)
	if e.Bond().FreezeState != chain.FreezeClaimOpen {
		t.Fatal("forfeited inside the claim window")
	}
	e.MineTo(b.ClaimUntilBlock + 1)
	e.Wait("forfeitUnclaimed", 120*time.Second, true, func() (bool, string) {
		b := e.Bond()
		return b.FreezeState == freezeClaimClosed, fmt.Sprintf("freeze state %d", b.FreezeState)
	})
	if !e.KeeperSent("forfeitUnclaimed") || !e.KeeperSent("timeoutAnchor") {
		t.Fatal("keeper log does not show timeoutAnchor and forfeitUnclaimed")
	}
	forfeits := e.Logs("UnclaimedForfeited(uint32,bytes32,uint256,uint256,uint256)")
	if len(forfeits) != 1 {
		t.Fatalf("%d UnclaimedForfeited events", len(forfeits))
	}
	amount, toVerifiers, toReserve := Word(forfeits[0].Data, 0), Word(forfeits[0].Data, 1), Word(forfeits[0].Data, 2)
	// The remainder stays locked in the contract (ADR 0022): both destination
	// amounts of the event are zero and no token reaches the pool or the treasury.
	if amount.Cmp(v) != 0 || toVerifiers.Sign() != 0 || toReserve.Sign() != 0 {
		t.Fatalf("forfeit amount %s to %s/%s, want %s locked", amount, toVerifiers, toReserve, v)
	}
	if got := new(big.Int).Sub(e.Balance(pool), poolBefore); got.Sign() != 0 {
		t.Fatalf("reward pool received %s, want nothing", got)
	}
	if got := new(big.Int).Sub(e.Balance(treasury), treasuryBefore); got.Sign() != 0 {
		t.Fatalf("treasury received %s, want nothing", got)
	}
	// Each of the two confirmed failures (UNSERVED and the missed anchor)
	// also deducted one share of the seller penalty (ADR 0018); the bond holds
	// one penalty, so both shares fit in its balance. Shares and remainder are
	// locked together.
	shares := new(big.Int).SetUint64(2 * (prof.SellerPenalty / uint64(prof.FailureLimit)))
	if got, want := new(big.Int).Sub(e.CallWords("getLockedForfeit()")[0], lockedBefore), new(big.Int).Add(amount, shares); got.Cmp(want) != 0 {
		t.Fatalf("locked total grew by %s, want %s (remainder plus two penalty shares)", got, want)
	}
	if st := e.PurchaseState(nonceA); st != chain.FinForfeited {
		t.Fatalf("purchase A %s, want FORFEITED", chain.FinancialStateName(st))
	}
	if got := e.Balance(owner); got.Cmp(sellerBefore) != 0 {
		t.Fatalf("seller owner balance %s, want %s (never paid)", got, sellerBefore)
	}
	t.Logf("forfeited %s, locked in the contract with %s of penalty shares", amount, shares)
	t.Logf("non-delivery path: %d blocks from setup to forfeiture (%d mined explicitly)", e.Head()-start, e.mined)
}
