package protocol

import (
	"encoding/binary"
	"fmt"
)

type Address [20]byte
type Bytes16 [16]byte
type Bytes32 [32]byte

var (
	KeyDomain      = Keccak256([]byte("fairbind/key/v1"))
	PurchaseDomain = Keccak256([]byte("fairbind/v1"))
)

func Keccak256(parts ...[]byte) Bytes32 {
	length := 0
	for _, part := range parts {
		length += len(part)
	}
	input := make([]byte, 0, length)
	for _, part := range parts {
		input = append(input, part...)
	}
	return keccak256(input)
}

func DeriveKeyID(chainID uint64, contract Address, sellerID uint32, buyer Address, key Bytes16) Bytes32 {
	return Keccak256(
		wordBytes32(KeyDomain), wordUint64(chainID), wordAddress(contract),
		wordUint32(sellerID), wordAddress(buyer), wordBytes16(key),
	)
}

func DeriveNonce(chainID uint64, contract Address, sellerID, profileID uint32, claimsHash Bytes32, buyer Address, key Bytes16, requestHash Bytes32) Bytes32 {
	return Keccak256(
		wordBytes32(PurchaseDomain), wordUint64(chainID), wordAddress(contract),
		wordUint32(sellerID), wordUint32(profileID), wordBytes32(claimsHash),
		wordAddress(buyer), wordBytes16(key), wordBytes32(requestHash),
	)
}

func ParseAddress(raw []byte) (Address, error) {
	var out Address
	if len(raw) != len(out) {
		return out, fmt.Errorf("address must be %d bytes", len(out))
	}
	copy(out[:], raw)
	return out, nil
}

func wordUint32(value uint32) []byte {
	out := make([]byte, 32)
	binary.BigEndian.PutUint32(out[28:], value)
	return out
}

func wordUint64(value uint64) []byte {
	out := make([]byte, 32)
	binary.BigEndian.PutUint64(out[24:], value)
	return out
}

func wordAddress(value Address) []byte {
	out := make([]byte, 32)
	copy(out[12:], value[:])
	return out
}

func wordBytes16(value Bytes16) []byte {
	out := make([]byte, 32)
	copy(out, value[:])
	return out
}

func wordBytes32(value Bytes32) []byte {
	out := make([]byte, 32)
	copy(out, value[:])
	return out
}
