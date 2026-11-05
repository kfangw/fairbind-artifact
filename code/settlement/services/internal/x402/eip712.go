package x402

import (
	"encoding/binary"
	"errors"
	"fmt"

	"example.org/fairbind/protocol"
)

var (
	domainTypeHash        = protocol.Keccak256([]byte("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"))
	receiveTypeHash       = protocol.Keccak256([]byte("ReceiveWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"))
	serveAuthTypeHash     = protocol.Keccak256([]byte("FairBindServeAuthorization(bytes32 nonce,uint8 role,uint64 caseOpenedBlock,uint64 validUntil)"))
	serveBundleDomain     = protocol.Keccak256([]byte("fairbind/serve-bundle/v1"))
	dataCommitmentDomain  = protocol.Keccak256([]byte("fairbind/data-commitment/v1"))
	openWeightsCommitment = protocol.Keccak256([]byte("fairbind/open-weights-commitment/v1"))
)

// Serve requester roles in FairBindServeAuthorization.
const (
	RoleBuyer    uint8 = 1
	RoleVerifier uint8 = 2
)

func word(v uint64) []byte {
	out := make([]byte, 32)
	binary.BigEndian.PutUint64(out[24:], v)
	return out
}

func addrWord(a protocol.Address) []byte {
	out := make([]byte, 32)
	copy(out[12:], a[:])
	return out
}

func domainSeparator(name, version string, chainID uint64, contract protocol.Address) protocol.Bytes32 {
	n := protocol.Keccak256([]byte(name))
	v := protocol.Keccak256([]byte(version))
	return protocol.Keccak256(domainTypeHash[:], n[:], v[:], word(chainID), addrWord(contract))
}

// ReceiveDigest is the EIP-3009 ReceiveWithAuthorization digest under the
// token's own EIP-712 domain. The buyer signs this type rather than
// TransferWithAuthorization: the token accepts it only from the payee, the
// FairBind contract, so the authorization can be spent only through settle
// (ADR 0016).
func ReceiveDigest(tokenName, tokenVersion string, chainID uint64, token protocol.Address, a Authorization) protocol.Bytes32 {
	d := domainSeparator(tokenName, tokenVersion, chainID, token)
	s := protocol.Keccak256(receiveTypeHash[:], addrWord(protocol.Address(a.From)), addrWord(protocol.Address(a.To)),
		word(uint64(a.Value)), word(uint64(a.ValidAfter)), word(uint64(a.ValidBefore)), a.Nonce[:])
	return protocol.Keccak256([]byte{0x19, 0x01}, d[:], s[:])
}

// ServeAuthDigest is the FairBindServeAuthorization digest under the
// FairBind domain.
func ServeAuthDigest(chainID uint64, contract protocol.Address, nonce protocol.Bytes32, role uint8, caseOpenedBlock, validUntil uint64) protocol.Bytes32 {
	d := domainSeparator("FairBind", "1", chainID, contract)
	s := protocol.Keccak256(serveAuthTypeHash[:], nonce[:], word(uint64(role)), word(caseOpenedBlock), word(validUntil))
	return protocol.Keccak256([]byte{0x19, 0x01}, d[:], s[:])
}

// ServeAuthorization is carried base64(JSON) in X-FairBind-Serve-Authorization.
type ServeAuthorization struct {
	Role            uint8  `json:"role"`
	CaseOpenedBlock uint64 `json:"caseOpenedBlock"`
	ValidUntil      uint64 `json:"validUntil"`
	Signature       string `json:"signature"`
}

// Receipt is the wire receipt carried in X-FairBind-Receipt.
type Receipt struct {
	Version             uint8  `json:"version"`
	ChainID             U64    `json:"chainId"`
	ContractAddress     Addr   `json:"contractAddress"`
	SellerID            uint32 `json:"sellerId"`
	ProfileID           uint32 `json:"profileId"`
	Nonce               H32    `json:"nonce"`
	RequestHash         H32    `json:"requestHash"`
	ResponseHash        H32    `json:"responseHash"`
	ClaimsHash          H32    `json:"claimsHash"`
	PredicateCommitment H32    `json:"predicateCommitment"`
	Epoch               uint32 `json:"epoch"`
	IssuedAt            U64    `json:"issuedAt"`
	Signature           string `json:"signature"`
}

// Typed returns the EIP-712 message fields.
func (r Receipt) Typed() protocol.Receipt {
	return protocol.Receipt{
		Version: r.Version, SellerID: r.SellerID, ProfileID: r.ProfileID,
		Nonce: protocol.Bytes32(r.Nonce), RequestHash: protocol.Bytes32(r.RequestHash),
		ResponseHash: protocol.Bytes32(r.ResponseHash), ClaimsHash: protocol.Bytes32(r.ClaimsHash),
		PredicateCommitment: protocol.Bytes32(r.PredicateCommitment), Epoch: r.Epoch, IssuedAt: uint64(r.IssuedAt),
	}
}

// Digest returns the receipt digest, which is also the receipt leaf.
func (r Receipt) Digest() protocol.Bytes32 {
	return protocol.ReceiptDigest(uint64(r.ChainID), protocol.Address(r.ContractAddress), r.Typed())
}

// SignatureBytes decodes the 65-byte signature.
func (r Receipt) SignatureBytes() ([]byte, error) {
	b, err := ParseHex(r.Signature)
	if err != nil || len(b) != 65 {
		return nil, errors.New("receipt signature must be 65 bytes")
	}
	return b, nil
}

// Preimage is the service-class predicate-commitment preimage.
type Preimage struct {
	Kind                string `json:"kind"`
	ReferenceTime       *U64   `json:"referenceTime,omitempty"`
	SourceSetHash       *H32   `json:"sourceSetHash,omitempty"`
	TolerancePolicyHash *H32   `json:"tolerancePolicyHash,omitempty"`
	ToplocCommitment    *H32   `json:"toplocCommitment,omitempty"`
	ModelHash           *H32   `json:"modelHash,omitempty"`
	ConfigHash          *H32   `json:"configHash,omitempty"`
}

// Commitment computes predicateCommitment from predicate-interface-v1.
func (p Preimage) Commitment() (protocol.Bytes32, error) {
	switch p.Kind {
	case "data-api":
		if p.ReferenceTime == nil || p.SourceSetHash == nil || p.TolerancePolicyHash == nil {
			return protocol.Bytes32{}, errors.New("incomplete data-api preimage")
		}
		return protocol.Keccak256(dataCommitmentDomain[:], word(uint64(*p.ReferenceTime)), p.SourceSetHash[:], p.TolerancePolicyHash[:]), nil
	case "open-weights-inference":
		if p.ToplocCommitment == nil || p.ModelHash == nil || p.ConfigHash == nil {
			return protocol.Bytes32{}, errors.New("incomplete open-weights preimage")
		}
		return protocol.Keccak256(openWeightsCommitment[:], p.ToplocCommitment[:], p.ModelHash[:], p.ConfigHash[:]), nil
	}
	return protocol.Bytes32{}, fmt.Errorf("unknown preimage kind %q", p.Kind)
}
