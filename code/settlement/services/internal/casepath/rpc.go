package casepath

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

// RPC reads a local node over JSON-RPC.
type RPC struct {
	URL      string
	Contract string // 0x address
	client   *http.Client
}

func NewRPC(url, contract string) *RPC {
	return &RPC{URL: url, Contract: strings.ToLower(contract), client: &http.Client{Timeout: 30 * time.Second}}
}

func (r *RPC) call(ctx context.Context, method string, params []any, out any) error {
	body, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, r.URL, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	res, err := r.client.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(res.Body, 64<<20))
	if err != nil {
		return err
	}
	var msg struct {
		Result json.RawMessage `json:"result"`
		Error  *struct {
			Message string `json:"message"`
		} `json:"error"`
	}
	if err = json.Unmarshal(raw, &msg); err != nil {
		return err
	}
	if msg.Error != nil {
		return fmt.Errorf("%s: %s", method, msg.Error.Message)
	}
	return json.Unmarshal(msg.Result, out)
}

func quantity(s string) (uint64, error) {
	return strconv.ParseUint(strings.TrimPrefix(s, "0x"), 16, 64)
}

func words(hexData string) []uint64 {
	d, _ := hex.DecodeString(strings.TrimPrefix(hexData, "0x"))
	var out []uint64
	for i := 0; i+32 <= len(d); i += 32 {
		w := d[i : i+32]
		if !bytes.Equal(w[:24], make([]byte, 24)) {
			out = append(out, ^uint64(0))
			continue
		}
		out = append(out, binary.BigEndian.Uint64(w[24:]))
	}
	return out
}

func (r *RPC) Logs(ctx context.Context, signature string, topics ...*string) ([]Log, error) {
	t0 := protocol.Keccak256([]byte(signature))
	ts := []any{"0x" + hex.EncodeToString(t0[:])}
	for _, t := range topics {
		if t == nil {
			ts = append(ts, nil)
		} else {
			ts = append(ts, *t)
		}
	}
	var raw []struct {
		BlockNumber string   `json:"blockNumber"`
		Topics      []string `json:"topics"`
		Data        string   `json:"data"`
		Removed     bool     `json:"removed"`
	}
	filter := map[string]any{"address": r.Contract, "fromBlock": "0x0", "toBlock": "latest", "topics": ts}
	if err := r.call(ctx, "eth_getLogs", []any{filter}, &raw); err != nil {
		return nil, err
	}
	var out []Log
	for _, l := range raw {
		if l.Removed {
			continue
		}
		b, err := quantity(l.BlockNumber)
		if err != nil {
			return nil, err
		}
		out = append(out, Log{Block: b, Topics: l.Topics, Data: words(l.Data)})
	}
	return out, nil
}

func (r *RPC) view(ctx context.Context, signature string, args ...string) ([]uint64, error) {
	sel := protocol.Keccak256([]byte(signature))
	data := "0x" + hex.EncodeToString(sel[:4])
	for _, a := range args {
		data += strings.TrimPrefix(a, "0x")
	}
	var out string
	if err := r.call(ctx, "eth_call", []any{map[string]string{"to": r.Contract, "data": data}, "latest"}, &out); err != nil {
		return nil, err
	}
	return words(out), nil
}

func (r *RPC) Case(ctx context.Context, nonce string) ([]uint64, error) {
	w, err := r.view(ctx, "getCase(bytes32)", nonce)
	if err == nil && len(w) != 23 {
		err = fmt.Errorf("getCase returned %d words", len(w))
	}
	return w, err
}

func (r *RPC) MaxAssignments(ctx context.Context, profileID uint32) (uint64, error) {
	w, err := r.view(ctx, "getServiceProfile(uint32)", word(uint64(profileID)))
	if err != nil {
		return 0, err
	}
	if len(w) < 34 {
		return 0, fmt.Errorf("getServiceProfile returned %d words", len(w))
	}
	return w[33], nil
}

func (r *RPC) TxBlock(ctx context.Context, tx string) (uint64, error) {
	var rc *struct {
		BlockNumber string `json:"blockNumber"`
		Status      string `json:"status"`
	}
	if err := r.call(ctx, "eth_getTransactionReceipt", []any{tx}, &rc); err != nil {
		return 0, err
	}
	if rc == nil {
		return 0, fmt.Errorf("no receipt for %s", tx)
	}
	if rc.Status != "0x1" {
		return 0, ErrReverted
	}
	return quantity(rc.BlockNumber)
}

func (r *RPC) PurchaseState(ctx context.Context, nonce string) (uint64, error) {
	w, err := r.view(ctx, "purchaseState(bytes32)", nonce)
	if err == nil && len(w) != 1 {
		err = fmt.Errorf("purchaseState returned %d words", len(w))
	}
	if err != nil {
		return 0, err
	}
	return w[0], nil
}
