package protocol

// VerdictTypeHash is the normative FairBindVerdict EIP-712 type hash.
var VerdictTypeHash = Keccak256([]byte("FairBindVerdict(uint8 version,bytes32 nonce,uint8 stage,uint8 attempt,uint32 verifierId,uint8 verdict,bytes32 evidenceHash)"))

// Verdict codes signed by verifiers and stored by the contract's Verdict enum.
const (
	VerdictNone         uint8 = 0
	VerdictPass         uint8 = 1
	VerdictFail         uint8 = 2
	VerdictInconclusive uint8 = 3
)

// VerdictCode maps an evidence-envelope verdict name to its signed code. It
// returns VerdictNone for an unknown name.
func VerdictCode(name string) uint8 {
	switch name {
	case "PASS":
		return VerdictPass
	case "FAIL":
		return VerdictFail
	case "INCONCLUSIVE":
		return VerdictInconclusive
	}
	return VerdictNone
}

// SignedVerdict contains the message fields committed by a verifier signature.
// The signature itself is supplied separately and is not part of this message.
// Hashing does not validate the active assignment, timing, or predicate result.
type SignedVerdict struct {
	Version      uint8
	Nonce        Bytes32
	Stage        uint8
	Attempt      uint8
	VerifierID   uint32
	Verdict      uint8
	EvidenceHash Bytes32
}

// VerdictStructHash hashes ABI words in the normative field order.
func VerdictStructHash(verdict SignedVerdict) Bytes32 {
	return Keccak256(
		VerdictTypeHash[:], wordUint64(uint64(verdict.Version)),
		verdict.Nonce[:], wordUint64(uint64(verdict.Stage)),
		wordUint64(uint64(verdict.Attempt)), wordUint32(verdict.VerifierID),
		wordUint64(uint64(verdict.Verdict)), verdict.EvidenceHash[:],
	)
}

// VerdictDigest returns the EIP-712 signing digest in the same FairBind domain
// as ReceiptDigest. This function neither signs nor verifies a signature.
// Like ReceiptDigest, the API represents chain IDs with uint64.
func VerdictDigest(chainID uint64, contract Address, verdict SignedVerdict) Bytes32 {
	nameHash := Keccak256([]byte("FairBind"))
	versionHash := Keccak256([]byte("1"))
	domain := Keccak256(
		EIP712DomainTypeHash[:], nameHash[:], versionHash[:],
		wordUint64(chainID), wordAddress(contract),
	)
	structHash := VerdictStructHash(verdict)
	return Keccak256([]byte{0x19, 0x01}, domain[:], structHash[:])
}
