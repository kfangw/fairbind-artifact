package casepath

import (
	"context"
	"reflect"
	"testing"
)

type stateChain struct {
	*fakeChain
	states map[string]uint64
}

func (s stateChain) PurchaseState(_ context.Context, n string) (uint64, error) {
	return s.states[n], nil
}

func settle(f *fakeChain, nonce string, block, value uint64) {
	f.add(evSettled, block, []string{nonce, "0xkey", word(1)}, 5, 3, ^uint64(0), value, 1)
}

func TestFiniteAttackEpisodeWithDetection(t *testing.T) {
	f := &fakeChain{cases: map[string][]uint64{}}
	c := stateChain{f, map[string]uint64{}}
	// Three cheated sales and one honest sale after them.
	for i, n := range []string{"0xa", "0xb", "0xc", "0xh"} {
		settle(f, n, uint64(10*(i+1)), 10000)
	}
	w := make([]uint64, 23)
	w[15], w[22] = caseFinal, verdictFail
	f.cases["0xa"] = w
	f.add(evClaimWindowOpened, 29690, []string{word(5), "0xa"}, 0, 0)
	f.add(evSellerSuspended, 29690, []string{word(1), word(5), "0xa"})
	c.states["0xa"], c.states["0xb"], c.states["0xc"] = 5, 5, 7
	f.add(evRefunded, 30000, []string{"0xa", "0xbuyer"}, 10000, 1)
	f.add(evFrozenClaimPaid, 30100, []string{word(5), word(1), "0xb"}, 0, 10000)
	f.add(evReleased, 60030, []string{"0xc", word(1)}, 10000)
	e, err := FiniteAttack(context.Background(), c, 1, 3)
	if err != nil {
		t.Fatal(err)
	}
	if e.Detection != "with_detection" || e.DetectionBlock != 29690 || !reflect.DeepEqual(e.DetectedBy, []string{"0xa"}) {
		t.Fatalf("detection %+v", e)
	}
	if e.SellerGainReleased != 10000 || e.BuyerRefundAmount != 20000 || e.BuyerRefundOwed != 0 {
		t.Fatalf("amounts %+v", e)
	}
	if !reflect.DeepEqual(e.BuyerRefundBlocks, []uint64{29990, 30080}) || e.BuyerRefundBlocksMax != 30080 {
		t.Fatalf("refund blocks %v", e.BuyerRefundBlocks)
	}
	if e.EndBlock != 60030 || len(e.Sales) != 3 {
		t.Fatalf("end %d sales %d", e.EndBlock, len(e.Sales))
	}
	rows := EpisodeRows("run-1", e)
	if rows[0].Metric != "finite_attack_detection" || rows[3].Metric != "buyer_refund_blocks" {
		t.Fatalf("rows %+v", rows)
	}
}

func TestFiniteAttackEpisodeWithoutDetection(t *testing.T) {
	f := &fakeChain{cases: map[string][]uint64{}}
	c := stateChain{f, map[string]uint64{}}
	for i, n := range []string{"0xa", "0xb"} {
		settle(f, n, uint64(10*(i+1)), 10000)
		c.states[n] = 7
		f.add(evReleased, 60000+uint64(i), []string{n, word(1)}, 10000)
	}
	e, err := FiniteAttack(context.Background(), c, 1, 2)
	if err != nil {
		t.Fatal(err)
	}
	if e.Detection != "without_detection" || e.SellerGainReleased != 20000 || e.BuyerRefundAmount != 0 || len(e.BuyerRefundBlocks) != 0 {
		t.Fatalf("episode %+v", e)
	}
	// Still deferred at the end of the run: open.
	c.states["0xb"] = 1
	if e, _ = FiniteAttack(context.Background(), c, 1, 2); e.Detection != "open" || e.EndBlock != 0 {
		t.Fatalf("open episode %+v", e)
	}
}

func TestEpisodeFailureAfterTheEpisode(t *testing.T) {
	e := episode([]Sale{{Nonce: "0xa", SettledBlock: 10, Value: 5, FinancialState: "RELEASED", CaseOutcome: "FAIL", ReleasedBlock: 60010}}, 70000)
	if e.Detection != "without_detection" || e.SellerGainReleased != 5 {
		t.Fatalf("%+v", e)
	}
	e = episode([]Sale{{Nonce: "0xa", Value: 5, FinancialState: "FROZEN_CLAIMABLE", CaseOutcome: "UNSERVED"}}, 700)
	if e.Detection != "with_detection" || e.BuyerRefundOwed != 5 {
		t.Fatalf("%+v", e)
	}
}
