package chain

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
)

// ErrUnsupported is returned by RPC for reads it does not implement.
var ErrUnsupported = errors.New("not supported by the RPC client")

// RPCConfig configures an RPC client.
type RPCConfig struct {
	URL      string
	ChainID  uint64
	Contract Address
	// From is the sending account. The node must hold its key and accept
	// eth_sendTransaction for it (for example anvil's unlocked accounts or a
	// signing proxy). The client never handles private keys.
	From Address
	// Gas is the gas limit for each transaction (default 5,000,000).
	Gas uint64
	// ReceiptTimeout bounds the wait for a mined receipt (default 60s).
	ReceiptTimeout time.Duration
	HTTP           *http.Client
}

// RPC is a JSON-RPC implementation of Client.
type RPC struct {
	cfg RPCConfig
	id  atomic.Uint64
}

// NewRPC checks the node's chain ID and returns a client.
func NewRPC(ctx context.Context, cfg RPCConfig) (*RPC, error) {
	if cfg.HTTP == nil {
		cfg.HTTP = &http.Client{Timeout: 30 * time.Second}
	}
	if cfg.Gas == 0 {
		cfg.Gas = 5_000_000
	}
	if cfg.ReceiptTimeout == 0 {
		cfg.ReceiptTimeout = 60 * time.Second
	}
	r := &RPC{cfg: cfg}
	var id string
	if err := r.rpc(ctx, "eth_chainId", []any{}, &id); err != nil {
		return nil, err
	}
	got, err := quantity(id)
	if err != nil || got != cfg.ChainID {
		return nil, fmt.Errorf("node chain ID %s, configured %d", id, cfg.ChainID)
	}
	return r, nil
}

type rpcError struct {
	Code    int             `json:"code"`
	Message string          `json:"message"`
	Data    json.RawMessage `json:"data"`
}

func (e *rpcError) Error() string { return fmt.Sprintf("rpc error %d: %s", e.Code, e.Message) }

func (r *RPC) rpc(ctx context.Context, method string, params any, out any) error {
	body, err := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": r.id.Add(1), "method": method, "params": params})
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, r.cfg.URL, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := r.cfg.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	var env struct {
		Result json.RawMessage `json:"result"`
		Error  *rpcError       `json:"error"`
	}
	if err = json.NewDecoder(resp.Body).Decode(&env); err != nil {
		return err
	}
	if env.Error != nil {
		return env.Error
	}
	if out == nil {
		return nil
	}
	return json.Unmarshal(env.Result, out)
}

func quantity(s string) (uint64, error) {
	if !strings.HasPrefix(s, "0x") {
		return 0, errors.New("missing 0x")
	}
	return strconv.ParseUint(s[2:], 16, 64)
}

func (r *RPC) callMsg(data []byte) map[string]string {
	return map[string]string{"from": x402.Hex(r.cfg.From[:]), "to": x402.Hex(r.cfg.Contract[:]), "data": x402.Hex(data)}
}

func revertData(err error) ([]byte, bool) {
	var e *rpcError
	if !errors.As(err, &e) {
		return nil, false
	}
	var s string
	if json.Unmarshal(e.Data, &s) == nil {
		if b, err := x402.ParseHex(s); err == nil {
			return b, true
		}
	}
	var nested struct {
		Data string `json:"data"`
	}
	if json.Unmarshal(e.Data, &nested) == nil {
		if b, err := x402.ParseHex(nested.Data); err == nil {
			return b, true
		}
	}
	return nil, strings.Contains(strings.ToLower(e.Message), "revert")
}

func (r *RPC) view(ctx context.Context, data []byte) ([]byte, error) {
	var out string
	if err := r.rpc(ctx, "eth_call", []any{r.callMsg(data), "latest"}, &out); err != nil {
		if d, ok := revertData(err); ok {
			return nil, &RevertError{Name: ErrorName(d)}
		}
		return nil, err
	}
	return x402.ParseHex(out)
}

// send simulates the call to surface a named revert, then submits it and
// waits for its receipt.
func (r *RPC) send(ctx context.Context, data []byte) (Hash, error) {
	if _, err := r.view(ctx, data); err != nil {
		return Hash{}, err
	}
	msg := r.callMsg(data)
	msg["gas"] = "0x" + strconv.FormatUint(r.cfg.Gas, 16)
	var txText string
	if err := r.rpc(ctx, "eth_sendTransaction", []any{msg}, &txText); err != nil {
		if d, ok := revertData(err); ok {
			return Hash{}, &RevertError{Name: ErrorName(d)}
		}
		return Hash{}, err
	}
	h, err := x402.ParseH32(txText)
	if err != nil {
		return Hash{}, err
	}
	tx := Hash(h)
	deadline := time.Now().Add(r.cfg.ReceiptTimeout)
	for time.Now().Before(deadline) {
		st, err := r.TxStatus(ctx, tx)
		if err == nil && st == TxSucceeded {
			return tx, nil
		}
		if err == nil && st == TxFailed {
			return tx, &RevertError{Tx: tx}
		}
		select {
		case <-ctx.Done():
			return tx, ctx.Err()
		case <-time.After(200 * time.Millisecond):
		}
	}
	return tx, fmt.Errorf("transaction %s not mined before timeout", x402.H32(tx))
}

func (r *RPC) ChainID() uint64   { return r.cfg.ChainID }
func (r *RPC) Contract() Address { return r.cfg.Contract }
func (r *RPC) From() Address     { return r.cfg.From }

func (r *RPC) BlockNumber(ctx context.Context) (uint64, error) {
	var s string
	if err := r.rpc(ctx, "eth_blockNumber", []any{}, &s); err != nil {
		return 0, err
	}
	return quantity(s)
}

func (r *RPC) TxStatus(ctx context.Context, tx Hash) (TxStatus, error) {
	var rec *struct {
		Status string `json:"status"`
	}
	if err := r.rpc(ctx, "eth_getTransactionReceipt", []any{x402.H32(tx).String()}, &rec); err != nil {
		return TxUnknown, err
	}
	if rec != nil {
		if rec.Status == "0x1" {
			return TxSucceeded, nil
		}
		return TxFailed, nil
	}
	var pending json.RawMessage
	if err := r.rpc(ctx, "eth_getTransactionByHash", []any{x402.H32(tx).String()}, &pending); err != nil {
		return TxUnknown, err
	}
	if len(pending) > 0 && string(pending) != "null" {
		return TxPending, nil
	}
	return TxUnknown, nil
}

// decoder reads static return words and keeps the first error.
type decoder struct {
	w   [][]byte
	err error
}

func (d *decoder) u64(i int) uint64 {
	v, err := wU64(d.w[i])
	if err != nil && d.err == nil {
		d.err = err
	}
	return v
}
func (d *decoder) u32(i int) uint32 { return uint32(d.u64(i)) }
func (d *decoder) u16(i int) uint16 { return uint16(d.u64(i)) }
func (d *decoder) u8(i int) uint8   { return uint8(d.u64(i)) }
func (d *decoder) h(i int) Hash     { return w32(d.w[i]) }
func (d *decoder) a(i int) Address  { return wAddr(d.w[i]) }

func (r *RPC) viewWords(ctx context.Context, n int, signature string, args ...abiArg) (*decoder, error) {
	out, err := r.view(ctx, call(signature, args...))
	if err != nil {
		return nil, err
	}
	w, err := words(out, n)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", signature, err)
	}
	return &decoder{w: w}, nil
}

func (r *RPC) GetProfile(ctx context.Context, id uint32) (Profile, error) {
	d, err := r.viewWords(ctx, 3+45, sigGetServiceProfile, st(u(uint64(id))))
	if err != nil {
		return Profile{}, err
	}
	const o = 3 // parameters start after profileId, active, deploymentToken
	p := Profile{ProfileID: d.u32(0), Active: d.u64(1) != 0, Token: d.a(2), ClassID: d.u16(o + 0),
		PredicateID: d.h(o + 1), CanonID: d.h(o + 2), EpochOrigin: d.u64(o + 3), EpochBlocks: d.u32(o + 4),
		DeferBlocks: d.u32(o + 12), RetentionBlocks: d.u32(o + 13), MaxRequestBytes: d.u32(o + 15),
		MaxResponseBytes: d.u32(o + 16), MaxPurchaseValue: d.u64(o + 20), DisputeDeposit: d.u64(o + 27),
		DeadlineConfigID: d.u32(o + 33), BeaconDelayBlocks: d.u32(o + 34), SellerPenalty: d.u64(o + 22),
		FailureLimit: d.u32(o + 37)}
	if d.err != nil {
		return Profile{}, d.err
	}
	dc, err := r.viewWords(ctx, 9, sigGetDeadlineConfig, st(u(uint64(p.DeadlineConfigID))))
	if err != nil {
		return Profile{}, err
	}
	p.Deadlines = DeadlineConfig{dc.u32(0), dc.u32(1), dc.u32(2), dc.u32(3), dc.u32(4), dc.u32(5), dc.u32(6), dc.u32(7), dc.u32(8)}
	return p, dc.err
}

func (r *RPC) GetSeller(ctx context.Context, id uint32) (Seller, error) {
	d, err := r.viewWords(ctx, 9, sigGetSeller, st(u(uint64(id))))
	if err != nil {
		return Seller{}, err
	}
	s := Seller{SellerID: d.u32(0), ProfileID: d.u32(1), Owner: d.a(2), SigningKey: d.a(3), ClaimsHash: d.h(4), BondID: d.u32(5), Status: d.u8(8)}
	return s, d.err
}

func (r *RPC) QuoteSeller(ctx context.Context, id uint32) (Quote, error) {
	d, err := r.viewWords(ctx, 11, sigQuoteSeller, st(u(uint64(id))))
	if err != nil {
		return Quote{}, err
	}
	q := Quote{SellerID: d.u32(0), ProfileID: d.u32(1), ClaimsHash: d.h(2), Token: d.a(3), MaxPurchaseValue: d.u64(4),
		Remaining: d.u32(6), QuotedAtBlock: d.u64(7), CurrentEpoch: d.u32(8), SellerStatus: d.u8(9), BondID: d.u32(10)}
	return q, d.err
}

func (r *RPC) GetPurchase(ctx context.Context, nonce Hash) (Purchase, error) {
	d, err := r.viewWords(ctx, 15, sigGetPurchase, st(nonce[:]))
	if err != nil {
		return Purchase{}, err
	}
	p := Purchase{Nonce: d.h(0), KeyID: d.h(1), SellerID: d.u32(2), ProfileID: d.u32(3), Buyer: d.a(4), Value: d.u64(5),
		RequestHash: d.h(6), ClaimsHash: d.h(7), Epoch: d.u32(8), SettledBlock: d.u64(9), ResponseDue: d.u64(10),
		ClaimUntil: d.u64(11), ReleaseBlock: d.u64(12), RetainUntil: d.u64(13), FinancialState: d.u8(14)}
	return p, d.err
}

func (r *RPC) PurchaseByKey(ctx context.Context, keyID Hash) (Hash, error) {
	d, err := r.viewWords(ctx, 1, sigPurchaseByKey, st(keyID[:]))
	if err != nil {
		return Hash{}, err
	}
	return d.h(0), nil
}

func (r *RPC) PurchaseState(ctx context.Context, nonce Hash) (uint8, error) {
	d, err := r.viewWords(ctx, 1, sigPurchaseState, st(nonce[:]))
	if err != nil {
		return 0, err
	}
	return d.u8(0), d.err
}

func (r *RPC) GetCase(ctx context.Context, nonce Hash) (Case, error) {
	d, err := r.viewWords(ctx, 23, sigGetCase, st(nonce[:]))
	if err != nil {
		return Case{}, err
	}
	c := Case{Nonce: d.h(0), Requester: d.a(1), BundleHash: d.h(2), CaseOpenedBlock: d.u64(5), ServeDue: d.u64(6),
		ChallengeUntil: d.u64(7), PublishDue: d.u64(8), AssignedVerifierID: d.u32(12), PublishedChunks: d.u16(13),
		Trigger: d.u8(14), State: d.u8(15), RequesterRole: d.u8(18)}
	return c, d.err
}

func (r *RPC) GetAnchor(ctx context.Context, seller uint32, epoch uint32) (Anchor, error) {
	d, err := r.viewWords(ctx, 12, sigGetAnchor, st(u(uint64(seller))), st(u(uint64(epoch))))
	if err != nil {
		return Anchor{}, err
	}
	a := Anchor{Root: d.h(0), PublicationHash: d.h(2), AnchoredBlock: d.u64(5), RandomBlock: d.u64(6),
		ProfileID: d.u32(9), Count: d.u32(10), State: d.u8(11)}
	return a, d.err
}

func (r *RPC) GetBond(ctx context.Context, id uint32) (Bond, error) {
	d, err := r.viewWords(ctx, 25, sigGetBond, st(u(uint64(id))))
	if err != nil {
		return Bond{}, err
	}
	b := Bond{BondID: d.u32(0), FreezeBlock: d.u64(17), ClaimUntilBlock: d.u64(18), FreezeState: d.u8(22), Status: d.u8(23)}
	return b, d.err
}

func (r *RPC) GetVerifier(ctx context.Context, id uint32) (Verifier, error) {
	d, err := r.viewWords(ctx, 9, sigGetVerifier, st(u(uint64(id))))
	if err != nil {
		return Verifier{}, err
	}
	return Verifier{VerifierID: d.u32(0), SigningKey: d.a(2)}, d.err
}

func (r *RPC) SettledNonces(ctx context.Context, seller uint32, epoch uint32) ([]Hash, error) {
	s, err := r.GetSeller(ctx, seller)
	if err != nil {
		return nil, err
	}
	p, err := r.GetProfile(ctx, s.ProfileID)
	if err != nil {
		return nil, err
	}
	from, to := p.EpochStart(epoch), p.EpochStart(epoch+1)-1
	topic := protocol.Keccak256([]byte(eventSettled))
	var logs []struct {
		Topics []string `json:"topics"`
		Data   string   `json:"data"`
	}
	filter := map[string]any{
		"address":   x402.Hex(r.cfg.Contract[:]),
		"fromBlock": "0x" + strconv.FormatUint(from, 16),
		"toBlock":   "0x" + strconv.FormatUint(to, 16),
		"topics":    []any{x402.H32(topic).String(), nil, nil, x402.Hex(u(uint64(seller)))},
	}
	if err = r.rpc(ctx, "eth_getLogs", []any{filter}, &logs); err != nil {
		return nil, err
	}
	var out []Hash
	for _, l := range logs {
		if len(l.Topics) < 2 {
			return nil, errors.New("malformed Settled log")
		}
		data, err := x402.ParseHex(l.Data)
		if err != nil {
			return nil, err
		}
		w, err := words(data, 7)
		if err != nil {
			return nil, err
		}
		if e, _ := wU64(w[4]); uint32(e) != epoch {
			continue
		}
		n, err := x402.ParseH32(l.Topics[1])
		if err != nil {
			return nil, err
		}
		out = append(out, Hash(n))
	}
	return out, nil
}

// Publication is not implemented over RPC: it would require locating the
// publishing transaction and decoding its calldata.
func (r *RPC) Publication(context.Context, Hash) (*Publication, error) { return nil, ErrUnsupported }

func (r *RPC) Settle(ctx context.Context, s Settlement) (Hash, error) {
	a := s.Authorization
	auth := st(aWord(Address(a.From)), aWord(Address(a.To)), u(uint64(a.Value)), u(uint64(a.ValidAfter)), u(uint64(a.ValidBefore)), a.Nonce[:])
	return r.send(ctx, call(sigSettle, st(u(uint64(s.SellerID))), st(u(uint64(s.ProfileID))), st(s.ClaimsHash[:]),
		st(b16Word(s.Key)), st(s.RequestHash[:]), auth, dynBytes(s.Signature)))
}

func (r *RPC) Anchor(ctx context.Context, seller uint32, epoch uint32, entries []x402.Entry, count uint32, pub Hash) (Hash, error) {
	return r.send(ctx, call(sigAnchor, st(u(uint64(seller))), st(u(uint64(epoch))), dynEntries(entries), st(u(uint64(count))), st(pub[:])))
}

func (r *RPC) Dispute(ctx context.Context, nonce Hash, kind uint8, rc protocol.Receipt, sig []byte) (Hash, error) {
	return r.send(ctx, call(sigDispute, st(nonce[:]), st(u(uint64(kind))), receiptArg(rc), dynBytes(sig)))
}

func (r *RPC) nonceCall(ctx context.Context, sig string, nonce Hash) (Hash, error) {
	return r.send(ctx, call(sig, st(nonce[:])))
}

func (r *RPC) Served(ctx context.Context, nonce, bundle Hash) (Hash, error) {
	return r.send(ctx, call(sigServed, st(nonce[:]), st(bundle[:])))
}
func (r *RPC) AcceptServe(ctx context.Context, n Hash) (Hash, error) {
	return r.nonceCall(ctx, sigAcceptServe, n)
}
func (r *RPC) Escalate(ctx context.Context, n Hash) (Hash, error) {
	return r.nonceCall(ctx, sigEscalate, n)
}
func (r *RPC) FinalizeServed(ctx context.Context, n Hash) (Hash, error) {
	return r.nonceCall(ctx, sigFinalizeServed, n)
}
func (r *RPC) TimeoutServe(ctx context.Context, n Hash) (Hash, error) {
	return r.nonceCall(ctx, sigTimeoutServe, n)
}
func (r *RPC) FinalizePublication(ctx context.Context, n Hash) (Hash, error) {
	return r.nonceCall(ctx, sigFinalizePub, n)
}
func (r *RPC) ClaimRefund(ctx context.Context, n Hash) (Hash, error) {
	return r.nonceCall(ctx, sigClaimRefund, n)
}
func (r *RPC) ClaimEpochFailure(ctx context.Context, n Hash) (Hash, error) {
	return r.nonceCall(ctx, sigClaimEpochFail, n)
}

func (r *RPC) Publish(ctx context.Context, p Publication) (Hash, error) {
	return r.send(ctx, call(sigPublish, st(p.Nonce[:]), st(b16Word(p.Key)), requestArg(p.Request), dynBytes(p.Body),
		receiptArg(p.Receipt), dynBytes(p.Signature)))
}

func (r *RPC) BeginPublication(ctx context.Context, p Publication, total uint32, count uint16) (Hash, error) {
	return r.send(ctx, call(sigBeginPublication, st(p.Nonce[:]), st(b16Word(p.Key)), requestArg(p.Request),
		receiptArg(p.Receipt), dynBytes(p.Signature), st(u(uint64(total))), st(u(uint64(count)))))
}

func (r *RPC) PublishChunk(ctx context.Context, nonce Hash, index uint16, chunk []byte) (Hash, error) {
	return r.send(ctx, call(sigPublishChunk, st(nonce[:]), st(u(uint64(index))), dynBytes(chunk)))
}

func (r *RPC) ClaimRefundWithReceipt(ctx context.Context, nonce Hash, rc protocol.Receipt, sig []byte, proof protocol.ReceiptProof) (Hash, error) {
	return r.send(ctx, call(sigClaimRefundRcpt, st(nonce[:]), receiptArg(rc), dynBytes(sig), proofArg(proof)))
}

var _ Client = (*RPC)(nil)
