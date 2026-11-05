package verifier

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"example.org/fairbind/protocol"
)

// TxStatus is the observed outcome of a broadcast transaction.
type TxStatus struct {
	Found   bool
	Success bool
	Block   uint64
}

// Chain is the read-only view the worker needs beyond the finalized ledger
// snapshot: block heights, assignment and verdict logs, and receipts.
type Chain interface {
	BlockNumber(ctx context.Context) (uint64, error)
	FinalizedBlock(ctx context.Context) (uint64, error)
	AssignedNonces(ctx context.Context, verifierID uint32, from, to uint64) ([]protocol.Bytes32, error)
	VerdictRecorded(ctx context.Context, nonce protocol.Bytes32, verifierID uint32, stage uint8, evidenceHash protocol.Bytes32, from, to uint64) (bool, error)
	TxStatus(ctx context.Context, tx protocol.Bytes32) (TxStatus, error)
}

var (
	VerifierAssignedTopic = protocol.Keccak256([]byte("VerifierAssigned(bytes32,uint8,uint8,uint32,uint64)"))
	VerdictSubmittedTopic = protocol.Keccak256([]byte("VerdictSubmitted(bytes32,uint8,uint32,uint8,bytes32)"))
)

// RPC is a minimal JSON-RPC client. It never signs or sends transactions.
type RPC struct {
	URL      string
	ChainID  uint64
	Contract protocol.Address
	MaxRange uint64 // maximum block span per eth_getLogs request
	Timeout  time.Duration
	MaxBytes int64
	client   *http.Client
}

func NewRPC(url string, chainID uint64, contract protocol.Address, maxRange uint64, timeout time.Duration) (*RPC, error) {
	if _, err := checkEndpoint(url); err != nil {
		return nil, err
	}
	if chainID == 0 || contract == (protocol.Address{}) || maxRange == 0 || timeout <= 0 {
		return nil, fmt.Errorf("invalid RPC configuration")
	}
	return &RPC{URL: url, ChainID: chainID, Contract: contract, MaxRange: maxRange, Timeout: timeout, MaxBytes: 8 << 20,
		client: &http.Client{Timeout: timeout, CheckRedirect: func(*http.Request, []*http.Request) error { return fmt.Errorf("RPC redirect rejected") }}}, nil
}

func (c *RPC) call(ctx context.Context, method string, params any, dst any) error {
	body, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.URL, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	res, err := c.client.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(res.Body, c.MaxBytes+1))
	if err != nil {
		return err
	}
	if res.StatusCode != http.StatusOK || int64(len(raw)) > c.MaxBytes {
		return fmt.Errorf("RPC unavailable: %s", method)
	}
	var msg struct {
		JSONRPC string          `json:"jsonrpc"`
		ID      json.RawMessage `json:"id"`
		Result  json.RawMessage `json:"result"`
		Error   json.RawMessage `json:"error"`
	}
	if err = json.Unmarshal(raw, &msg); err != nil {
		return err
	}
	if msg.JSONRPC != "2.0" || string(msg.ID) != "1" || (len(msg.Error) > 0 && string(msg.Error) != "null") {
		return fmt.Errorf("RPC error: %s", method)
	}
	return json.Unmarshal(msg.Result, dst)
}

func quantity(s string) (uint64, error) {
	if !strings.HasPrefix(s, "0x") || len(s) < 3 || (len(s) > 3 && s[2] == '0') {
		return 0, fmt.Errorf("invalid RPC quantity")
	}
	return strconv.ParseUint(s[2:], 16, 64)
}

func (c *RPC) checkChain(ctx context.Context) error {
	var s string
	if err := c.call(ctx, "eth_chainId", []any{}, &s); err != nil {
		return err
	}
	if n, err := quantity(s); err != nil || n != c.ChainID {
		return fmt.Errorf("RPC chain mismatch")
	}
	return nil
}

func (c *RPC) BlockNumber(ctx context.Context) (uint64, error) {
	if err := c.checkChain(ctx); err != nil {
		return 0, err
	}
	var s string
	if err := c.call(ctx, "eth_blockNumber", []any{}, &s); err != nil {
		return 0, err
	}
	return quantity(s)
}

func (c *RPC) FinalizedBlock(ctx context.Context) (uint64, error) {
	if err := c.checkChain(ctx); err != nil {
		return 0, err
	}
	var b *struct {
		Number string `json:"number"`
	}
	if err := c.call(ctx, "eth_getBlockByNumber", []any{"finalized", false}, &b); err != nil {
		return 0, err
	}
	if b == nil {
		return 0, fmt.Errorf("no finalized block")
	}
	return quantity(b.Number)
}

type rpcLog struct {
	Address string   `json:"address"`
	Topics  []string `json:"topics"`
	Data    string   `json:"data"`
	Removed bool     `json:"removed"`
}

func topicUint(v uint64) string {
	var w protocol.Bytes32
	binary.BigEndian.PutUint64(w[24:], v)
	return hex32(w)
}

// logs fetches contract logs in chunks of at most MaxRange blocks.
func (c *RPC) logs(ctx context.Context, topics []any, from, to uint64) ([]rpcLog, error) {
	if from > to {
		return nil, nil
	}
	if err := c.checkChain(ctx); err != nil {
		return nil, err
	}
	var out []rpcLog
	for start := from; start <= to; {
		end := to
		if end-start >= c.MaxRange {
			end = start + c.MaxRange - 1
		}
		var got []rpcLog
		filter := map[string]any{"address": "0x" + hex.EncodeToString(c.Contract[:]), "fromBlock": fmt.Sprintf("0x%x", start), "toBlock": fmt.Sprintf("0x%x", end), "topics": topics}
		if err := c.call(ctx, "eth_getLogs", []any{filter}, &got); err != nil {
			return nil, err
		}
		for _, l := range got {
			if l.Removed || !strings.EqualFold(l.Address, "0x"+hex.EncodeToString(c.Contract[:])) {
				continue
			}
			out = append(out, l)
		}
		if end == to {
			break
		}
		start = end + 1
	}
	return out, nil
}

// AssignedNonces returns the nonces of VerifierAssigned events for verifierID.
// Callers pass a finalized upper bound.
func (c *RPC) AssignedNonces(ctx context.Context, verifierID uint32, from, to uint64) ([]protocol.Bytes32, error) {
	logs, err := c.logs(ctx, []any{hex32(VerifierAssignedTopic), nil, topicUint(uint64(verifierID))}, from, to)
	if err != nil {
		return nil, err
	}
	var out []protocol.Bytes32
	for _, l := range logs {
		if len(l.Topics) != 3 || !strings.EqualFold(l.Topics[0], hex32(VerifierAssignedTopic)) || !strings.EqualFold(l.Topics[2], topicUint(uint64(verifierID))) {
			continue
		}
		n, err := parse32(l.Topics[1])
		if err != nil {
			return nil, err
		}
		out = append(out, n)
	}
	return out, nil
}

// VerdictRecorded reports whether a VerdictSubmitted event for the given
// nonce, verifier, stage and evidence hash exists in [from, to].
func (c *RPC) VerdictRecorded(ctx context.Context, nonce protocol.Bytes32, verifierID uint32, stage uint8, evidenceHash protocol.Bytes32, from, to uint64) (bool, error) {
	logs, err := c.logs(ctx, []any{hex32(VerdictSubmittedTopic), hex32(nonce), topicUint(uint64(verifierID))}, from, to)
	if err != nil {
		return false, err
	}
	for _, l := range logs {
		if len(l.Topics) != 3 || !strings.EqualFold(l.Topics[1], hex32(nonce)) || !strings.EqualFold(l.Topics[2], topicUint(uint64(verifierID))) {
			continue
		}
		data, err := parseHex(l.Data, 96)
		if err != nil {
			return false, fmt.Errorf("VerdictSubmitted data: %w", err)
		}
		var s, h protocol.Bytes32
		copy(s[:], data[:32])
		copy(h[:], data[64:96])
		if s == wordUint(uint64(stage)) && h == evidenceHash {
			return true, nil
		}
	}
	return false, nil
}

func wordUint(v uint64) (w protocol.Bytes32) { binary.BigEndian.PutUint64(w[24:], v); return }

// LatestCase reads getCase(nonce) at the latest block (worst-path directive).
func (c *RPC) LatestCase(ctx context.Context, nonce protocol.Bytes32) (CaseView, error) {
	if err := c.checkChain(ctx); err != nil {
		return CaseView{}, err
	}
	sel := protocol.Keccak256([]byte("getCase(bytes32)"))
	data := append(append([]byte{}, sel[:4]...), nonce[:]...)
	var out string
	msg := map[string]string{"to": "0x" + hex.EncodeToString(c.Contract[:]), "data": "0x" + hex.EncodeToString(data)}
	if err := c.call(ctx, "eth_call", []any{msg, "latest"}, &out); err != nil {
		return CaseView{}, err
	}
	raw, err := parseHex(out, 23*32)
	if err != nil {
		return CaseView{}, fmt.Errorf("getCase: %w", err)
	}
	w := func(i int) []byte { return raw[32*i : 32*(i+1)] }
	u := func(i int) uint64 { return binary.BigEndian.Uint64(w(i)[24:]) }
	var v CaseView
	if !bytes.Equal(w(0), nonce[:]) && u(15) != 0 {
		return CaseView{}, fmt.Errorf("getCase: nonce mismatch")
	}
	copy(v.Requester[:], w(1)[12:])
	copy(v.EvidenceHash[:], w(4))
	v.ChallengeUntil, v.JudgeDue, v.EvidenceDue = u(7), u(10), u(11)
	v.AssignedVerifierID = uint32(u(12))
	v.Trigger, v.State, v.Stage, v.Attempt = uint8(u(14)), uint8(u(15)), uint8(u(19)), uint8(u(20))
	return v, nil
}

func (c *RPC) TxStatus(ctx context.Context, tx protocol.Bytes32) (TxStatus, error) {
	if err := c.checkChain(ctx); err != nil {
		return TxStatus{}, err
	}
	var r *struct {
		Status      string `json:"status"`
		BlockNumber string `json:"blockNumber"`
	}
	if err := c.call(ctx, "eth_getTransactionReceipt", []any{hex32(tx)}, &r); err != nil {
		return TxStatus{}, err
	}
	if r == nil {
		return TxStatus{}, nil
	}
	n, err := quantity(r.BlockNumber)
	if err != nil {
		return TxStatus{}, err
	}
	return TxStatus{Found: true, Success: r.Status == "0x1", Block: n}, nil
}
