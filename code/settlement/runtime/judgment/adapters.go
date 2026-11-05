package judgment

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"example.org/fairbind/protocol"
	"example.org/fairbind/runtime/verifier"
	"io"
	"net/http"
	"net/netip"
	"net/url"
	"os/exec"
	"strings"
	"time"
)

// KeystoreSigner keeps secrets in operator-owned encrypted keystore/password
// files, never in bundles, environment dumps, or returned error diagnostics.
type KeystoreSigner struct{ CastPath, KeystorePath, PasswordFile string }

func (s KeystoreSigner) SignDigest(ctx context.Context, h protocol.Bytes32) ([]byte, error) {
	if s.CastPath == "" || s.KeystorePath == "" || s.PasswordFile == "" {
		return nil, fmt.Errorf("signer configuration missing")
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	version, e := exec.CommandContext(ctx, s.CastPath, "--version").Output()
	if e != nil || !strings.Contains(string(version), "Commit SHA: "+verifier.CastCommit+"\n") {
		return nil, fmt.Errorf("unsupported signer build")
	}
	out, e := exec.CommandContext(ctx, s.CastPath, "wallet", "sign", "--no-hash", "--keystore", s.KeystorePath, "--password-file", s.PasswordFile, fmt.Sprintf("0x%x", h)).Output()
	if e != nil {
		return nil, fmt.Errorf("keystore signing failed")
	}
	raw := strings.TrimSpace(string(out))
	if len(raw) != 132 || !strings.HasPrefix(raw, "0x") {
		return nil, fmt.Errorf("invalid signer output")
	}
	return hex.DecodeString(raw[2:])
}

// LocalRelay is intentionally limited to an operator-owned loopback RPC with an
// unlocked test account. It cannot submit to a public endpoint.
type LocalRelay struct {
	URL            string
	ChainID        uint64
	Contract, From protocol.Address
	Gas            uint64
}

func (r LocalRelay) Send(ctx context.Context, to protocol.Address, data []byte) (protocol.Bytes32, error) {
	var zero protocol.Bytes32
	u, e := url.Parse(r.URL)
	if e != nil {
		return zero, e
	}
	ip, e := netip.ParseAddr(u.Hostname())
	if e != nil || !ip.IsLoopback() || u.Scheme != "http" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || to != r.Contract || r.From == (protocol.Address{}) || r.ChainID == 0 || r.Gas == 0 || len(data) > 1048576 {
		return zero, fmt.Errorf("invalid local relay configuration")
	}
	client := &http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	rpc := func(method string, params any) (string, error) {
		b, _ := json.Marshal(map[string]any{"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
		req, e := http.NewRequestWithContext(ctx, "POST", r.URL, bytes.NewReader(b))
		if e != nil {
			return "", e
		}
		req.Header.Set("Content-Type", "application/json")
		res, e := client.Do(req)
		if e != nil {
			return "", e
		}
		defer res.Body.Close()
		raw, e := io.ReadAll(io.LimitReader(res.Body, 65537))
		if e != nil || len(raw) > 65536 || res.StatusCode != 200 {
			return "", fmt.Errorf("RPC unavailable")
		}
		var msg struct {
			JSONRPC string          `json:"jsonrpc"`
			ID      int             `json:"id"`
			Result  string          `json:"result"`
			Error   json.RawMessage `json:"error"`
		}
		if json.Unmarshal(raw, &msg) != nil || msg.JSONRPC != "2.0" || msg.ID != 1 || len(msg.Error) > 0 && string(msg.Error) != "null" {
			return "", fmt.Errorf("RPC error")
		}
		return msg.Result, nil
	}
	chain, e := rpc("eth_chainId", []any{})
	if e != nil || chain != fmt.Sprintf("0x%x", r.ChainID) {
		return zero, fmt.Errorf("chain mismatch")
	}
	tx, e := rpc("eth_sendTransaction", []any{map[string]string{"from": fmt.Sprintf("0x%x", r.From), "to": fmt.Sprintf("0x%x", to), "data": "0x" + hex.EncodeToString(data), "gas": fmt.Sprintf("0x%x", r.Gas)}})
	if e != nil {
		return zero, e
	}
	if len(tx) != 66 || !strings.HasPrefix(tx, "0x") {
		return zero, fmt.Errorf("invalid transaction hash")
	}
	b, e := hex.DecodeString(tx[2:])
	if e != nil {
		return zero, e
	}
	copy(zero[:], b)
	return zero, nil
}
