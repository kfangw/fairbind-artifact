// Package ledger reads one hash-pinned finalized FairBind assignment. It never
// signs or submits transactions. The configured RPC remains a trusted boundary.
package ledger

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
	"example.org/fairbind/runtime/verifier"
)

type Config struct {
	URL              string
	ChainID          uint64
	Contract         protocol.Address
	Timeout          time.Duration
	MaxResponseBytes int64
	MaxClaimsBytes   int
}
type ManifestBindings struct{ SourceSetHash, TolerancePolicyHash, ModelHash, ConfigHash protocol.Bytes32 }
type Assignment struct {
	AnchorRoot                protocol.Bytes32
	AnchorCount               uint32
	VerifierKey               protocol.Address
	Trigger                   uint8
	EvidenceHash              protocol.Bytes32
	Snapshot                  verifier.Snapshot
	BlockNumber               uint64
	BlockHash                 protocol.Bytes32
	Stage, Attempt, CaseState uint8
	VerifierID                uint32
	JudgeDue, RetainUntil     uint64
	MaxEvidenceBytes          uint32
}
type Client struct {
	cfg  Config
	http *http.Client
}

func New(c Config) (*Client, error) {
	u, e := url.Parse(c.URL)
	if e != nil || u.Host == "" || u.User != nil || u.Fragment != "" {
		return nil, fmt.Errorf("invalid RPC URL")
	}
	ip := net.ParseIP(u.Hostname())
	if u.Scheme != "https" && !(u.Scheme == "http" && ip != nil && ip.IsLoopback()) {
		return nil, fmt.Errorf("RPC requires HTTPS or literal loopback HTTP")
	}
	if c.ChainID == 0 || c.Contract == (protocol.Address{}) || c.Timeout <= 0 || c.MaxResponseBytes < 4096 || c.MaxResponseBytes > 16<<20 || c.MaxClaimsBytes <= 0 {
		return nil, fmt.Errorf("invalid ledger configuration")
	}
	return &Client{c, &http.Client{Timeout: c.Timeout, CheckRedirect: func(*http.Request, []*http.Request) error { return fmt.Errorf("RPC redirect rejected") }}}, nil
}
func (c *Client) rpc(ctx context.Context, method string, params any, dst any) error {
	body, _ := json.Marshal(struct {
		JSONRPC string `json:"jsonrpc"`
		ID      int    `json:"id"`
		Method  string `json:"method"`
		Params  any    `json:"params"`
	}{"2.0", 1, method, params})
	req, e := http.NewRequestWithContext(ctx, "POST", c.cfg.URL, bytes.NewReader(body))
	if e != nil {
		return e
	}
	req.Header.Set("Content-Type", "application/json")
	res, e := c.http.Do(req)
	if e != nil {
		return e
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		return fmt.Errorf("RPC HTTP status %d", res.StatusCode)
	}
	raw, e := io.ReadAll(io.LimitReader(res.Body, c.cfg.MaxResponseBytes+1))
	if e != nil {
		return e
	}
	if int64(len(raw)) > c.cfg.MaxResponseBytes {
		return fmt.Errorf("RPC response limit")
	}
	var msg struct {
		JSONRPC string          `json:"jsonrpc"`
		ID      json.RawMessage `json:"id"`
		Result  json.RawMessage `json:"result"`
		Error   json.RawMessage `json:"error"`
	}
	if e = json.Unmarshal(raw, &msg); e != nil {
		return e
	}
	if msg.JSONRPC != "2.0" || string(msg.ID) != "1" || (len(msg.Error) > 0 && string(msg.Error) != "null") || len(msg.Result) == 0 || string(msg.Result) == "null" {
		return fmt.Errorf("invalid or failed RPC response: %s", method)
	}
	return json.Unmarshal(msg.Result, dst)
}
func quantity(s string) (uint64, error) {
	if !strings.HasPrefix(s, "0x") || len(s) < 3 || (len(s) > 3 && s[2] == '0') {
		return 0, fmt.Errorf("invalid RPC quantity")
	}
	return strconv.ParseUint(s[2:], 16, 64)
}
func hash(s string) (h protocol.Bytes32, e error) {
	if len(s) != 66 || !strings.HasPrefix(s, "0x") {
		return h, fmt.Errorf("invalid block hash")
	}
	b, e := hex.DecodeString(s[2:])
	copy(h[:], b)
	return h, e
}
func hexHash(h protocol.Bytes32) string { return "0x" + hex.EncodeToString(h[:]) }

type block struct {
	Number string `json:"number"`
	Hash   string `json:"hash"`
}

func (c *Client) chain(ctx context.Context) error {
	var s string
	if e := c.rpc(ctx, "eth_chainId", []any{}, &s); e != nil {
		return e
	}
	n, e := quantity(s)
	if e != nil || n != c.cfg.ChainID {
		return fmt.Errorf("RPC chain mismatch")
	}
	return nil
}
func (c *Client) call(ctx context.Context, b protocol.Bytes32, signature string, arg protocol.Bytes32, widths []int, extra ...protocol.Bytes32) ([][]byte, error) {
	selector := protocol.Keccak256([]byte(signature))
	data := append(append([]byte{}, selector[:4]...), arg[:]...)
	for _, word := range extra {
		data = append(data, word[:]...)
	}
	var result string
	e := c.rpc(ctx, "eth_call", []any{map[string]string{"to": "0x" + hex.EncodeToString(c.cfg.Contract[:]), "data": "0x" + hex.EncodeToString(data)}, map[string]any{"blockHash": hexHash(b), "requireCanonical": true}}, &result)
	if e != nil {
		return nil, e
	}
	if !strings.HasPrefix(result, "0x") {
		return nil, fmt.Errorf("ABI hex")
	}
	raw, e := hex.DecodeString(result[2:])
	if e != nil || len(raw) != 32*len(widths) {
		return nil, fmt.Errorf("ABI size for %s", signature)
	}
	words := make([][]byte, len(widths))
	for i, w := range widths {
		words[i] = raw[i*32 : (i+1)*32]
		if w > 0 {
			for _, v := range words[i][:32-w] {
				if v != 0 {
					return nil, fmt.Errorf("ABI width for %s word %d", signature, i)
				}
			}
		}
		if w == -1 && (u64(words[i]) > 1 || !bytes.Equal(words[i][:31], make([]byte, 31))) {
			return nil, fmt.Errorf("ABI bool")
		}
	}
	return words, nil
}
func u64(b []byte) uint64                  { return binary.BigEndian.Uint64(b[24:]) }
func b32(b []byte) (h protocol.Bytes32)    { copy(h[:], b); return }
func addr(b []byte) (a protocol.Address)   { copy(a[:], b[12:]); return }
func idArg(id uint32) (b protocol.Bytes32) { binary.BigEndian.PutUint32(b[28:], id); return }

// Read authenticates chain and immutable field relationships at one finalized
// block. Manifest bindings are caller-supplied expectations, NOT authenticated
// by this adapter: verifier.Check must bind canonical claims to ClaimsHash.
func (c *Client) Read(ctx context.Context, nonce protocol.Bytes32, m ManifestBindings) (a Assignment, err error) {
	ctx, cancel := context.WithTimeout(ctx, c.cfg.Timeout)
	defer cancel()
	if err = c.chain(ctx); err != nil {
		return
	}
	var b block
	if err = c.rpc(ctx, "eth_getBlockByNumber", []any{"finalized", false}, &b); err != nil {
		return
	}
	if a.BlockNumber, err = quantity(b.Number); err != nil {
		return
	}
	if a.BlockHash, err = hash(b.Hash); err != nil {
		return
	}
	if a.BlockHash == (protocol.Bytes32{}) {
		return Assignment{}, fmt.Errorf("zero finalized hash")
	}
	p, e := c.call(ctx, a.BlockHash, "getPurchase(bytes32)", nonce, []int{0, 0, 4, 4, 20, 0, 0, 0, 3, 8, 8, 8, 8, 8, 1})
	if e != nil {
		return Assignment{}, e
	}
	sid, pid := uint32(u64(p[2])), uint32(u64(p[3]))
	if nonce == (protocol.Bytes32{}) || b32(p[0]) != nonce || sid == 0 || pid == 0 {
		return Assignment{}, fmt.Errorf("unknown or mismatched purchase")
	}
	s, e := c.call(ctx, a.BlockHash, "getSeller(uint32)", idArg(sid), []int{4, 4, 20, 20, 0, 4, 8, 8, 1})
	if e != nil {
		return Assignment{}, e
	}
	widths := []int{4, -1, 20, 2, 0, 0, 8, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 4, 2, 2, 2, 4, 4, 4, 4, 4, 4, 4, 4, 4, -1, 4, 0}
	f, e := c.call(ctx, a.BlockHash, "getServiceProfile(uint32)", idArg(pid), widths)
	if e != nil {
		return Assignment{}, e
	}
	k, e := c.call(ctx, a.BlockHash, "getCase(bytes32)", nonce, []int{0, 20, 0, 0, 0, 8, 8, 8, 8, 8, 8, 8, 4, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1})
	if e != nil {
		return Assignment{}, e
	}
	if uint32(u64(s[0])) != sid || uint32(u64(s[1])) != pid || b32(s[4]) != b32(p[7]) || uint32(u64(f[0])) != pid || u64(f[3]) > 255 || addr(s[3]) == (protocol.Address{}) || addr(p[4]) == (protocol.Address{}) || b32(k[0]) != nonce {
		return Assignment{}, fmt.Errorf("ledger relationship mismatch")
	}
	a.Snapshot = verifier.Snapshot{ChainID: c.cfg.ChainID, Contract: c.cfg.Contract, Buyer: addr(p[4]), SellerKey: addr(s[3]), SellerID: sid, ProfileID: pid, Epoch: uint32(u64(p[8])), KeyID: b32(p[1]), Nonce: nonce, RequestHash: b32(p[6]), ClaimsHash: b32(p[7]), ClassID: uint8(u64(f[3])), PredicateID: b32(f[4]), CanonID: b32(f[5]), SourceSetHash: m.SourceSetHash, TolerancePolicyHash: m.TolerancePolicyHash, ModelHash: m.ModelHash, ConfigHash: m.ConfigHash, MaxRequestBytes: int(u64(f[18])), MaxResponseBytes: int(u64(f[19])), MaxClaimsBytes: c.cfg.MaxClaimsBytes}
	a.MaxEvidenceBytes = uint32(u64(f[20]))
	a.RetainUntil = u64(p[13])
	a.JudgeDue = u64(k[10])
	a.VerifierID = uint32(u64(k[12]))
	a.Trigger = uint8(u64(k[14]))
	a.EvidenceHash = b32(k[4])
	a.CaseState = uint8(u64(k[15]))
	a.Stage = uint8(u64(k[19]))
	a.Attempt = uint8(u64(k[20]))
	if a.VerifierID != 0 {
		v, e := c.call(ctx, a.BlockHash, "getVerifier(uint32)", idArg(a.VerifierID), []int{4, 20, 20, 0, 0, 0, 8, 2, 1})
		if e != nil {
			return Assignment{}, e
		}
		if uint32(u64(v[0])) != a.VerifierID || addr(v[2]) == (protocol.Address{}) {
			return Assignment{}, fmt.Errorf("verifier relationship mismatch")
		}
		a.VerifierKey = addr(v[2])
	}
	if a.Trigger == 1 {
		anchor, e := c.call(ctx, a.BlockHash, "getAnchor(uint32,uint24)", idArg(sid), []int{0, 0, 0, 0, 0, 8, 8, 8, 8, 4, 4, 1}, idArg(a.Snapshot.Epoch))
		if e != nil {
			return Assignment{}, e
		}
		if uint32(u64(anchor[9])) != pid {
			return Assignment{}, fmt.Errorf("anchor profile mismatch")
		}
		a.AnchorRoot = b32(anchor[0])
		a.AnchorCount = uint32(u64(anchor[10]))
	}
	var again block
	if err = c.rpc(ctx, "eth_getBlockByNumber", []any{b.Number, false}, &again); err != nil {
		return Assignment{}, err
	}
	if again != b {
		return Assignment{}, fmt.Errorf("finalized block changed during snapshot")
	}
	if err = c.chain(ctx); err != nil {
		return Assignment{}, err
	}
	return a, nil
}
