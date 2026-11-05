// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { BatchShared } from "./BatchShared.sol";
import { ExchangeStore } from "./ExchangeStore.sol";

/// Code shared by the receipt-signature and proof modules (ADR 0037).
abstract contract ExchangeShared is BatchShared {
    /// EIP-712 types: the buyer's receipt signature, the seller's posting
    /// signature of one bundle, and that of the list of one transaction.
    bytes32 internal constant RECEIPT_SIGNATURE_TYPEHASH = keccak256(
        "FairBindReceiptSignature(address seller,bytes32 nonce,bytes32 ctHash,bytes32 ekHash,bytes32 responseHash,bytes32 leaf)"
    );
    bytes32 internal constant POST_TYPEHASH = keccak256(
        "FairBindReceiptPost(bytes32 nonce,bytes32 ctHash,bytes32 ekHash,bytes32 responseHash,bytes32 leaf)"
    );
    bytes32 internal constant POST_LIST_TYPEHASH = keccak256("FairBindReceiptPostList(bytes32 listHash,uint256 count)");
    bytes32 internal constant SALTED_DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract,bytes32 salt)"
    );
    bytes4 internal constant ERC1271_MAGIC = 0x1626ba7e;
    /// Gas the call keeps beyond g_1271 * 64 / 63 before it calls a smart account.
    uint256 internal constant G1271_MARGIN = 5_000;

    error ProofNotAllowed();
    error ProofNotPass();
    error GasBelow1271Bound();

    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        BatchShared(token, gov, guard, treasury, rewardPool)
    { }

    function _terms(uint32 profileId) internal view returns (ExchangeStore.Terms storage) {
        return ExchangeStore.layout().terms[profileId];
    }

    /// Domain of the receipt and posting signatures: chain, contract and the
    /// profile's parameter hash.
    function _exchangeDomain(uint32 profileId) internal view returns (bytes32) {
        return keccak256(
            abi.encode(
                SALTED_DOMAIN_TYPEHASH, keccak256("FairBind"), keccak256("1"), block.chainid, address(this),
                profiles[profileId].parameters.parameterHash
            )
        );
    }

    function _typed(uint32 profileId, bytes32 structHash) internal view returns (bytes32) {
        return keccak256(abi.encodePacked(hex"1901", _exchangeDomain(profileId), structHash));
    }

    /// The buyer's receipt signature digest. `seller` is the registered
    /// signing key of the purchase's seller, read by the contract.
    function _receiptSignatureDigest(
        uint32 profileId,
        address seller,
        bytes32 nonce,
        bytes32 ctHash,
        bytes32 ekHash,
        bytes32 rHash,
        bytes32 leaf
    ) internal view returns (bytes32) {
        return _typed(profileId, keccak256(abi.encode(RECEIPT_SIGNATURE_TYPEHASH, seller, nonce, ctHash, ekHash, rHash, leaf)));
    }

    /// h_n of a bundle with its lowest bit cleared.
    function _bundleHash(bytes32 ctHash, bytes32 ekHash, bytes32 rHash, bytes32 leaf) internal pure returns (bytes32) {
        return bytes32(uint256(keccak256(abi.encode(ctHash, ekHash, rHash, leaf))) & ~uint256(1));
    }

    /// Whether `sig` is `signer`'s signature of `digest`: ecrecover first,
    /// then, for a signer with code, ERC-1271 with a gas cap of `cap`.
    /// `limit` bounds the length of a 1271 signature (zero: none). A call
    /// with too little gas left for the cap reverts as a whole. `used` is
    /// the gas of the 1271 call.
    function _signedBy(address signer, bytes32 digest, bytes calldata sig, uint256 cap, uint256 limit)
        internal
        view
        returns (bool ok, uint256 used)
    {
        if (sig.length == 65) {
            bytes32 r;
            bytes32 s;
            uint8 v;
            assembly ("memory-safe") {
                r := calldataload(sig.offset)
                s := calldataload(add(sig.offset, 32))
                v := byte(0, calldataload(add(sig.offset, 64)))
            }
            if (uint256(s) <= SECP256K1_HALF_N && (v == 27 || v == 28)) {
                address got = ecrecover(digest, v, r, s);
                if (got != address(0) && got == signer) return (true, 0);
            }
        }
        if (signer.code.length == 0 || (limit != 0 && sig.length > limit)) return (false, 0);
        if (gasleft() < cap * 64 / 63 + G1271_MARGIN) revert GasBelow1271Bound();
        bytes memory data = abi.encodeWithSelector(ERC1271_MAGIC, digest, sig);
        uint256 before = gasleft();
        bool success;
        bytes4 answer;
        assembly ("memory-safe") {
            success := staticcall(cap, signer, add(data, 0x20), mload(data), 0, 0)
            if and(success, eq(returndatasize(), 32)) {
                returndatacopy(0, 0, 32)
                answer := mload(0)
            }
        }
        used = before - gasleft();
        ok = success && answer == ERC1271_MAGIC;
    }

    /// Dec_ek(ct): the keccak key stream bound to the nonce, block i of 32
    /// bytes being keccak256(ek, nonce, i). A mutation build of the tests
    /// overrides it.
    function _decrypt(bytes32 ek, bytes32 nonce, bytes calldata ct) internal pure virtual returns (bytes memory pt) {
        uint256 n = ct.length;
        pt = new bytes(n);
        assembly ("memory-safe") {
            let scratch := mload(0x40)
            mstore(scratch, ek)
            mstore(add(scratch, 0x20), nonce)
            let dst := add(pt, 0x20)
            for { let off := 0 } lt(off, n) { off := add(off, 0x20) } {
                mstore(add(scratch, 0x40), shr(5, off))
                mstore(add(dst, off), xor(calldataload(add(ct.offset, off)), keccak256(scratch, 0x60)))
            }
        }
    }

    /// keccak256(tag || pt): the response commitment h_r of a plaintext
    /// psi || pad(r).
    function _responseCommit(bytes32 tag, bytes memory pt) internal pure returns (bytes32 h) {
        assembly ("memory-safe") {
            let n := mload(pt)
            mstore(pt, tag)
            h := keccak256(pt, add(n, 0x20))
            mstore(pt, n)
        }
    }

    /// The length of r in a plaintext psi || pad(r): pad appends 0x80 and
    /// zero bytes up to the padded length, so r ends before the last
    /// non-zero byte, which must be 0x80. Anything else is a failed
    /// decryption and reverts. A mutation build of the tests overrides it.
    function _unpad(bytes memory pt) internal pure virtual returns (uint256 len) {
        uint256 i = pt.length;
        assembly ("memory-safe") {
            let base := add(pt, 0x20)
            // Whole zero words from the end, then single bytes.
            for { } and(gt(i, 63), iszero(mload(add(base, sub(i, 32))))) { } { i := sub(i, 32) }
            for { } and(gt(i, 32), iszero(byte(0, mload(add(base, sub(i, 1)))))) { } { i := sub(i, 1) }
        }
        if (i <= 32 || pt[i - 1] != 0x80) revert InvalidProof();
        len = i - 33;
    }

    /// The receipt leaf of a PASS proof: the purchase's receipt with h_r as
    /// its response hash, the profile's predicate commitment at the
    /// purchase's reference time, and issuedAt.
    function _proofLeaf(bytes32 nonce, bytes32 rHash, bytes32 commitment, uint64 issuedAt)
        internal
        view
        returns (bytes32)
    {
        PurchaseView storage p = purchases[nonce];
        bytes32 structHash = keccak256(
            abi.encode(
                RECEIPT_TYPEHASH, uint8(1), p.sellerId, p.profileId, nonce, p.requestHash, rHash,
                sellers[p.sellerId].viewData.claimsHash, commitment, p.epoch, issuedAt
            )
        );
        bytes32 domainSeparator = keccak256(
            abi.encode(EIP712_DOMAIN_TYPEHASH, keccak256("FairBind"), keccak256("1"), block.chainid, address(this))
        );
        return keccak256(abi.encodePacked(hex"1901", domainSeparator, structHash));
    }

    /// The predicate commitment of a proof profile at reference time t: the
    /// manifest (t, sourceSetHash, policyHash).
    function _commitment(ExchangeStore.Terms storage t, uint64 refTime) internal view returns (bytes32) {
        return keccak256(abi.encode(refTime, t.sourceSetHash, t.policyHash));
    }
}
