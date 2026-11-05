// Package ethkey implements the secp256k1 operations the services need:
// address derivation, deterministic (RFC 6979) low-s signing of a 32-byte
// digest in r||s||v form with v in {27, 28}, and public-key recovery.
//
// It uses math/big and is not constant time. It is intended for local test
// deployments and development keys. Production signing keys should use an
// external signer (see Signer).
package ethkey

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"math/big"
	"os"
	"strings"

	"example.org/fairbind/protocol"
)

var (
	curveP, _  = new(big.Int).SetString("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F", 16)
	curveN, _  = new(big.Int).SetString("FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141", 16)
	curveGx, _ = new(big.Int).SetString("79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798", 16)
	curveGy, _ = new(big.Int).SetString("483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8", 16)
	halfN      = new(big.Int).Rsh(curveN, 1)
	sqrtExp    = new(big.Int).Rsh(new(big.Int).Add(curveP, big.NewInt(1)), 2)
)

// Signer signs a 32-byte digest without hashing it again.
type Signer interface {
	SignDigest(ctx context.Context, digest protocol.Bytes32) ([]byte, error)
}

type point struct{ x, y *big.Int } // nil x means the point at infinity

func (p point) inf() bool { return p.x == nil }

func mod(v *big.Int) *big.Int { return v.Mod(v, curveP) }

func add(a, b point) point {
	if a.inf() {
		return b
	}
	if b.inf() {
		return a
	}
	var lambda *big.Int
	if a.x.Cmp(b.x) == 0 {
		if new(big.Int).Add(a.y, b.y).Mod(new(big.Int).Add(a.y, b.y), curveP).Sign() == 0 {
			return point{}
		}
		num := mod(new(big.Int).Mul(big.NewInt(3), new(big.Int).Mul(a.x, a.x)))
		den := new(big.Int).ModInverse(mod(new(big.Int).Lsh(a.y, 1)), curveP)
		lambda = mod(num.Mul(num, den))
	} else {
		num := mod(new(big.Int).Sub(b.y, a.y))
		den := new(big.Int).ModInverse(mod(new(big.Int).Sub(b.x, a.x)), curveP)
		lambda = mod(num.Mul(num, den))
	}
	x := mod(new(big.Int).Sub(new(big.Int).Sub(new(big.Int).Mul(lambda, lambda), a.x), b.x))
	y := mod(new(big.Int).Sub(new(big.Int).Mul(lambda, new(big.Int).Sub(a.x, x)), a.y))
	return point{x, y}
}

func mul(p point, k *big.Int) point {
	out := point{}
	for i := k.BitLen() - 1; i >= 0; i-- {
		out = add(out, out)
		if k.Bit(i) == 1 {
			out = add(out, p)
		}
	}
	return out
}

var generator = point{curveGx, curveGy}

// PrivateKey is a secp256k1 scalar in [1, n-1].
type PrivateKey struct{ d *big.Int }

// ParsePrivateKey accepts 32 bytes as 0x-prefixed or bare hex.
func ParsePrivateKey(text string) (*PrivateKey, error) {
	text = strings.TrimPrefix(strings.TrimSpace(text), "0x")
	raw, err := hex.DecodeString(text)
	if err != nil || len(raw) != 32 {
		return nil, errors.New("private key must be 32 bytes of hex")
	}
	d := new(big.Int).SetBytes(raw)
	if d.Sign() == 0 || d.Cmp(curveN) >= 0 {
		return nil, errors.New("private key out of range")
	}
	return &PrivateKey{d: d}, nil
}

// LoadPrivateKeyFile reads a hex private key from a file. The file should be
// readable by its owner only.
func LoadPrivateKeyFile(path string) (*PrivateKey, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return ParsePrivateKey(string(raw))
}

func pubAddress(p point) protocol.Address {
	buf := make([]byte, 64)
	p.x.FillBytes(buf[:32])
	p.y.FillBytes(buf[32:])
	h := protocol.Keccak256(buf)
	var a protocol.Address
	copy(a[:], h[12:])
	return a
}

// Address returns the Ethereum address of the key.
func (k *PrivateKey) Address() protocol.Address { return pubAddress(mul(generator, k.d)) }

func hmacSum(key []byte, parts ...[]byte) []byte {
	m := hmac.New(sha256.New, key)
	for _, p := range parts {
		m.Write(p)
	}
	return m.Sum(nil)
}

// Sign returns r||s||v with a low s and v in {27, 28}. The nonce follows
// RFC 6979 with HMAC-SHA256, so the output is deterministic.
func (k *PrivateKey) Sign(digest protocol.Bytes32) []byte {
	x := make([]byte, 32)
	k.d.FillBytes(x)
	h := new(big.Int).SetBytes(digest[:])
	h.Mod(h, curveN)
	hb := make([]byte, 32)
	h.FillBytes(hb)
	v := bytes.Repeat([]byte{1}, 32)
	kk := make([]byte, 32)
	kk = hmacSum(kk, v, []byte{0}, x, hb)
	v = hmacSum(kk, v)
	kk = hmacSum(kk, v, []byte{1}, x, hb)
	v = hmacSum(kk, v)
	e := new(big.Int).SetBytes(digest[:])
	for {
		v = hmacSum(kk, v)
		nonce := new(big.Int).SetBytes(v)
		if nonce.Sign() > 0 && nonce.Cmp(curveN) < 0 {
			r := mul(generator, nonce)
			rx := new(big.Int).Mod(r.x, curveN)
			if rx.Sign() != 0 {
				s := new(big.Int).Mul(rx, k.d)
				s.Add(s, e)
				s.Mul(s, new(big.Int).ModInverse(nonce, curveN))
				s.Mod(s, curveN)
				if s.Sign() != 0 {
					recid := byte(r.y.Bit(0))
					if r.x.Cmp(curveN) >= 0 {
						recid |= 2
					}
					if s.Cmp(halfN) > 0 {
						s.Sub(curveN, s)
						recid ^= 1
					}
					out := make([]byte, 65)
					rx.FillBytes(out[:32])
					s.FillBytes(out[32:64])
					out[64] = 27 + recid&1
					return out
				}
			}
		}
		kk = hmacSum(kk, v, []byte{0})
		v = hmacSum(kk, v)
	}
}

// SignDigest implements Signer.
func (k *PrivateKey) SignDigest(_ context.Context, digest protocol.Bytes32) ([]byte, error) {
	return k.Sign(digest), nil
}

// Recover returns the signer of a canonical 65-byte signature. It rejects a
// high s, a zero r or s, and a v outside {27, 28}.
func Recover(digest protocol.Bytes32, sig []byte) (protocol.Address, error) {
	var zero protocol.Address
	if len(sig) != 65 || (sig[64] != 27 && sig[64] != 28) {
		return zero, errors.New("noncanonical signature")
	}
	r := new(big.Int).SetBytes(sig[:32])
	s := new(big.Int).SetBytes(sig[32:64])
	if r.Sign() == 0 || s.Sign() == 0 || r.Cmp(curveN) >= 0 || s.Cmp(halfN) > 0 {
		return zero, errors.New("noncanonical signature")
	}
	// y^2 = x^3 + 7
	c := new(big.Int).Exp(r, big.NewInt(3), curveP)
	c.Add(c, big.NewInt(7))
	c.Mod(c, curveP)
	y := new(big.Int).Exp(c, sqrtExp, curveP)
	if new(big.Int).Exp(y, big.NewInt(2), curveP).Cmp(c) != 0 {
		return zero, errors.New("invalid signature point")
	}
	if y.Bit(0) != uint(sig[64]-27) {
		y.Sub(curveP, y)
	}
	e := new(big.Int).SetBytes(digest[:])
	rinv := new(big.Int).ModInverse(r, curveN)
	u1 := new(big.Int).Mul(e, rinv)
	u1.Neg(u1).Mod(u1, curveN)
	u2 := new(big.Int).Mul(s, rinv)
	u2.Mod(u2, curveN)
	q := add(mul(generator, u1), mul(point{r, y}, u2))
	if q.inf() {
		return zero, errors.New("invalid signature")
	}
	return pubAddress(q), nil
}

// Verify checks that sig is a canonical signature of digest by want.
func Verify(want protocol.Address, digest protocol.Bytes32, sig []byte) error {
	got, err := Recover(digest, sig)
	if err != nil {
		return err
	}
	if got != want {
		return fmt.Errorf("signature recovers %x, want %x", got, want)
	}
	return nil
}
