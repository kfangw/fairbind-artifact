// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { G10Base, G10Sig, G10Merkle } from "./G10Base.sol";
import { FairBindMerkle } from "../../src/FairBindMerkle.sol";

/// Sketch of the rule 10 v0.3 buyer signature check (R2 (c), R3 (b)) and the
/// swap proof (R5 (b) (1)). The buyer signature is EIP-712 over (nonce,
/// amount, request hash, response hash, ciphertext hash, profile id, code
/// hash, accepted flag) under the domain (name, version, chain id, FairBind
/// address); the signer must be the payer recorded at settlement (one cold
/// slot per nonce). The swap proof is a seller-signed receipt R_S for a nonce
/// whose anchored leaf differs, with the leaf's Merkle membership in the
/// stored epoch root.
contract BuyerSigVerifier {
    struct BuyerAck {
        bytes32 nonce;
        uint256 amount;
        bytes32 requestHash;
        bytes32 responseHash;
        bytes32 ctHash;
        bytes32 profileId;
        bytes32 codeHash;
        bool accepted;
    }

    struct SellerReceipt {
        bytes32 nonce;
        uint256 amount;
        bytes32 requestHash;
        bytes32 responseHash;
        bytes32 ctHash;
        bytes32 keyHash;
        bytes32 profileId;
        bytes32 codeHash;
        bytes32 claimsHash;
        bytes32 materialCommit;
    }

    bytes32 internal constant ACK_TYPEHASH = keccak256(
        "BuyerAck(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 profileId,bytes32 codeHash,bool accepted)"
    );
    bytes32 internal constant RECEIPT_TYPEHASH = keccak256(
        "SellerReceipt(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 keyHash,bytes32 profileId,bytes32 codeHash,bytes32 claimsHash,bytes32 materialCommit)"
    );
    bytes32 public immutable DOMAIN_SEPARATOR;

    mapping(bytes32 => address) public payerOf;
    mapping(uint64 => bytes32) public epochRoot;
    address public sellerKey;
    mapping(uint64 => bool) public failed;

    constructor(address seller) {
        sellerKey = seller;
        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256("FairBind"),
                keccak256("10"),
                block.chainid,
                address(this)
            )
        );
    }

    function setPayers(bytes32[] calldata nonces, address payer) external {
        for (uint256 i; i < nonces.length; i++) payerOf[nonces[i]] = payer;
    }

    function setRoot(uint64 epoch, bytes32 root) external {
        epochRoot[epoch] = root;
    }

    function ackDigest(BuyerAck calldata a) public view returns (bytes32) {
        return G10Sig.typed(DOMAIN_SEPARATOR, keccak256(abi.encode(ACK_TYPEHASH, a)));
    }

    function receiptDigest(SellerReceipt calldata r) public view returns (bytes32) {
        return G10Sig.typed(DOMAIN_SEPARATOR, keccak256(abi.encode(RECEIPT_TYPEHASH, r)));
    }

    /// One buyer signature: beta = 1 when it recovers to the payer of the
    /// nonce. A bad signature gives beta = 0 and does not revert.
    function checkAck(BuyerAck calldata a, bytes calldata sig) external returns (bool beta) {
        address s = G10Sig.recover(ackDigest(a), sig);
        beta = s != address(0) && s == payerOf[a.nonce];
    }

    /// A batch, as an anchor carries the signatures: count of beta = 1 and
    /// the accepted bitmap.
    function checkAcks(BuyerAck[] calldata acks, bytes[] calldata sigs) external returns (uint256 betas, uint256 acceptedBits) {
        for (uint256 i; i < acks.length; i++) {
            address s = G10Sig.recover(ackDigest(acks[i]), sigs[i]);
            if (s != address(0) && s == payerOf[acks[i].nonce]) {
                betas++;
                if (acks[i].accepted) acceptedBits |= 1 << i;
            }
        }
    }

    /// Swap proof: R_S signed by the seller key, the anchored entry (nonce,
    /// receiptLeaf) is in the epoch root, and receiptLeaf is not the hash of
    /// R_S. On success it records a confirmed failure (one fresh slot).
    function proveSwap(
        uint64 epoch,
        SellerReceipt calldata r,
        bytes calldata sellerSig,
        bytes32 anchoredLeaf,
        uint256 index,
        bytes32[] calldata path
    ) external returns (bool) {
        bytes32 rd = receiptDigest(r);
        if (G10Sig.recover(rd, sellerSig) != sellerKey) return false;
        bytes32 entry = FairBindMerkle.entryHash(r.nonce, anchoredLeaf);
        if (G10Merkle.rootOf(entry, index, path) != epochRoot[epoch]) return false;
        if (anchoredLeaf == keccak256(abi.encode(RECEIPT_TYPEHASH, r))) return false;
        failed[epoch] = true;
        return true;
    }
}

/// Run with --isolate. Every number is logged; nothing is asserted about gas.
contract BuyerSigGasTest is G10Base {
    BuyerSigVerifier internal v;
    uint256 internal constant BUYER_KEY = 0xB0B;
    uint256 internal constant SELLER_KEY = 0x5E11;
    bytes32 internal constant PROFILE = keccak256("profile");
    bytes32 internal constant CODEHASH = keccak256("verifier code");
    bytes32 internal constant ACK_TYPEHASH = keccak256(
        "BuyerAck(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 profileId,bytes32 codeHash,bool accepted)"
    );
    bytes32 internal constant RECEIPT_TYPEHASH = keccak256(
        "SellerReceipt(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 keyHash,bytes32 profileId,bytes32 codeHash,bytes32 claimsHash,bytes32 materialCommit)"
    );

    function setUp() public {
        v = new BuyerSigVerifier(hv.addr(SELLER_KEY));
        bytes32[] memory ns = new bytes32[](32);
        for (uint256 i; i < 32; i++) ns[i] = _nonce(i);
        v.setPayers(ns, hv.addr(BUYER_KEY));
        hv.roll(1000);
    }

    function _nonce(uint256 i) internal pure returns (bytes32) {
        return keccak256(abi.encode("nonce", i));
    }

    function _ack(uint256 i, bool accepted) internal pure returns (BuyerSigVerifier.BuyerAck memory a) {
        a.nonce = _nonce(i);
        a.amount = 10_000 + i;
        a.requestHash = keccak256(abi.encode("req", i));
        a.responseHash = keccak256(abi.encode("resp", i));
        a.ctHash = keccak256(abi.encode("ct", i));
        a.profileId = PROFILE;
        a.codeHash = CODEHASH;
        a.accepted = accepted;
    }

    function _signAck(BuyerSigVerifier.BuyerAck memory a) internal returns (bytes memory) {
        return _sig(BUYER_KEY, G10Sig.typed(v.DOMAIN_SEPARATOR(), keccak256(abi.encode(ACK_TYPEHASH, a))));
    }

    function test_gas_buyerSigSingle() public {
        BuyerSigVerifier.BuyerAck memory a = _ack(0, false);
        bytes memory s = _signAck(a);
        uint256 g = gasleft();
        bool beta = v.checkAck(a, s);
        g -= gasleft();
        _rec(address(v), abi.encodeCall(v.checkAck, (a, s)));
        require(beta, "buyer signature verifies");
        _log("G10-2 buyer signature single, tx gas", g);
        _log("G10-2 buyer signature single, calldata gas", _cdGas(abi.encodeCall(v.checkAck, (a, s))));
        a.amount += 1;
        require(!v.checkAck(a, s), "altered ack gives beta 0");
    }

    function test_gas_buyerSigBatch() public {
        uint256[4] memory sizes = [uint256(1), 2, 8, 32];
        for (uint256 k; k < sizes.length; k++) {
            uint256 n = sizes[k];
            BuyerSigVerifier.BuyerAck[] memory acks = new BuyerSigVerifier.BuyerAck[](n);
            bytes[] memory sigs = new bytes[](n);
            for (uint256 i; i < n; i++) {
                acks[i] = _ack(i, i % 4 == 0);
                sigs[i] = _signAck(acks[i]);
            }
            uint256 g = gasleft();
            (uint256 betas,) = v.checkAcks(acks, sigs);
            g -= gasleft();
            _rec(address(v), abi.encodeCall(v.checkAcks, (acks, sigs)));
            require(betas == n, "every buyer signature verifies");
            _log(string.concat("G10-2 buyer signature batch n=", _u(n), " tx gas"), g);
            _log(string.concat("G10-2 buyer signature batch n=", _u(n), " calldata gas"), _cdGas(abi.encodeCall(v.checkAcks, (acks, sigs))));
        }
    }

    function _receipt(uint256 i) internal pure returns (BuyerSigVerifier.SellerReceipt memory r) {
        r.nonce = _nonce(i);
        r.amount = 10_000 + i;
        r.requestHash = keccak256(abi.encode("req", i));
        r.responseHash = keccak256(abi.encode("resp", i));
        r.ctHash = keccak256(abi.encode("ct", i));
        r.keyHash = keccak256(abi.encode("k", i));
        r.profileId = PROFILE;
        r.codeHash = CODEHASH;
        r.claimsHash = keccak256("claims");
        r.materialCommit = keccak256(abi.encode("material", i));
    }

    /// Swap proof against epochs of 8, 32, 1,024 and 65,536 entries (depths
    /// 3, 5, 10, 16). For the two large trees only the path of entry 0 is
    /// built, with random siblings; the root is the one the path gives.
    function test_gas_swapProof() public {
        uint256[4] memory widths = [uint256(8), 32, 1024, 65536];
        uint256[4] memory depths = [uint256(3), 5, 10, 16];
        for (uint256 k; k < widths.length; k++) {
            uint64 epoch = uint64(k + 1);
            uint256 idx = 0;
            BuyerSigVerifier.SellerReceipt memory r = _receipt(idx);
            bytes32 swapped = keccak256("a different leaf");
            bytes32 entry = FairBindMerkle.entryHash(r.nonce, swapped);
            bytes32[] memory path = new bytes32[](depths[k]);
            bytes32 h = entry;
            for (uint256 d; d < depths[k]; d++) {
                path[d] = keccak256(abi.encode("sibling", k, d));
                h = G10Merkle.node(h, path[d]);
            }
            v.setRoot(epoch, h);
            bytes memory ss = _sig(SELLER_KEY, G10Sig.typed(v.DOMAIN_SEPARATOR(), keccak256(abi.encode(RECEIPT_TYPEHASH, r))));
            uint256 g = gasleft();
            bool ok = v.proveSwap(epoch, r, ss, swapped, idx, path);
            g -= gasleft();
            _rec(address(v), abi.encodeCall(v.proveSwap, (epoch, r, ss, swapped, idx, path)));
            require(ok, "swap proof holds");
            _log(string.concat("G10-2 swap proof, epoch of ", _u(widths[k]), " entries (depth ", _u(depths[k]), "), tx gas"), g);
            _log(
                string.concat("G10-2 swap proof depth ", _u(depths[k]), ", calldata gas"),
                _cdGas(abi.encodeCall(v.proveSwap, (epoch, r, ss, swapped, idx, path)))
            );
        }
    }
}
