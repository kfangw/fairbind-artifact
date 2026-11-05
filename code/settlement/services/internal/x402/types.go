// Package x402 holds the wire types and helpers shared by the seller, buyer
// and facilitator services: x402 version 2 messages with the FairBind
// extension, header encodings, EIP-712 digests the services sign or check,
// receipt trees with inclusion proofs, and serve bundles.
package x402

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"strings"

	"example.org/fairbind/protocol"
)

// H32 is a bytes32 encoded as a 0x-prefixed lowercase hex JSON string.
type H32 protocol.Bytes32

// H16 is a bytes16 encoded as a 0x-prefixed lowercase hex JSON string.
type H16 protocol.Bytes16

// Addr is an address encoded as a 0x-prefixed lowercase hex JSON string.
type Addr protocol.Address

// U64 is an unsigned integer encoded as a decimal JSON string.
type U64 uint64

func decodeFixed(text string, out []byte) error {
	if !strings.HasPrefix(text, "0x") || len(text) != 2+2*len(out) {
		return fmt.Errorf("expected 0x-prefixed %d-byte hex", len(out))
	}
	raw, err := hex.DecodeString(text[2:])
	if err != nil {
		return err
	}
	copy(out, raw)
	return nil
}

func unmarshalFixed(data []byte, out []byte) error {
	var s string
	if err := json.Unmarshal(data, &s); err != nil {
		return err
	}
	return decodeFixed(s, out)
}

func (h H32) String() string                   { return "0x" + hex.EncodeToString(h[:]) }
func (h H32) MarshalJSON() ([]byte, error)     { return json.Marshal(h.String()) }
func (h *H32) UnmarshalJSON(data []byte) error { return unmarshalFixed(data, h[:]) }
func (h H16) String() string                   { return "0x" + hex.EncodeToString(h[:]) }
func (h H16) MarshalJSON() ([]byte, error)     { return json.Marshal(h.String()) }
func (h *H16) UnmarshalJSON(data []byte) error { return unmarshalFixed(data, h[:]) }
func (a Addr) String() string                  { return "0x" + hex.EncodeToString(a[:]) }
func (a Addr) MarshalJSON() ([]byte, error)    { return json.Marshal(a.String()) }
func (a *Addr) UnmarshalJSON(data []byte) error {
	var s string
	if err := json.Unmarshal(data, &s); err != nil {
		return err
	}
	return decodeFixed(strings.ToLower(s), a[:])
}
func (u U64) MarshalJSON() ([]byte, error) { return json.Marshal(strconv.FormatUint(uint64(u), 10)) }
func (u *U64) UnmarshalJSON(data []byte) error {
	var s string
	if err := json.Unmarshal(data, &s); err != nil {
		return err
	}
	if s == "" || (len(s) > 1 && s[0] == '0') {
		return errors.New("noncanonical decimal string")
	}
	v, err := strconv.ParseUint(s, 10, 64)
	if err != nil {
		return err
	}
	*u = U64(v)
	return nil
}

// ParseH32 parses a 0x-prefixed bytes32.
func ParseH32(s string) (H32, error) {
	var h H32
	return h, decodeFixed(strings.ToLower(s), h[:])
}

// ParseAddr parses a 0x-prefixed address in any letter case.
func ParseAddr(s string) (Addr, error) {
	var a Addr
	return a, decodeFixed(strings.ToLower(s), a[:])
}

// ParseH16 parses a 0x-prefixed bytes16.
func ParseH16(s string) (H16, error) {
	var h H16
	return h, decodeFixed(strings.ToLower(s), h[:])
}

// Hex returns 0x-prefixed lowercase hex for arbitrary bytes.
func Hex(b []byte) string { return "0x" + hex.EncodeToString(b) }

// ParseHex decodes 0x-prefixed hex of any length.
func ParseHex(s string) ([]byte, error) {
	if !strings.HasPrefix(s, "0x") {
		return nil, errors.New("missing 0x prefix")
	}
	return hex.DecodeString(s[2:])
}
