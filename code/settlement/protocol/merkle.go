package protocol

import (
	"fmt"
	"sort"
)

var (
	EpochLeafDomain = Keccak256([]byte("fairbind/epoch-leaf/v1"))
	EpochNodeDomain = Keccak256([]byte("fairbind/epoch-node/v1"))
)

type ReceiptEntry struct {
	Nonce       Bytes32
	ReceiptLeaf Bytes32
}

type ReceiptProof struct {
	Index    uint32
	Count    uint32
	Siblings []Bytes32
}

func ReceiptEntryHash(entry ReceiptEntry) Bytes32 {
	return Keccak256(EpochLeafDomain[:], entry.Nonce[:], entry.ReceiptLeaf[:])
}

func ReceiptRoot(entries []ReceiptEntry) (Bytes32, error) {
	if len(entries) == 0 {
		return Bytes32{}, fmt.Errorf("empty receipt tree")
	}
	ordered := append([]ReceiptEntry(nil), entries...)
	sort.Slice(ordered, func(i, j int) bool { return bytes32Less(ordered[i].Nonce, ordered[j].Nonce) })
	leaves := make([]Bytes32, len(ordered))
	for i, entry := range ordered {
		if i > 0 && entry.Nonce == ordered[i-1].Nonce {
			return Bytes32{}, fmt.Errorf("duplicate nonce")
		}
		leaves[i] = ReceiptEntryHash(entry)
	}
	return merkleRoot(leaves), nil
}

func VerifyReceiptProof(root Bytes32, entry ReceiptEntry, proof ReceiptProof) bool {
	if proof.Count == 0 || proof.Index >= proof.Count {
		return false
	}
	hash := ReceiptEntryHash(entry)
	index := proof.Index
	width := proof.Count
	for _, sibling := range proof.Siblings {
		if index%2 == 0 {
			hash = Keccak256(EpochNodeDomain[:], hash[:], sibling[:])
		} else {
			hash = Keccak256(EpochNodeDomain[:], sibling[:], hash[:])
		}
		index /= 2
		width = (width + 1) / 2
	}
	return width == 1 && hash == root
}

func merkleRoot(level []Bytes32) Bytes32 {
	for len(level) > 1 {
		next := make([]Bytes32, (len(level)+1)/2)
		for i := range next {
			left := level[2*i]
			right := left
			if 2*i+1 < len(level) {
				right = level[2*i+1]
			}
			next[i] = Keccak256(EpochNodeDomain[:], left[:], right[:])
		}
		level = next
	}
	return level[0]
}

func bytes32Less(left, right Bytes32) bool {
	for i := range left {
		if left[i] != right[i] {
			return left[i] < right[i]
		}
	}
	return false
}
