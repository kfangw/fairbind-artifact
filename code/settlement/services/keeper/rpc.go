package keeper

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"example.org/fairbind/protocol"
)

// settledTopic is the topic of Settled(bytes32,bytes32,uint32,uint32,uint32,address,uint256,uint24,bytes32,bytes32).
var settledTopic = protocol.Keccak256([]byte("Settled(bytes32,bytes32,uint32,uint32,uint32,address,uint256,uint24,bytes32,bytes32)"))

// RPC reads the ledger over JSON-RPC. Views use EIP-1898 block-hash pins with
// requireCanonical; Simulate uses the latest block. It sends nothing.
type RPC struct {
	URL              string
	ChainID          uint64
	Contract, From   protocol.Address
	Timeout          time.Duration
	MaxResponseBytes int64
	// SimulateAt is the block tag Simulate runs against: "latest" by default,
	// "pending" under the worst-path directive, whose calls are timed to the
	// block that includes them (Anvil runs a "latest" call at the latest block
	// number and a "pending" one at the next).
	SimulateAt string
	client     *http.Client
}

func NewRPC(u string, chainID uint64, contract, from protocol.Address, timeout time.Duration) (*RPC, error) {
	if err := checkURL(u); err != nil {
		return nil, err
	}
	if chainID == 0 || contract == (protocol.Address{}) || from == (protocol.Address{}) || timeout <= 0 {
		return nil, fmt.Errorf("invalid RPC configuration")
	}
	return &RPC{URL: u, ChainID: chainID, Contract: contract, From: from, Timeout: timeout, MaxResponseBytes: 8 << 20,
		client: &http.Client{Timeout: timeout, CheckRedirect: func(*http.Request, []*http.Request) error {
			return fmt.Errorf("RPC redirect rejected")
		}}}, nil
}

func checkURL(raw string) error {
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" || u.User != nil || u.Fragment != "" {
		return fmt.Errorf("invalid RPC URL")
	}
	ip := net.ParseIP(u.Hostname())
	if u.Scheme != "https" && !(u.Scheme == "http" && ip != nil && ip.IsLoopback()) {
		return fmt.Errorf("RPC requires HTTPS or literal loopback HTTP")
	}
	return nil
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

func (r *RPC) rpc(ctx context.Context, method string, params any, dst any) error {
	body, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
	req, err := http.NewRequestWithContext(ctx, "POST", r.URL, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	res, err := r.client.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		return fmt.Errorf("RPC HTTP status %d", res.StatusCode)
	}
	raw, err := io.ReadAll(io.LimitReader(res.Body, r.MaxResponseBytes+1))
	if err != nil {
		return err
	}
	if int64(len(raw)) > r.MaxResponseBytes {
		return fmt.Errorf("RPC response limit")
	}
	var msg struct {
		JSONRPC string          `json:"jsonrpc"`
		ID      json.RawMessage `json:"id"`
		Result  json.RawMessage `json:"result"`
		Error   *rpcError       `json:"error"`
	}
	if err = json.Unmarshal(raw, &msg); err != nil {
		return err
	}
	if msg.Error != nil {
		return fmt.Errorf("%s: RPC error %d: %s", method, msg.Error.Code, msg.Error.Message)
	}
	if msg.JSONRPC != "2.0" || string(msg.ID) != "1" || len(msg.Result) == 0 || string(msg.Result) == "null" {
		return fmt.Errorf("invalid RPC response: %s", method)
	}
	return json.Unmarshal(msg.Result, dst)
}

func quantity(s string) (uint64, error) {
	if !strings.HasPrefix(s, "0x") || len(s) < 3 || (len(s) > 3 && s[2] == '0') {
		return 0, fmt.Errorf("invalid RPC quantity %q", s)
	}
	return strconv.ParseUint(s[2:], 16, 64)
}

func hexBytes(s string) ([]byte, error) {
	if !strings.HasPrefix(s, "0x") {
		return nil, fmt.Errorf("invalid hex")
	}
	return hex.DecodeString(s[2:])
}

func (r *RPC) Finalized(ctx context.Context) (Block, error) { return r.block(ctx, "finalized") }

// Latest returns the latest block (worst-path directive).
func (r *RPC) Latest(ctx context.Context) (Block, error) { return r.block(ctx, "latest") }

func (r *RPC) block(ctx context.Context, tag string) (Block, error) {
	var chain string
	if err := r.rpc(ctx, "eth_chainId", []any{}, &chain); err != nil {
		return Block{}, err
	}
	if id, err := quantity(chain); err != nil || id != r.ChainID {
		return Block{}, fmt.Errorf("RPC chain mismatch")
	}
	var b struct{ Number, Hash string }
	if err := r.rpc(ctx, "eth_getBlockByNumber", []any{tag, false}, &b); err != nil {
		return Block{}, err
	}
	n, err := quantity(b.Number)
	if err != nil {
		return Block{}, err
	}
	h, err := hexBytes(b.Hash)
	if err != nil || len(h) != 32 {
		return Block{}, fmt.Errorf("invalid block hash")
	}
	out := Block{Number: n}
	copy(out.Hash[:], h)
	if out.Hash == (protocol.Bytes32{}) {
		return Block{}, fmt.Errorf("zero finalized hash")
	}
	return out, nil
}

func (r *RPC) Settlements(ctx context.Context, from, to uint64) ([]Settlement, error) {
	var logs []struct {
		Address string   `json:"address"`
		Topics  []string `json:"topics"`
		Data    string   `json:"data"`
		Removed bool     `json:"removed"`
	}
	filter := map[string]any{
		"fromBlock": fmt.Sprintf("0x%x", from), "toBlock": fmt.Sprintf("0x%x", to),
		"address": hexAddr(r.Contract), "topics": []any{hexKey(settledTopic)},
	}
	if err := r.rpc(ctx, "eth_getLogs", []any{filter}, &logs); err != nil {
		return nil, err
	}
	out := make([]Settlement, 0, len(logs))
	for _, l := range logs {
		if l.Removed || !strings.EqualFold(l.Address, hexAddr(r.Contract)) || len(l.Topics) != 4 || !strings.EqualFold(l.Topics[0], hexKey(settledTopic)) {
			return nil, fmt.Errorf("unexpected Settled log")
		}
		data, err := hexBytes(l.Data)
		if err != nil || len(data) != 7*32 {
			return nil, fmt.Errorf("Settled log data size")
		}
		nonce, err := parseKey(strings.ToLower(l.Topics[1]))
		if err != nil {
			return nil, err
		}
		seller, err := parseKey(strings.ToLower(l.Topics[3]))
		if err != nil {
			return nil, err
		}
		w := func(i int) []byte { return data[i*32 : (i+1)*32] }
		out = append(out, Settlement{Nonce: nonce, SellerID: uint32(u64(seller[:])),
			BondID: uint32(u64(w(0))), ProfileID: uint32(u64(w(1))), Epoch: uint32(u64(w(4)))})
	}
	return out, nil
}

func (r *RPC) call(ctx context.Context, at Block, sig string, n int, args ...[]byte) ([][]byte, error) {
	sel := protocol.Keccak256([]byte(sig))
	data := append([]byte{}, sel[:4]...)
	for _, a := range args {
		data = append(data, a...)
	}
	var result string
	tx := map[string]string{"to": hexAddr(r.Contract), "data": "0x" + hex.EncodeToString(data)}
	pin := map[string]any{"blockHash": hexKey(at.Hash), "requireCanonical": true}
	if err := r.rpc(ctx, "eth_call", []any{tx, pin}, &result); err != nil {
		return nil, err
	}
	raw, err := hexBytes(result)
	if err != nil || len(raw) != 32*n {
		return nil, fmt.Errorf("ABI size for %s", sig)
	}
	words := make([][]byte, n)
	for i := range words {
		words[i] = raw[i*32 : (i+1)*32]
	}
	return words, nil
}

func u64(b []byte) uint64 {
	for _, v := range b[:24] {
		if v != 0 {
			return ^uint64(0)
		}
	}
	return binary.BigEndian.Uint64(b[24:])
}

func hexAddr(a protocol.Address) string { return "0x" + hex.EncodeToString(a[:]) }

func (r *RPC) Timing(ctx context.Context, at Block, profileID uint32) (Timing, error) {
	f, err := r.call(ctx, at, "getServiceProfile(uint32)", 48, word(uint64(profileID)))
	if err != nil {
		return Timing{}, err
	}
	if uint32(u64(f[0])) != profileID {
		return Timing{}, fmt.Errorf("profile mismatch")
	}
	d, err := r.call(ctx, at, "getDeadlineConfig(uint32)", 9, word(u64(f[36])))
	if err != nil {
		return Timing{}, err
	}
	return Timing{EpochOrigin: u64(f[6]), EpochBlocks: u64(f[7]), AnchorBlocks: u64(d[0]), OpenBlocks: u64(d[2]),
		SealBlocks: u64(d[1]), MaxAssignments: u64(f[33]), FreezeOnInitialFail: u64(f[45]) != 0}, nil
}

func (r *RPC) Purchase(ctx context.Context, at Block, nonce protocol.Bytes32) (Purchase, error) {
	p, err := r.call(ctx, at, "getPurchase(bytes32)", 15, nonce[:])
	if err != nil {
		return Purchase{}, err
	}
	if !bytes.Equal(p[0], nonce[:]) {
		return Purchase{}, fmt.Errorf("purchase mismatch")
	}
	return Purchase{ClaimUntil: u64(p[11]), ReleaseBlock: u64(p[12]), RetainUntil: u64(p[13]), FinancialState: uint8(u64(p[14]))}, nil
}

func (r *RPC) PurchaseState(ctx context.Context, at Block, nonce protocol.Bytes32) (uint8, error) {
	w, err := r.call(ctx, at, "purchaseState(bytes32)", 1, nonce[:])
	if err != nil {
		return 0, err
	}
	return uint8(u64(w[0])), nil
}

func (r *RPC) Case(ctx context.Context, at Block, nonce protocol.Bytes32) (Case, error) {
	k, err := r.call(ctx, at, "getCase(bytes32)", 23, nonce[:])
	if err != nil {
		return Case{}, err
	}
	c := Case{ServeDue: u64(k[6]), ChallengeUntil: u64(k[7]), PublishDue: u64(k[8]), RandomBlock: u64(k[9]),
		JudgeDue: u64(k[10]), EvidenceDue: u64(k[11]), AssignedVerifierID: uint32(u64(k[12])),
		Trigger: uint8(u64(k[14])), State: uint8(u64(k[15])), Stage: uint8(u64(k[19])), Attempt: uint8(u64(k[20])),
		InitialVerdict: uint8(u64(k[21]))}
	if c.Trigger == triggerSample {
		w, err := r.call(ctx, at, "getSampleReceiptDue(bytes32)", 1, nonce[:])
		if err != nil {
			return Case{}, err
		}
		c.SampleReceiptDue = u64(w[0])
	}
	return c, nil
}

// ReviewResealDue reads getReviewResealDue(nonce): the last block of the
// reopened seal window of the current review stage (ADR 0025).
func (r *RPC) ReviewResealDue(ctx context.Context, at Block, nonce protocol.Bytes32) (uint64, error) {
	w, err := r.call(ctx, at, "getReviewResealDue(bytes32)", 1, nonce[:])
	if err != nil {
		return 0, err
	}
	return u64(w[0]), nil
}

// ReviewReseals reads getReviewReseals(nonce): bit s is set once the seal of
// review stage s has reopened (ADR 0021).
func (r *RPC) ReviewReseals(ctx context.Context, at Block, nonce protocol.Bytes32) (uint8, error) {
	w, err := r.call(ctx, at, "getReviewReseals(bytes32)", 1, nonce[:])
	if err != nil {
		return 0, err
	}
	return uint8(u64(w[0])), nil
}

func (r *RPC) Sampled(ctx context.Context, at Block, nonce protocol.Bytes32) (bool, bool, error) {
	w, err := r.call(ctx, at, "isSampled(bytes32)", 2, nonce[:])
	if err != nil {
		return false, false, err
	}
	return u64(w[0]) == 1, u64(w[1]) == 1, nil
}

func (r *RPC) Anchor(ctx context.Context, at Block, sellerID, epoch uint32) (Anchor, error) {
	a, err := r.call(ctx, at, "getAnchor(uint32,uint24)", 12, word(uint64(sellerID)), word(uint64(epoch)))
	if err != nil {
		return Anchor{}, err
	}
	return Anchor{RandomBlock: u64(a[6]), SealDeadline: u64(a[7]), State: uint8(u64(a[11]))}, nil
}

func (r *RPC) Bond(ctx context.Context, at Block, bondID uint32) (Bond, error) {
	b, err := r.call(ctx, at, "getBond(uint32)", 25, word(uint64(bondID)))
	if err != nil {
		return Bond{}, err
	}
	return Bond{FreezeBlock: u64(b[17]), ClaimUntilBlock: u64(b[18]), FreezeState: uint8(u64(b[22]))}, nil
}

// Simulate runs the call from the keeper account against the latest block.
func (r *RPC) Simulate(ctx context.Context, data []byte) error {
	var result string
	tx := map[string]string{"from": hexAddr(r.From), "to": hexAddr(r.Contract), "data": "0x" + hex.EncodeToString(data)}
	at := r.SimulateAt
	if at == "" {
		at = "latest"
	}
	return r.rpc(ctx, "eth_call", []any{tx, at}, &result)
}
