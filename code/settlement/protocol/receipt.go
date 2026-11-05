package protocol

var (
	EIP712DomainTypeHash = Keccak256([]byte("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"))
	ReceiptTypeHash      = Keccak256([]byte("FairBindReceipt(uint8 version,uint32 sellerId,uint32 profileId,bytes32 nonce,bytes32 requestHash,bytes32 responseHash,bytes32 claimsHash,bytes32 predicateCommitment,uint24 epoch,uint64 issuedAt)"))
	ResponseNodeDomain   = Keccak256([]byte("fairbind/response-node/v1"))
)

const ResponseChunkBytes = 16_384

type Receipt struct {
	Version             uint8
	SellerID            uint32
	ProfileID           uint32
	Nonce               Bytes32
	RequestHash         Bytes32
	ResponseHash        Bytes32
	ClaimsHash          Bytes32
	PredicateCommitment Bytes32
	Epoch               uint32
	IssuedAt            uint64
}

func ReceiptDigest(chainID uint64, contract Address, receipt Receipt) Bytes32 {
	nameHash := Keccak256([]byte("FairBind"))
	versionHash := Keccak256([]byte("1"))
	domain := Keccak256(
		EIP712DomainTypeHash[:],
		nameHash[:],
		versionHash[:],
		wordUint64(chainID),
		wordAddress(contract),
	)
	structHash := Keccak256(
		ReceiptTypeHash[:], wordUint64(uint64(receipt.Version)),
		wordUint32(receipt.SellerID), wordUint32(receipt.ProfileID),
		receipt.Nonce[:], receipt.RequestHash[:], receipt.ResponseHash[:],
		receipt.ClaimsHash[:], receipt.PredicateCommitment[:],
		wordUint32(receipt.Epoch), wordUint64(receipt.IssuedAt),
	)
	return Keccak256([]byte{0x19, 0x01}, domain[:], structHash[:])
}

func ResponseHash(body []byte) Bytes32 {
	count := (len(body) + ResponseChunkBytes - 1) / ResponseChunkBytes
	if count == 0 {
		count = 1
	}
	leaves := make([]Bytes32, count)
	for i := range leaves {
		start := i * ResponseChunkBytes
		end := start + ResponseChunkBytes
		if end > len(body) {
			end = len(body)
		}
		leaves[i] = Keccak256(body[start:end])
	}
	return responseRoot(leaves)
}

func responseRoot(level []Bytes32) Bytes32 {
	for len(level) > 1 {
		next := make([]Bytes32, (len(level)+1)/2)
		for i := range next {
			left := level[2*i]
			right := left
			if 2*i+1 < len(level) {
				right = level[2*i+1]
			}
			next[i] = Keccak256(ResponseNodeDomain[:], left[:], right[:])
		}
		level = next
	}
	return level[0]
}
