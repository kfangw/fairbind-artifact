package casepath

import (
	"context"
	"sort"
	"strings"
)

// Finite-attack episode columns (experiments/controller/finiteattack.py,
// experiments/metrics.md). The cheated sales are the first cheatSales settled
// purchases of the seller, in settlement order; the seller's own record
// (meta/attack.json) lists the same nonces when no settlement failed.

// Events the episode reads besides those of casepath.go.
const (
	evReleased        = "Released(bytes32,uint32,uint256)"
	evRefunded        = "Refunded(bytes32,address,uint256,uint8)"
	evFrozenClaimPaid = "FrozenClaimPaid(uint32,uint32,bytes32,address,uint256)"
	evUnclaimed       = "UnclaimedForfeited(uint32,bytes32,uint256,uint256,uint256)"
)

// Financial states of contract-interface-v1 section 2, by purchaseState value.
var financialStates = []string{"NONE", "DEFERRED", "HELD", "FROZEN_CLAIMABLE", "REFUNDABLE", "REFUNDED",
	"RELEASABLE", "RELEASED", "FORFEITED"}

// Sale is the outcome of one cheated sale at the end of the run.
type Sale struct {
	Nonce          string `json:"nonce"`
	SettledBlock   uint64 `json:"settled_block"`
	Value          uint64 `json:"value"`
	FinancialState string `json:"financial_state"`
	CaseOutcome    string `json:"case_outcome,omitempty"` // FAIL, UNSERVED or empty
	ReleasedBlock  uint64 `json:"released_block,omitempty"`
	RepaidBlock    uint64 `json:"repaid_block,omitempty"`
	ForfeitedBlock uint64 `json:"forfeited_block,omitempty"`
}

// Episode is one finite-attack episode of a seller.
type Episode struct {
	Detection             string   `json:"finite_attack_detection"` // with_detection, without_detection, open
	DetectionBlock        uint64   `json:"detection_block,omitempty"`
	DetectedBy            []string `json:"detected_by,omitempty"`
	EndBlock              uint64   `json:"episode_end_block,omitempty"`
	SellerGainReleased    uint64   `json:"seller_gain_released"`
	BuyerRefundAmount     uint64   `json:"buyer_refund_amount"`
	BuyerRefundOwed       uint64   `json:"buyer_refund_owed"`
	BuyerRefundBlocks     []uint64 `json:"buyer_refund_blocks"`
	BuyerRefundBlocksMax  uint64   `json:"buyer_refund_blocks_max,omitempty"`
	Sales                 []Sale   `json:"sales"`
	ConfirmedFailureBlock uint64   `json:"confirmed_failure_block,omitempty"`
}

// StateReader reads purchaseState.
type StateReader interface {
	PurchaseState(ctx context.Context, nonce string) (uint64, error)
}

// FiniteAttack collects the episode of a seller that cheated on its first
// cheatSales settled sales.
func FiniteAttack(ctx context.Context, c interface {
	Chain
	StateReader
}, sellerID uint32, cheatSales int) (Episode, error) {
	sid := word(uint64(sellerID))
	settled, err := c.Logs(ctx, evSettled, nil, nil, &sid)
	if err != nil {
		return Episode{}, err
	}
	sort.SliceStable(settled, func(i, j int) bool { return settled[i].Block < settled[j].Block })
	if len(settled) > cheatSales {
		settled = settled[:cheatSales]
	}
	var sales []Sale
	var bond uint64
	for _, s := range settled {
		nonce := strings.ToLower(s.Topics[1])
		bond = s.Data[0]
		sale := Sale{Nonce: nonce, SettledBlock: s.Block, Value: s.Data[3]}
		st, err := c.PurchaseState(ctx, nonce)
		if err != nil {
			return Episode{}, err
		}
		if st < uint64(len(financialStates)) {
			sale.FinancialState = financialStates[st]
		}
		w, err := c.Case(ctx, nonce)
		if err != nil {
			return Episode{}, err
		}
		switch {
		case w[15] == caseFinal && w[22] == verdictFail:
			sale.CaseOutcome = "FAIL"
		case w[15] == caseUnserved:
			sale.CaseOutcome = "UNSERVED"
		}
		first := func(sig string, pos int) (uint64, error) {
			topics := make([]*string, pos)
			topics[pos-1] = &nonce
			logs, err := c.Logs(ctx, sig, topics...)
			if err != nil || len(logs) == 0 {
				return 0, err
			}
			return logs[0].Block, nil
		}
		if sale.ReleasedBlock, err = first(evReleased, 1); err != nil {
			return Episode{}, err
		}
		if sale.RepaidBlock, err = first(evRefunded, 1); err != nil {
			return Episode{}, err
		}
		if sale.RepaidBlock == 0 {
			if sale.RepaidBlock, err = first(evFrozenClaimPaid, 3); err != nil {
				return Episode{}, err
			}
		}
		if sale.ForfeitedBlock, err = first(evUnclaimed, 2); err != nil {
			return Episode{}, err
		}
		sales = append(sales, sale)
	}
	// The first confirmed failure of the seller's bond account: its claim
	// window or the suspension of the seller.
	var confirmed uint64
	bw := word(bond)
	for _, q := range []struct {
		sig    string
		topics []*string
	}{{evClaimWindowOpened, []*string{&bw}}, {evSellerSuspended, []*string{&sid}}} {
		logs, err := c.Logs(ctx, q.sig, q.topics...)
		if err != nil {
			return Episode{}, err
		}
		for _, l := range logs {
			if confirmed == 0 || l.Block < confirmed {
				confirmed = l.Block
			}
		}
	}
	return episode(sales, confirmed), nil
}

// episode reduces the sales to the result columns; confirmed is the first
// confirmed failure of the bond account (0 when none).
func episode(sales []Sale, confirmed uint64) Episode {
	e := Episode{Sales: sales, BuyerRefundBlocks: []uint64{}, ConfirmedFailureBlock: confirmed}
	ended := len(sales) > 0
	for _, s := range sales {
		switch s.FinancialState {
		case "RELEASED", "RELEASABLE":
			e.SellerGainReleased += s.Value
		case "REFUNDED":
			e.BuyerRefundAmount += s.Value
			d := s.RepaidBlock - s.SettledBlock
			e.BuyerRefundBlocks = append(e.BuyerRefundBlocks, d)
			if d > e.BuyerRefundBlocksMax {
				e.BuyerRefundBlocksMax = d
			}
		case "REFUNDABLE", "FROZEN_CLAIMABLE":
			e.BuyerRefundOwed += s.Value
		}
		switch s.FinancialState {
		case "RELEASED", "REFUNDED", "FORFEITED":
			end := s.ReleasedBlock
			if end == 0 {
				end = s.RepaidBlock
			}
			if end == 0 {
				end = s.ForfeitedBlock
			}
			if end > e.EndBlock {
				e.EndBlock = end
			}
		default:
			ended = false
		}
		if s.CaseOutcome != "" {
			e.DetectedBy = append(e.DetectedBy, s.Nonce)
		}
	}
	if !ended {
		e.EndBlock = 0
	}
	detected := len(e.DetectedBy) > 0 && confirmed != 0 && (!ended || confirmed <= e.EndBlock)
	switch {
	case detected:
		e.Detection, e.DetectionBlock = "with_detection", confirmed
	case ended:
		e.Detection = "without_detection"
	default:
		e.Detection = "open"
	}
	return e
}

// EpisodeRows returns the observation rows of an episode: the four columns
// of experiments/metrics.md and the episode itself.
func EpisodeRows(runID string, e Episode) []Row {
	return []Row{
		{Metric: "finite_attack_detection", Value: e.Detection, ObservationID: runID},
		{Metric: "seller_gain_released", Value: e.SellerGainReleased, ObservationID: runID},
		{Metric: "buyer_refund_amount", Value: e.BuyerRefundAmount, ObservationID: runID},
		{Metric: "buyer_refund_blocks", Value: e.BuyerRefundBlocks, ObservationID: runID},
		{Metric: "finite_attack_episode", Value: e, ObservationID: runID},
	}
}
