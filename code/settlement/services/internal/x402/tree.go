package x402

import (
	"errors"
	"sort"

	"example.org/fairbind/protocol"
)

var epochNodeDomain = protocol.Keccak256([]byte("fairbind/epoch-node/v1"))

// Entry is one (nonce, receiptLeaf) pair of an epoch tree.
type Entry struct {
	Nonce       H32 `json:"nonce"`
	ReceiptLeaf H32 `json:"receiptLeaf"`
}

// Proof is the JSON form of a receipt inclusion proof.
type Proof struct {
	Index    uint32 `json:"index"`
	Count    uint32 `json:"count"`
	Siblings []H32  `json:"siblings"`
}

// Typed converts the proof to the protocol type.
func (p Proof) Typed() protocol.ReceiptProof {
	s := make([]protocol.Bytes32, len(p.Siblings))
	for i, h := range p.Siblings {
		s[i] = protocol.Bytes32(h)
	}
	return protocol.ReceiptProof{Index: p.Index, Count: p.Count, Siblings: s}
}

// Tree is an epoch receipt tree (merkle-v1) with its levels retained.
type Tree struct {
	Entries []Entry
	levels  [][]protocol.Bytes32
}

// BuildTree sorts entries by nonce and builds all levels.
func BuildTree(entries []Entry) (*Tree, error) {
	if len(entries) == 0 {
		return nil, errors.New("empty receipt tree")
	}
	sorted := append([]Entry(nil), entries...)
	sort.Slice(sorted, func(i, j int) bool {
		return string(sorted[i].Nonce[:]) < string(sorted[j].Nonce[:])
	})
	level := make([]protocol.Bytes32, len(sorted))
	for i, e := range sorted {
		if i > 0 && e.Nonce == sorted[i-1].Nonce {
			return nil, errors.New("duplicate nonce")
		}
		level[i] = protocol.ReceiptEntryHash(protocol.ReceiptEntry{Nonce: protocol.Bytes32(e.Nonce), ReceiptLeaf: protocol.Bytes32(e.ReceiptLeaf)})
	}
	t := &Tree{Entries: sorted, levels: [][]protocol.Bytes32{level}}
	for len(level) > 1 {
		next := make([]protocol.Bytes32, (len(level)+1)/2)
		for i := range next {
			left := level[2*i]
			right := left
			if 2*i+1 < len(level) {
				right = level[2*i+1]
			}
			next[i] = protocol.Keccak256(epochNodeDomain[:], left[:], right[:])
		}
		t.levels = append(t.levels, next)
		level = next
	}
	return t, nil
}

// EntryHashes returns level zero of the tree, the entry hashes in nonce order.
func (t *Tree) EntryHashes() []protocol.Bytes32 {
	return append([]protocol.Bytes32(nil), t.levels[0]...)
}

// StrictlyAscending reports whether the nonces of entries increase strictly,
// as the contract requires of an anchor's list (ADR 0026).
func StrictlyAscending(entries []Entry) bool {
	for i := 1; i < len(entries); i++ {
		if string(entries[i].Nonce[:]) <= string(entries[i-1].Nonce[:]) {
			return false
		}
	}
	return true
}

// EntryHashes returns the entry hashes of entries in the given order.
func EntryHashes(entries []Entry) []protocol.Bytes32 {
	out := make([]protocol.Bytes32, len(entries))
	for i, e := range entries {
		out[i] = protocol.ReceiptEntryHash(protocol.ReceiptEntry{Nonce: protocol.Bytes32(e.Nonce), ReceiptLeaf: protocol.Bytes32(e.ReceiptLeaf)})
	}
	return out
}

// EntriesRoot is the merkle-v1 root over an ordered level zero, as the
// contract computes it in anchor. An empty list has the zero root.
func EntriesRoot(level []protocol.Bytes32) protocol.Bytes32 {
	if len(level) == 0 {
		return protocol.Bytes32{}
	}
	for len(level) > 1 {
		next := make([]protocol.Bytes32, (len(level)+1)/2)
		for i := range next {
			left := level[2*i]
			right := left
			if 2*i+1 < len(level) {
				right = level[2*i+1]
			}
			next[i] = protocol.Keccak256(epochNodeDomain[:], left[:], right[:])
		}
		level = next
	}
	return level[0]
}

// Root returns the tree root.
func (t *Tree) Root() protocol.Bytes32 { return t.levels[len(t.levels)-1][0] }

// Count returns the number of entries.
func (t *Tree) Count() uint32 { return uint32(len(t.Entries)) }

// Prove returns the inclusion proof for nonce.
func (t *Tree) Prove(nonce protocol.Bytes32) (Entry, Proof, bool) {
	idx := sort.Search(len(t.Entries), func(i int) bool { return string(t.Entries[i].Nonce[:]) >= string(nonce[:]) })
	if idx == len(t.Entries) || protocol.Bytes32(t.Entries[idx].Nonce) != nonce {
		return Entry{}, Proof{}, false
	}
	p := Proof{Index: uint32(idx), Count: t.Count(), Siblings: []H32{}}
	i := idx
	for _, level := range t.levels[:len(t.levels)-1] {
		sib := i ^ 1
		if sib >= len(level) {
			sib = i
		}
		p.Siblings = append(p.Siblings, H32(level[sib]))
		i /= 2
	}
	return t.Entries[idx], p, true
}
