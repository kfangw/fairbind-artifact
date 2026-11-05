package judgment

import (
	"encoding/binary"
	"fmt"
	"example.org/fairbind/protocol"
)

const JudgeSignature = "judge((uint8,bytes32,uint8,uint8,uint32,uint8,bytes32),bytes,(uint8,uint32,uint32,bytes32,bytes32,bytes32,bytes32,bytes32,uint24,uint64),bytes,(uint32,uint32,bytes32[]))"

func word(v uint64) []byte { b := make([]byte, 32); binary.BigEndian.PutUint64(b[24:], v); return b }
func dyn(b []byte) []byte {
	out := append(word(uint64(len(b))), b...)
	return append(out, make([]byte, (32-len(b)%32)%32)...)
}

// EncodeJudge uses the deployed ABI, not packed encoding or textual interpolation.
func EncodeJudge(v protocol.SignedVerdict, vs []byte, r protocol.Receipt, rs []byte, p protocol.ReceiptProof) ([]byte, error) {
	if len(vs) != 65 || len(rs) != 65 || len(p.Siblings) > 32 || r.Epoch > 0xffffff {
		return nil, fmt.Errorf("invalid ABI input")
	}
	head := []byte{}
	add := func(b []byte) { head = append(head, b...) }
	add(word(uint64(v.Version)))
	add(v.Nonce[:])
	add(word(uint64(v.Stage)))
	add(word(uint64(v.Attempt)))
	add(word(uint64(v.VerifierID)))
	add(word(uint64(v.Verdict)))
	add(v.EvidenceHash[:])
	// Seven verdict words + one signature offset + ten receipt words + two offsets.
	const size = 20 * 32
	vd := dyn(vs)
	rd := dyn(rs)
	proof := append(word(uint64(p.Index)), word(uint64(p.Count))...)
	proof = append(proof, word(96)...)
	proof = append(proof, word(uint64(len(p.Siblings)))...)
	for _, h := range p.Siblings {
		proof = append(proof, h[:]...)
	}
	add(word(size))
	add(word(uint64(r.Version)))
	add(word(uint64(r.SellerID)))
	add(word(uint64(r.ProfileID)))
	add(r.Nonce[:])
	add(r.RequestHash[:])
	add(r.ResponseHash[:])
	add(r.ClaimsHash[:])
	add(r.PredicateCommitment[:])
	add(word(uint64(r.Epoch)))
	add(word(r.IssuedAt))
	add(word(uint64(size + len(vd))))
	add(word(uint64(size + len(vd) + len(rd))))
	selector := protocol.Keccak256([]byte(JudgeSignature))
	out := append([]byte{}, selector[:4]...)
	out = append(out, head...)
	out = append(out, vd...)
	out = append(out, rd...)
	return append(out, proof...), nil
}
