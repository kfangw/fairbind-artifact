package protocol

import (
	"encoding/binary"
	"math/bits"
)

var keccakRoundConstants = [24]uint64{
	0x0000000000000001, 0x0000000000008082, 0x800000000000808a,
	0x8000000080008000, 0x000000000000808b, 0x0000000080000001,
	0x8000000080008081, 0x8000000000008009, 0x000000000000008a,
	0x0000000000000088, 0x0000000080008009, 0x000000008000000a,
	0x000000008000808b, 0x800000000000008b, 0x8000000000008089,
	0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
	0x000000000000800a, 0x800000008000000a, 0x8000000080008081,
	0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
}

var keccakRotation = [5][5]int{
	{0, 36, 3, 41, 18},
	{1, 44, 10, 45, 2},
	{62, 6, 43, 15, 61},
	{28, 55, 25, 21, 56},
	{27, 20, 39, 8, 14},
}

func keccak256(input []byte) Bytes32 {
	const rate = 136
	padded := append([]byte(nil), input...)
	padded = append(padded, 0x01)
	for len(padded)%rate != 0 {
		padded = append(padded, 0)
	}
	padded[len(padded)-1] |= 0x80

	var state [25]uint64
	for offset := 0; offset < len(padded); offset += rate {
		for lane := 0; lane < rate/8; lane++ {
			start := offset + lane*8
			state[lane] ^= binary.LittleEndian.Uint64(padded[start : start+8])
		}
		keccakF1600(&state)
	}

	var out Bytes32
	for lane := 0; lane < len(out)/8; lane++ {
		binary.LittleEndian.PutUint64(out[lane*8:], state[lane])
	}
	return out
}

func keccakF1600(state *[25]uint64) {
	for _, constant := range keccakRoundConstants {
		var columns [5]uint64
		for x := 0; x < 5; x++ {
			columns[x] = state[x] ^ state[x+5] ^ state[x+10] ^ state[x+15] ^ state[x+20]
		}
		var delta [5]uint64
		for x := 0; x < 5; x++ {
			delta[x] = columns[(x+4)%5] ^ bits.RotateLeft64(columns[(x+1)%5], 1)
		}
		for y := 0; y < 5; y++ {
			for x := 0; x < 5; x++ {
				state[x+5*y] ^= delta[x]
			}
		}

		var moved [25]uint64
		for y := 0; y < 5; y++ {
			for x := 0; x < 5; x++ {
				moved[y+5*((2*x+3*y)%5)] = bits.RotateLeft64(state[x+5*y], keccakRotation[x][y])
			}
		}
		for y := 0; y < 5; y++ {
			for x := 0; x < 5; x++ {
				state[x+5*y] = moved[x+5*y] ^ (^moved[(x+1)%5+5*y] & moved[(x+2)%5+5*y])
			}
		}
		state[0] ^= constant
	}
}
