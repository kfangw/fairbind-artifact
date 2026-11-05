package seller

import (
	"bytes"
	"net/http"
	"testing"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/directive"
	"example.org/fairbind/services/internal/x402"
	"example.org/fairbind/services/internal/x402/chain"
	"example.org/fairbind/services/internal/x402/testworld"
)

func attackHarness(t *testing.T, m uint64, after string) *harness {
	h := &harness{t: t, w: testworld.New(), dir: t.TempDir(),
		attack: &directive.FiniteAttack{CheatSales: m, After: after}}
	h.fac = &stubFacilitator{w: h.w}
	h.start()
	t.Cleanup(func() { h.stop() })
	return h
}

func (h *harness) mustBuy(key byte) (purchase, []byte) {
	h.t.Helper()
	p, resp, body := h.buy("/v1/quote", protocol.Bytes16{key})
	if resp.StatusCode != http.StatusOK {
		h.t.Fatalf("sale %d: status %d %s", key, resp.StatusCode, body)
	}
	return p, body
}

func TestFiniteAttackCheatsThenServesHonestly(t *testing.T) {
	h := attackHarness(t, 2, directive.AfterServeHonestly)
	var nonces []protocol.Bytes32
	for i, want := range [][]byte{cheatBody, cheatBody, dataBody(0), dataBody(0)} {
		p, body := h.mustBuy(byte(50 + i))
		if !bytes.Equal(body, want) {
			t.Fatalf("sale %d served %s, want %s", i, body, want)
		}
		rec, _ := h.s.Record(p.nonce)
		if rec.Cheat != (i < 2) {
			t.Fatalf("sale %d cheat mark %v", i, rec.Cheat)
		}
		nonces = append(nonces, p.nonce)
	}
	a, err := h.s.Attack()
	if err != nil || a.Accepted != 4 || len(a.Cheated) != 2 || a.Refused != 0 {
		t.Fatalf("attack state %+v %v", a, err)
	}
	if protocol.Bytes32(a.Cheated[0]) != nonces[0] || protocol.Bytes32(a.Cheated[1]) != nonces[1] {
		t.Fatalf("cheated nonces %v", a.Cheated)
	}
	// A restart keeps the count: the next sale is still honest.
	h.restart()
	if _, body := h.mustBuy(60); !bytes.Equal(body, dataBody(0)) {
		t.Fatalf("after restart %s", body)
	}
}

func TestFiniteAttackCheatsThenStopsSelling(t *testing.T) {
	h := attackHarness(t, 2, directive.AfterStopSelling)
	first, _ := h.mustBuy(70)
	h.mustBuy(71)
	// A new offer is refused.
	resp := h.request("GET", "/v1/quote", protocol.Bytes16{72}, "")
	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("offer after the attack: %d", resp.StatusCode)
	}
	// A retried payment of an accepted sale is still answered with its receipt.
	resp = h.request("GET", "/v1/quote", protocol.Bytes16{70}, first.header)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("retry of an accepted sale: %d", resp.StatusCode)
	}
	a, _ := h.s.Attack()
	if a.Accepted != 2 || len(a.Cheated) != 2 {
		t.Fatalf("attack state %+v", a)
	}
	if h.w.Fake.Calls("RequestSellerExit") != 0 {
		t.Fatal("stop_selling must not exit")
	}
}

func TestFiniteAttackPaymentRaceIsRefused(t *testing.T) {
	h := attackHarness(t, 1, directive.AfterStopSelling)
	// Both offers are issued before the first sale is paid.
	a := h.offerAndSign("/v1/quote", protocol.Bytes16{80})
	b := h.offerAndSign("/v1/quote", protocol.Bytes16{81})
	if resp := h.request("GET", "/v1/quote", a.key, a.header); resp.StatusCode != http.StatusOK {
		t.Fatalf("first sale %d", resp.StatusCode)
	}
	if resp := h.request("GET", "/v1/quote", b.key, b.header); resp.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("second payment %d, want refusal", resp.StatusCode)
	}
	st, _ := h.s.Attack()
	if st.Refused != 1 {
		t.Fatalf("refused %d", st.Refused)
	}
	if p, _ := h.w.Fake.As(testworld.SellerOwner).GetPurchase(ctx, b.nonce); p.Exists() {
		t.Fatal("the refused payment was settled")
	}
}

func TestFiniteAttackCheatsThenExits(t *testing.T) {
	h := attackHarness(t, 1, directive.AfterRequestExit)
	h.mustBuy(90)
	c := h.w.Fake.As(testworld.SellerOwner)
	tick := func() {
		t.Helper()
		if err := h.s.Tick(ctx); err != nil {
			t.Fatal(err)
		}
	}
	tick()
	s, _ := c.GetSeller(ctx, testworld.SellerID)
	b, _ := c.GetBond(ctx, testworld.BondID)
	if s.Status != chain.SellerExiting || b.Status != chain.BondExiting {
		t.Fatalf("after the attack: seller %d bond %d", s.Status, b.Status)
	}
	a, _ := h.s.Attack()
	if a.SellerExitRequested == 0 || a.BondExitRequested == 0 || a.SellerExited != 0 {
		t.Fatalf("exit progress %+v", a)
	}
	// Not admitted before the retention ends: nothing is recorded, nothing fails.
	tick()
	if a2, _ := h.s.Attack(); a2.SellerExited != 0 {
		t.Fatal("finalized before retention")
	}
	h.w.Fake.Mine(uint64(h.w.Profile.RetentionBlocks) + 1)
	tick()
	s, _ = c.GetSeller(ctx, testworld.SellerID)
	b, _ = c.GetBond(ctx, testworld.BondID)
	a, _ = h.s.Attack()
	if s.Status != chain.SellerExited || b.Status != chain.BondExited || a.SellerExited == 0 || a.BondExited == 0 {
		t.Fatalf("after retention: seller %d bond %d progress %+v", s.Status, b.Status, a)
	}
	if n := h.w.Fake.Calls("RequestSellerExit"); n != 1 {
		t.Fatalf("seller exit requested %d times", n)
	}
	tick()
	if n := h.w.Fake.Calls("FinalizeBondExit"); n != 1 {
		t.Fatalf("bond exit finalized %d times", n)
	}
}

func TestFiniteAttackExitWaitsForAFrozenAccount(t *testing.T) {
	h := attackHarness(t, 1, directive.AfterRequestExit)
	h.mustBuy(95)
	if err := h.s.Tick(ctx); err != nil {
		t.Fatal(err)
	}
	h.w.Fake.FreezeBond(testworld.BondID, 1000)
	h.w.Fake.Mine(uint64(h.w.Profile.RetentionBlocks) + 1)
	if err := h.s.Tick(ctx); err != nil {
		t.Fatal(err)
	}
	a, _ := h.s.Attack()
	if a.SellerExited != 0 || a.BondExited != 0 {
		t.Fatalf("exit finalized with the claim window open: %+v", a)
	}
}

func TestNextExitStep(t *testing.T) {
	cheated := AttackState{Cheated: make([]x402.H32, 2)}
	cases := []struct {
		name      string
		a         AttackState
		delivered bool
		want      exitStep
	}{
		{"cheating not finished", AttackState{Cheated: make([]x402.H32, 1)}, true, exitNone},
		{"cheated sale undelivered", cheated, false, exitNone},
		{"request the registration exit", cheated, true, exitRequestSeller},
		{"then the bond exit", AttackState{Cheated: cheated.Cheated, SellerExitRequested: 5}, true, exitRequestBond},
		{"finalize the registration", AttackState{Cheated: cheated.Cheated, SellerExitRequested: 5, BondExitRequested: 6}, true, exitFinalizeSeller},
		{"finalize the bond", AttackState{Cheated: cheated.Cheated, SellerExitRequested: 5, BondExitRequested: 6, SellerExited: 9}, true, exitFinalizeBond},
		{"done", AttackState{Cheated: cheated.Cheated, SellerExitRequested: 5, BondExitRequested: 6, SellerExited: 9, BondExited: 9}, true, exitNone},
	}
	for _, c := range cases {
		if got := nextExitStep(c.a, 2, c.delivered); got != c.want {
			t.Errorf("%s: %d, want %d", c.name, got, c.want)
		}
	}
}
