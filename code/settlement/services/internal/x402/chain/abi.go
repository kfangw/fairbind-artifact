package chain

import (
	"encoding/binary"
	"errors"

	"example.org/fairbind/protocol"
	"example.org/fairbind/services/internal/x402"
)

// A minimal Solidity ABI encoder for the argument shapes of the calls the
// services make: static words, bytes, static and dynamic tuples, bytes32[].

type abiArg struct {
	static []byte // inline words for a static argument
	tail   []byte // encoded body for a dynamic argument
	dyn    bool
}

func u(v uint64) []byte {
	w := make([]byte, 32)
	binary.BigEndian.PutUint64(w[24:], v)
	return w
}

func aWord(a Address) []byte {
	w := make([]byte, 32)
	copy(w[12:], a[:])
	return w
}

func b16Word(b protocol.Bytes16) []byte {
	w := make([]byte, 32)
	copy(w, b[:])
	return w
}

func st(words ...[]byte) abiArg {
	var b []byte
	for _, w := range words {
		b = append(b, w...)
	}
	return abiArg{static: b}
}

func dynBytes(b []byte) abiArg {
	out := u(uint64(len(b)))
	out = append(out, b...)
	out = append(out, make([]byte, (32-len(b)%32)%32)...)
	return abiArg{tail: out, dyn: true}
}

func dynTuple(args ...abiArg) abiArg { return abiArg{tail: encodeArgs(args...), dyn: true} }

func dynHashes(items []protocol.Bytes32) abiArg {
	out := u(uint64(len(items)))
	for _, h := range items {
		out = append(out, h[:]...)
	}
	return abiArg{tail: out, dyn: true}
}

// dynEntries encodes a dynamic array of static (nonce, receiptLeaf) tuples:
// its length, then two words per entry.
func dynEntries(items []x402.Entry) abiArg {
	out := u(uint64(len(items)))
	for _, e := range items {
		out = append(out, e.Nonce[:]...)
		out = append(out, e.ReceiptLeaf[:]...)
	}
	return abiArg{tail: out, dyn: true}
}

func encodeArgs(args ...abiArg) []byte {
	headLen := 0
	for _, a := range args {
		if a.dyn {
			headLen += 32
		} else {
			headLen += len(a.static)
		}
	}
	var head, tail []byte
	for _, a := range args {
		if a.dyn {
			head = append(head, u(uint64(headLen+len(tail)))...)
			tail = append(tail, a.tail...)
		} else {
			head = append(head, a.static...)
		}
	}
	return append(head, tail...)
}

func selector(signature string) []byte {
	h := protocol.Keccak256([]byte(signature))
	return h[:4]
}

func call(signature string, args ...abiArg) []byte {
	return append(selector(signature), encodeArgs(args...)...)
}

const receiptTuple = "(uint8,uint32,uint32,bytes32,bytes32,bytes32,bytes32,bytes32,uint24,uint64)"
const requestTuple = "(bytes,bytes,bytes,bytes,bytes)"

func receiptArg(r protocol.Receipt) abiArg {
	return st(u(uint64(r.Version)), u(uint64(r.SellerID)), u(uint64(r.ProfileID)), r.Nonce[:], r.RequestHash[:],
		r.ResponseHash[:], r.ClaimsHash[:], r.PredicateCommitment[:], u(uint64(r.Epoch)), u(r.IssuedAt))
}

func requestArg(c x402.CanonicalRequest) abiArg {
	return dynTuple(dynBytes(c.Method), dynBytes(c.Path), dynBytes(c.Query), dynBytes(c.HeaderBlock), dynBytes(c.Body))
}

func proofArg(p protocol.ReceiptProof) abiArg {
	return dynTuple(st(u(uint64(p.Index))), st(u(uint64(p.Count))), dynHashes(p.Siblings))
}

// Signatures of the calls, checked against the deployment ABI in tests.
var (
	sigSettle           = "settle(uint32,uint32,bytes32,bytes16,bytes32,(address,address,uint256,uint256,uint256,bytes32),bytes)"
	sigAnchor           = "anchor(uint32,uint24,(bytes32,bytes32)[],uint32,bytes32)"
	sigDispute          = "dispute(bytes32,uint8," + receiptTuple + ",bytes)"
	sigServed           = "served(bytes32,bytes32)"
	sigAcceptServe      = "acceptServe(bytes32)"
	sigEscalate         = "escalate(bytes32)"
	sigFinalizeServed   = "finalizeServed(bytes32)"
	sigTimeoutServe     = "timeoutServe(bytes32)"
	sigPublish          = "publish(bytes32,bytes16," + requestTuple + ",bytes," + receiptTuple + ",bytes)"
	sigBeginPublication = "beginPublication(bytes32,bytes16," + requestTuple + "," + receiptTuple + ",bytes,uint32,uint16)"
	sigPublishChunk     = "publishChunk(bytes32,uint16,bytes)"
	sigFinalizePub      = "finalizePublication(bytes32)"
	sigClaimRefund      = "claimRefund(bytes32)"
	sigClaimRefundRcpt  = "claimRefund(bytes32," + receiptTuple + ",bytes,(uint32,uint32,bytes32[]))"
	sigClaimEpochFail   = "claimEpochFailure(bytes32)"

	sigGetServiceProfile = "getServiceProfile(uint32)"
	sigGetDeadlineConfig = "getDeadlineConfig(uint32)"
	sigGetSeller         = "getSeller(uint32)"
	sigQuoteSeller       = "quoteSeller(uint32)"
	sigGetPurchase       = "getPurchase(bytes32)"
	sigPurchaseByKey     = "purchaseByKey(bytes32)"
	sigPurchaseState     = "purchaseState(bytes32)"
	sigGetCase           = "getCase(bytes32)"
	sigGetAnchor         = "getAnchor(uint32,uint24)"
	sigGetBond           = "getBond(uint32)"
	sigGetVerifier       = "getVerifier(uint32)"

	eventSettled = "Settled(bytes32,bytes32,uint32,uint32,uint32,address,uint256,uint24,bytes32,bytes32)"
)

var errorNames = []string{"Unauthorized", "ZeroAddress", "InvalidConfiguration", "Paused", "UnknownDeadlineConfig",
	"UnknownProfile", "ObjectAlreadyExists", "InactiveProfile", "InvalidProfile", "UnsupportedServiceClass",
	"ServiceClassUnavailable", "SellerInactive", "VerifierInactive", "InsufficientSellerBond", "InsufficientVerifierBond",
	"LiabilityExceeded", "ExitNotReady", "KeyAlreadyUsed", "NonceAlreadyUsed", "ProfileMismatch", "ClaimsMismatch",
	"NonceMismatch", "AuthorizationMismatch", "AuthorizationExpired", "ValueTooLarge", "RateLimitExceeded",
	"AnchorTooEarly", "AnchorWindowClosed", "CountMismatch", "EntriesNotAscending", "InvalidRandomnessWindow", "NotSampled",
	"ClaimWindowClosed", "ResponseTooLarge", "EvidenceTooLarge", "InvalidReceipt", "InvalidSignature", "InvalidProof",
	"InvalidPublication", "IneligibleVerifier", "AssignmentExhausted", "DeadlineNotReached", "DeadlinePassed",
	"InvalidTransition", "AlreadyFinalized", "TransferFailed", "BondNotActive", "BondMismatch", "SellerIsSuspended",
	"FrozenEntry", "ClaimWindowNotOpen", "AlreadyClaimed", "ReceiptOutOfWindow", "PoolExhausted", "ReinstateConditionsUnmet"}

var errorBySelector = func() map[[4]byte]string {
	m := map[[4]byte]string{}
	for _, n := range errorNames {
		var k [4]byte
		copy(k[:], selector(n+"()"))
		m[k] = n
	}
	return m
}()

// ErrorName maps revert data to a custom error name, or "" if unknown.
func ErrorName(data []byte) string {
	if len(data) < 4 {
		return ""
	}
	var k [4]byte
	copy(k[:], data[:4])
	return errorBySelector[k]
}

// words splits return data into 32-byte words, requiring at least n.
func words(data []byte, n int) ([][]byte, error) {
	if len(data) < 32*n {
		return nil, errors.New("short return data")
	}
	out := make([][]byte, n)
	for i := range out {
		out[i] = data[32*i : 32*i+32]
	}
	return out, nil
}

func wU64(w []byte) (uint64, error) {
	for _, b := range w[:24] {
		if b != 0 {
			return 0, errors.New("value exceeds uint64")
		}
	}
	return binary.BigEndian.Uint64(w[24:]), nil
}

func w32(w []byte) (h Hash)      { copy(h[:], w); return }
func wAddr(w []byte) (a Address) { copy(a[:], w[12:]); return }
