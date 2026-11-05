// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { G10Base, G10Merkle } from "./G10Base.sol";
import { FairBindMerkle } from "../../src/FairBindMerkle.sol";

/// Sketch of the rule 10 v0.3 non-delivery dispute (R5 (d)) with calldata
/// delivery. The buyer opens the dispute with the anchored leaf's hashes and
/// their Merkle membership (32-entry epoch, depth 5); the seller posts the
/// ciphertext ct (H(ct) against the leaf's h_ct) and reveals the key k (H(k)
/// against h_k); the buyer may then ask for the decryption check: the
/// contract recomputes ct XOR keystream, with keystream word j =
/// keccak256(k, nonce, j), and compares keccak256(tag || plaintext) with the
/// leaf's response hash h_r (a FairSwap-style proof of misbehaviour). The
/// plaintext is psi || pad(r), so its length is the ciphertext length.
contract NonDeliveryDispute {
    struct Dispute {
        bytes32 ctHash;
        bytes32 keyHash;
        bytes32 responseHash;
        bytes32 key;
        uint64 deadline;
        uint8 state; // 1 open, 2 ct posted, 3 delivered, 4 refunded
    }

    bytes32 internal constant TAG = keccak256("fairbind/response/v1");
    mapping(uint64 => bytes32) public epochRoot;
    mapping(bytes32 => Dispute) public disputes;

    function setRoot(uint64 epoch, bytes32 root) external {
        epochRoot[epoch] = root;
    }

    function leafOf(bytes32 responseHash, bytes32 ctHash, bytes32 keyHash) public pure returns (bytes32) {
        return keccak256(abi.encode(responseHash, ctHash, keyHash));
    }

    function open(
        uint64 epoch,
        bytes32 nonce,
        bytes32 responseHash,
        bytes32 ctHash,
        bytes32 keyHash,
        uint256 index,
        bytes32[] calldata path
    ) external {
        require(disputes[nonce].state == 0, "exists");
        bytes32 entry = FairBindMerkle.entryHash(nonce, leafOf(responseHash, ctHash, keyHash));
        require(G10Merkle.rootOf(entry, index, path) == epochRoot[epoch], "membership");
        disputes[nonce] = Dispute(ctHash, keyHash, responseHash, bytes32(0), uint64(block.number + 300), 1);
    }

    /// The ciphertext alone, as calldata: H(ct) check.
    function postCiphertext(bytes32 nonce, bytes calldata ct) external {
        Dispute storage d = disputes[nonce];
        require(d.state == 1 && block.number <= d.deadline, "state");
        require(keccak256(ct) == d.ctHash, "ct hash");
        d.state = 2;
    }

    /// The key alone: H(k) check, the key is stored for the decryption check.
    function revealKey(bytes32 nonce, bytes32 k) external {
        Dispute storage d = disputes[nonce];
        require(d.state == 2 && block.number <= d.deadline, "state");
        require(keccak256(abi.encode(k)) == d.keyHash, "key hash");
        d.key = k;
        d.state = 3;
    }

    /// Ciphertext and key in one transaction.
    function deliver(bytes32 nonce, bytes calldata ct, bytes32 k) external {
        Dispute storage d = disputes[nonce];
        require(d.state == 1 && block.number <= d.deadline, "state");
        require(keccak256(ct) == d.ctHash, "ct hash");
        require(keccak256(abi.encode(k)) == d.keyHash, "key hash");
        d.key = k;
        d.state = 3;
    }

    /// The decryption check: the ciphertext again as calldata. Returns true
    /// when the decryption does not match h_r (misbehaviour proven, refund).
    function decryptCheck(bytes32 nonce, bytes calldata ct) external returns (bool misbehaviour) {
        Dispute storage d = disputes[nonce];
        require(d.state == 3, "state");
        require(keccak256(ct) == d.ctHash, "ct hash");
        bytes32 h = decryptHash(d.key, nonce, ct);
        misbehaviour = h != d.responseHash;
        if (misbehaviour) d.state = 4;
    }

    /// keccak256(TAG || (ct XOR keystream)); ct length is a multiple of 32.
    function decryptHash(bytes32 k, bytes32 nonce, bytes calldata ct) public pure returns (bytes32 h) {
        require(ct.length % 32 == 0, "length");
        bytes32 tag = TAG;
        assembly ("memory-safe") {
            let out := mload(0x40)
            mstore(out, tag)
            let words := shr(5, ct.length)
            let scratch := add(add(out, 0x20), ct.length)
            mstore(scratch, k)
            mstore(add(scratch, 0x20), nonce)
            for { let j := 0 } lt(j, words) { j := add(j, 1) } {
                mstore(add(scratch, 0x40), j)
                let ks := keccak256(scratch, 0x60)
                mstore(add(add(out, 0x20), shl(5, j)), xor(calldataload(add(ct.offset, shl(5, j))), ks))
            }
            h := keccak256(out, add(0x20, ct.length))
        }
    }

    /// Encryption with the same keystream (test helper).
    function encrypt(bytes32 k, bytes32 nonce, bytes calldata pt) external pure returns (bytes memory ct) {
        ct = new bytes(pt.length);
        for (uint256 j; j < pt.length / 32; j++) {
            bytes32 ks = keccak256(abi.encode(k, nonce, j));
            bytes32 w = bytes32(pt[32 * j:32 * j + 32]) ^ ks;
            assembly ("memory-safe") {
                mstore(add(add(ct, 0x20), shl(5, j)), w)
            }
        }
    }
}

/// Run with --isolate. Every number is logged; nothing is asserted about gas.
/// Calldata is also priced under the EIP-7623 floor (Prague; Base since
/// Isthmus): a transaction pays at least 21,000 + 10 x tokens, tokens = zero
/// bytes + 4 x nonzero bytes. The L1 data fee of Base is not in these numbers.
contract NonDeliveryGasTest is G10Base {
    NonDeliveryDispute internal nd;
    bytes32 internal constant TAG = keccak256("fairbind/response/v1");
    uint64 internal constant EPOCH = 2;

    function setUp() public {
        nd = new NonDeliveryDispute();
        hv.roll(100);
    }

    function _floor(bytes memory data) internal pure returns (uint256 t) {
        for (uint256 i; i < data.length; i++) t += data[i] == 0 ? 1 : 4;
        t = 21_000 + 10 * t;
    }

    struct Case {
        bytes32 nonce;
        bytes32 k;
        bytes ct;
        bytes32 respHash;
        bytes32 ctHash;
        bytes32 keyHash;
        bytes32[] path;
    }

    function _case(uint256 size, bool honest) internal returns (Case memory c) {
        c.nonce = keccak256(abi.encode("nonce", size, honest));
        c.k = keccak256(abi.encode("key", size));
        bytes memory pt = new bytes(size);
        for (uint256 i; i < size; i++) pt[i] = bytes1(uint8(0x20 + (i * 31) % 90));
        c.ct = nd.encrypt(c.k, c.nonce, pt);
        c.respHash = honest ? keccak256(abi.encodePacked(TAG, pt)) : keccak256("another response");
        c.ctHash = keccak256(c.ct);
        c.keyHash = keccak256(abi.encode(c.k));
        bytes32 entry = FairBindMerkle.entryHash(c.nonce, nd.leafOf(c.respHash, c.ctHash, c.keyHash));
        c.path = new bytes32[](5);
        bytes32 h = entry;
        for (uint256 d; d < 5; d++) {
            c.path[d] = keccak256(abi.encode("sib", d, size, honest));
            h = G10Merkle.node(h, c.path[d]);
        }
        nd.setRoot(EPOCH, h);
    }

    function _open(Case memory c) internal returns (uint256 g) {
        g = gasleft();
        nd.open(EPOCH, c.nonce, c.respHash, c.ctHash, c.keyHash, 0, c.path);
        g -= gasleft();
        _rec(address(nd), abi.encodeCall(nd.open, (EPOCH, c.nonce, c.respHash, c.ctHash, c.keyHash, 0, c.path)));
    }

    function _line(string memory tag, uint256 g, bytes memory data) internal {
        _log(string.concat(tag, ", tx gas"), g);
        _log(string.concat(tag, ", calldata gas"), _cdGas(data));
        _log(string.concat(tag, ", EIP-7623 floor"), _floor(data));
    }

    function test_gas_nonDelivery() public {
        uint256[3] memory sizes = [uint256(1024), 2048, 4096];
        for (uint256 s; s < 3; s++) {
            uint256 size = sizes[s];
            string memory z = string.concat(" ", _u(size / 1024), " KB");
            uint256 id = hv.snapshotState();
            // Separate ciphertext and key transactions; misbehaving seller.
            Case memory c = _case(size, false);
            uint256 g = _open(c);
            _line(string.concat("G10-6 open dispute", z), g, abi.encodeCall(nd.open, (EPOCH, c.nonce, c.respHash, c.ctHash, c.keyHash, 0, c.path)));
            g = gasleft();
            nd.postCiphertext(c.nonce, c.ct);
            g -= gasleft();
            _rec(address(nd), abi.encodeCall(nd.postCiphertext, (c.nonce, c.ct)));
            _line(string.concat("G10-6 post ciphertext", z), g, abi.encodeCall(nd.postCiphertext, (c.nonce, c.ct)));
            g = gasleft();
            nd.revealKey(c.nonce, c.k);
            g -= gasleft();
            _rec(address(nd), abi.encodeCall(nd.revealKey, (c.nonce, c.k)));
            _line(string.concat("G10-6 reveal key", z), g, abi.encodeCall(nd.revealKey, (c.nonce, c.k)));
            g = gasleft();
            bool bad = nd.decryptCheck(c.nonce, c.ct);
            g -= gasleft();
            _rec(address(nd), abi.encodeCall(nd.decryptCheck, (c.nonce, c.ct)));
            require(bad, "misbehaviour is proven");
            _line(string.concat("G10-6 decryption check, misbehaviour proven", z), g, abi.encodeCall(nd.decryptCheck, (c.nonce, c.ct)));
            // Honest seller: ciphertext and key together, decryption matches.
            Case memory h = _case(size, true);
            _open(h);
            g = gasleft();
            nd.deliver(h.nonce, h.ct, h.k);
            g -= gasleft();
            _rec(address(nd), abi.encodeCall(nd.deliver, (h.nonce, h.ct, h.k)));
            _line(string.concat("G10-6 deliver ciphertext and key in one tx", z), g, abi.encodeCall(nd.deliver, (h.nonce, h.ct, h.k)));
            g = gasleft();
            bad = nd.decryptCheck(h.nonce, h.ct);
            g -= gasleft();
            _rec(address(nd), abi.encodeCall(nd.decryptCheck, (h.nonce, h.ct)));
            require(!bad, "honest delivery decrypts to h_r");
            _line(string.concat("G10-6 decryption check, honest", z), g, abi.encodeCall(nd.decryptCheck, (h.nonce, h.ct)));
            hv.revertToState(id);
        }
    }
}
