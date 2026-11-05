// Package casepath computes the per-case result columns of experiments/
// metrics.md from the chain and the keeper's call log: for every
// effective-detection case of a seller (final FAIL or UNSERVED) the blocks from
// its settlement to its confirmed failure (case_path_blocks), the keeper delay
// sum on its path (keeper_delay_sum_blocks, kappa_Sigma), their difference
// (case_path_minus_keeper) and whether the case followed the worst judgment
// path of experiments/controller/worstpath.py.
package casepath

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sort"
	"strings"
)

// KeeperCall is one sent keeper call as the keeper command logs it.
type KeeperCall struct {
	Action string `json:"action"`
	Status string `json:"status"`
	Tx     string `json:"tx"`
	Due    uint64 `json:"due"`
	Nonce  string `json:"nonce"`
	Epoch  string `json:"epoch"`
}

// ParseKeeperLog reads the keeper's JSON lines (standard output or an events
// file) and returns the sent calls. Other lines are skipped.
func ParseKeeperLog(r io.Reader) ([]KeeperCall, error) {
	var out []KeeperCall
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if !strings.HasPrefix(line, "{") {
			continue
		}
		var c KeeperCall
		if json.Unmarshal([]byte(line), &c) != nil || c.Status != "sent" || c.Tx == "" {
			continue
		}
		c.Nonce, c.Tx = strings.ToLower(c.Nonce), strings.ToLower(c.Tx)
		out = append(out, c)
	}
	return out, sc.Err()
}

// Chain is the read side the collector needs.
type Chain interface {
	// Logs returns the contract logs of an event signature whose indexed
	// topics match (nil matches any), with their block numbers.
	Logs(ctx context.Context, signature string, topics ...*string) ([]Log, error)
	// Case returns getCase(nonce) words at the latest block.
	Case(ctx context.Context, nonce string) ([]uint64, error)
	// MaxAssignments reads the profile's maxAssignments.
	MaxAssignments(ctx context.Context, profileID uint32) (uint64, error)
	// TxBlock returns the block that included a transaction, or ErrReverted.
	TxBlock(ctx context.Context, tx string) (uint64, error)
}

// ErrReverted marks a keeper call whose transaction reverted; it is not on
// any case's path.
var ErrReverted = errors.New("transaction reverted")

// Log is one contract log.
type Log struct {
	Block  uint64
	Topics []string
	Data   []uint64 // 32-byte data words that fit in uint64; larger words are 2^64-1
}

// Delay is one keeper call on a case's path.
type Delay struct {
	Action string `json:"action"`
	Due    uint64 `json:"due"`
	Block  uint64 `json:"block"`
	Delay  uint64 `json:"delay"`
}

// Case is one effective-detection case.
type Case struct {
	Nonce               string   `json:"nonce"`
	Outcome             string   `json:"outcome"` // FAIL or UNSERVED
	SettledBlock        uint64   `json:"settledBlock"`
	ConfirmedBlock      uint64   `json:"confirmedBlock"`
	CasePathBlocks      uint64   `json:"case_path_blocks"`
	KeeperDelaySum      uint64   `json:"keeper_delay_sum_blocks"`
	CasePathMinusKeeper int64    `json:"case_path_minus_keeper"`
	WorstPath           bool     `json:"worst_path"`
	WorstPathMismatch   []string `json:"worst_path_mismatch,omitempty"`
	KeeperCalls         []Delay  `json:"keeper_calls,omitempty"`
}

// Event signatures of contract-interface-v1 section 12.
const (
	evSettled           = "Settled(bytes32,bytes32,uint32,uint32,uint32,address,uint256,uint24,bytes32,bytes32)"
	evCaseFinalized     = "CaseFinalized(bytes32,uint8,uint8)"
	evCaseOpened        = "CaseOpened(bytes32,uint8,address,uint256)"
	evVerifierAssigned  = "VerifierAssigned(bytes32,uint8,uint8,uint32,uint64)"
	evServeRequested    = "ServeRequested(bytes32,address,uint64,uint64)"
	evEvidenceRequested = "EvidenceRequested(bytes32,uint8,uint8,uint64)"
	evEvidenceDisclosed = "EvidenceDisclosed(bytes32,uint8,uint8,bytes32)"
	evReviewResealed    = "ReviewResealed(bytes32,uint8,uint64)"
	evVerdictSubmitted  = "VerdictSubmitted(bytes32,uint8,uint32,uint8,bytes32)"
	evClaimWindowOpened = "ClaimWindowOpened(uint32,bytes32,uint64,uint256)"
	evSellerSuspended   = "SellerSuspended(uint32,uint32,bytes32)"
)

const (
	caseUnserved = 11
	caseFinal    = 13
	verdictPass  = 1
	verdictFail  = 2
)

func word(v uint64) string { return fmt.Sprintf("0x%064x", v) }

// Collect returns the effective-detection cases of a seller in settlement order.
func Collect(ctx context.Context, c Chain, sellerID uint32, calls []KeeperCall) ([]Case, error) {
	sid := word(uint64(sellerID))
	settled, err := c.Logs(ctx, evSettled, nil, nil, &sid)
	if err != nil {
		return nil, err
	}
	sort.SliceStable(settled, func(i, j int) bool { return settled[i].Block < settled[j].Block })
	var out []Case
	for _, s := range settled {
		nonce := strings.ToLower(s.Topics[1])
		words, err := c.Case(ctx, nonce)
		if err != nil {
			return nil, err
		}
		state, final := words[15], words[22]
		if !(state == caseFinal && final == verdictFail) && state != caseUnserved {
			continue
		}
		cs := Case{Nonce: nonce, Outcome: "FAIL", SettledBlock: s.Block}
		if state == caseUnserved {
			cs.Outcome = "UNSERVED"
		}
		if cs.ConfirmedBlock, err = confirmedBlock(ctx, c, nonce, state, calls); err != nil {
			return nil, err
		}
		cs.CasePathBlocks = cs.ConfirmedBlock - cs.SettledBlock
		epoch := fmt.Sprintf("%d:%d", sellerID, s.Data[4])
		for _, k := range calls {
			if k.Nonce != nonce && k.Epoch != epoch {
				continue
			}
			b, err := c.TxBlock(ctx, k.Tx)
			if errors.Is(err, ErrReverted) {
				continue
			}
			if err != nil {
				return nil, err
			}
			if b > cs.ConfirmedBlock || b < cs.SettledBlock {
				continue
			}
			d := Delay{Action: k.Action, Due: k.Due, Block: b}
			if k.Due > 0 && b > k.Due {
				d.Delay = b - k.Due
			}
			cs.KeeperDelaySum += d.Delay
			cs.KeeperCalls = append(cs.KeeperCalls, d)
		}
		cs.CasePathMinusKeeper = int64(cs.CasePathBlocks) - int64(cs.KeeperDelaySum)
		m, err := c.MaxAssignments(ctx, uint32(s.Data[1]))
		if err != nil {
			return nil, err
		}
		if cs.WorstPathMismatch, err = worstPathMismatch(ctx, c, nonce, m, state); err != nil {
			return nil, err
		}
		cs.WorstPath = len(cs.WorstPathMismatch) == 0
		out = append(out, cs)
	}
	return out, nil
}

// confirmedBlock is the block of the confirmed failure: CaseFinalized for a
// final FAIL; for UNSERVED the claim window or suspension it triggered, else
// the keeper's timeoutServe.
func confirmedBlock(ctx context.Context, c Chain, nonce string, state uint64, calls []KeeperCall) (uint64, error) {
	if state == caseFinal {
		logs, err := c.Logs(ctx, evCaseFinalized, &nonce)
		if err != nil || len(logs) == 0 {
			return 0, fmt.Errorf("case %s: no CaseFinalized log (%v)", nonce, err)
		}
		return logs[len(logs)-1].Block, nil
	}
	var best uint64
	for _, ev := range []struct {
		sig string
		pos int
	}{{evClaimWindowOpened, 2}, {evSellerSuspended, 3}} {
		topics := make([]*string, ev.pos)
		topics[ev.pos-1] = &nonce
		logs, err := c.Logs(ctx, ev.sig, topics...)
		if err != nil {
			return 0, err
		}
		for _, l := range logs {
			if best == 0 || l.Block < best {
				best = l.Block
			}
		}
	}
	if best != 0 {
		return best, nil
	}
	for _, k := range calls {
		if k.Nonce == nonce && k.Action == "timeoutServe" {
			return c.TxBlock(ctx, k.Tx)
		}
	}
	return 0, fmt.Errorf("case %s: UNSERVED without a block that confirms it", nonce)
}

// worstPathMismatch compares a case's events with the worst judgment path for
// maxAssignments m: opened by sampling; m initial assignments, each with a
// serve round and a FAIL, whose evidence is requested, and disclosed only on
// the last; m party review and m tiebreak assignments, each with a serve
// round, after one reseal of each stage; party review PASS, tiebreak FAIL.
func worstPathMismatch(ctx context.Context, c Chain, nonce string, m uint64, state uint64) ([]string, error) {
	count := func(sig string) ([]Log, error) { return c.Logs(ctx, sig, &nonce) }
	var bad []string
	check := func(what string, got, want uint64) {
		if got != want {
			bad = append(bad, fmt.Sprintf("%s: %d, want %d", what, got, want))
		}
	}
	if state != caseFinal {
		return []string{"not a final FAIL"}, nil
	}
	opened, err := count(evCaseOpened)
	if err != nil {
		return nil, err
	}
	if len(opened) != 1 || opened[0].Data[0] != 1 {
		bad = append(bad, "not opened by sampling")
	}
	assigned, err := count(evVerifierAssigned)
	if err != nil {
		return nil, err
	}
	perStage := map[uint64]uint64{}
	for _, l := range assigned {
		perStage[l.Data[0]]++
	}
	check("initial assignments", perStage[1], m)
	check("party review assignments", perStage[2], m)
	check("tiebreak assignments", perStage[4], m)
	check("auto review assignments", perStage[3], 0)
	for _, e := range []struct {
		sig, what string
		want      uint64
	}{{evServeRequested, "serve rounds", 3 * m}, {evEvidenceRequested, "evidence requests", m},
		{evEvidenceDisclosed, "evidence disclosures", 1}, {evReviewResealed, "review reseals", 2}} {
		logs, err := count(e.sig)
		if err != nil {
			return nil, err
		}
		check(e.what, uint64(len(logs)), e.want)
	}
	verdicts, err := count(evVerdictSubmitted)
	if err != nil {
		return nil, err
	}
	var initialFail, partyPass, tiebreakFail, other uint64
	for _, l := range verdicts {
		switch {
		case l.Data[0] == 1 && l.Data[1] == verdictFail:
			initialFail++
		case l.Data[0] == 2 && l.Data[1] == verdictPass:
			partyPass++
		case l.Data[0] == 4 && l.Data[1] == verdictFail:
			tiebreakFail++
		default:
			other++
		}
	}
	check("initial FAIL verdicts", initialFail, m)
	check("party review PASS verdicts", partyPass, 1)
	check("tiebreak FAIL verdicts", tiebreakFail, 1)
	check("other verdicts", other, 0)
	return bad, nil
}

// Row is one observation row of experiments/metrics.md.
type Row struct {
	Metric        string `json:"metric"`
	Value         any    `json:"value"`
	ObservationID string `json:"observation_id"`
}

// Rows returns the list metrics of the cases (one element per case, in
// settlement order) and one case_path row per case. worst names whether the
// run carried the worst-path directive; worst_path_case_blocks then lists
// case_path_minus_keeper of the cases that followed the worst path.
func Rows(runID string, cases []Case, worst bool) []Row {
	paths, sums, minus, worstBlocks := []uint64{}, []uint64{}, []int64{}, []int64{}
	var rows []Row
	for _, c := range cases {
		paths = append(paths, c.CasePathBlocks)
		sums = append(sums, c.KeeperDelaySum)
		minus = append(minus, c.CasePathMinusKeeper)
		if worst && c.WorstPath {
			worstBlocks = append(worstBlocks, c.CasePathMinusKeeper)
		}
		rows = append(rows, Row{Metric: "case_path", Value: c, ObservationID: runID + "/" + c.Nonce})
	}
	rows = append(rows,
		Row{Metric: "case_path_blocks", Value: paths, ObservationID: runID},
		Row{Metric: "keeper_delay_sum_blocks", Value: sums, ObservationID: runID},
		Row{Metric: "case_path_minus_keeper", Value: minus, ObservationID: runID})
	if worst {
		rows = append(rows, Row{Metric: "worst_path_case_blocks", Value: worstBlocks, ObservationID: runID})
	}
	return rows
}

// WriteRows writes rows as JSON lines.
func WriteRows(w io.Writer, rows []Row) error {
	enc := json.NewEncoder(w)
	for _, r := range rows {
		if err := enc.Encode(r); err != nil {
			return err
		}
	}
	return nil
}
