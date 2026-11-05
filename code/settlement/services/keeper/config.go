package keeper

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	"example.org/fairbind/protocol"
)

// Config is the JSON configuration of the keeper process.
type Config struct {
	RPCURL            string   `json:"rpcUrl"`
	ChainID           uint64   `json:"chainId"`
	Contract          string   `json:"contract"`
	From              string   `json:"from"`
	Gas               uint64   `json:"gas"`
	StateFile         string   `json:"stateFile"`
	StartBlock        uint64   `json:"startBlock"`
	PollIntervalMs    uint64   `json:"pollIntervalMs"`
	RPCTimeoutMs      uint64   `json:"rpcTimeoutMs"`
	MaxLogRange       uint64   `json:"maxLogRange"`
	ResendAfterBlocks uint64   `json:"resendAfterBlocks"`
	Actions           []string `json:"actions,omitempty"`
	// ReceiptsDir is the published receipt list (A-LEAF) as a directory of
	// JSON files, one per purchase (DirReceiptList). Optional.
	ReceiptsDir string `json:"receiptsDir,omitempty"`
}

// LoadConfig reads a JSON file and rejects unknown fields and unsafe values.
func LoadConfig(path string) (Config, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return Config{}, err
	}
	return ParseConfig(raw)
}

func ParseConfig(raw []byte) (Config, error) {
	var c Config
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&c); err != nil {
		return Config{}, fmt.Errorf("keeper config: %w", err)
	}
	if dec.More() {
		return Config{}, fmt.Errorf("keeper config: trailing data")
	}
	return c, c.Validate()
}

func (c Config) Validate() error {
	if err := checkURL(c.RPCURL); err != nil {
		return err
	}
	if c.ChainID == 0 || c.StateFile == "" || c.Gas == 0 || c.PollIntervalMs == 0 || c.RPCTimeoutMs == 0 {
		return fmt.Errorf("keeper config: chainId, gas, stateFile, pollIntervalMs and rpcTimeoutMs are required")
	}
	if c.MaxLogRange == 0 || c.MaxLogRange > 100000 {
		return fmt.Errorf("keeper config: maxLogRange must be in 1..100000")
	}
	if c.ResendAfterBlocks == 0 {
		return fmt.Errorf("keeper config: resendAfterBlocks must be positive")
	}
	for _, s := range []string{c.Contract, c.From} {
		if a, err := ParseHexAddress(s); err != nil || a == (protocol.Address{}) {
			return fmt.Errorf("keeper config: invalid address %q", s)
		}
	}
	for _, a := range c.Actions {
		if _, ok := signatures[a]; !ok {
			return fmt.Errorf("keeper config: unknown action %q", a)
		}
	}
	return nil
}

// EnabledActions returns nil when every action is enabled.
func (c Config) EnabledActions() map[string]bool {
	if len(c.Actions) == 0 {
		return nil
	}
	m := map[string]bool{}
	for _, a := range c.Actions {
		m[a] = true
	}
	return m
}

func (c Config) PollInterval() time.Duration {
	return time.Duration(c.PollIntervalMs) * time.Millisecond
}

func (c Config) RPCTimeout() time.Duration {
	return time.Duration(c.RPCTimeoutMs) * time.Millisecond
}

func ParseHexAddress(s string) (protocol.Address, error) {
	var a protocol.Address
	if len(s) != 42 || !strings.HasPrefix(s, "0x") {
		return a, fmt.Errorf("address must be 0x and 40 hex digits")
	}
	raw, err := hex.DecodeString(s[2:])
	if err != nil {
		return a, err
	}
	return protocol.ParseAddress(raw)
}
