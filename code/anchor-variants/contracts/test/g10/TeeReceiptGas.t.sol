// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { G10Base, G10Sig, G10Merkle } from "./G10Base.sol";

/// Sketch of a rule 10 tier 1b verification contract for a TEE gateway
/// receipt. The receipt is shaped like a Phala ACI receipt (served_at, the
/// request body hash, the response hash, provider and model id, workload id,
/// flags for request or response modification) but carried as an EIP-712
/// struct: Phala signs canonical receipt bytes whose normalisation rule we
/// did not find, so the struct form is an assumption of this sketch. The
/// raw-bytes variant hashes a 1 KB receipt as calldata and recovers once,
/// without parsing fields.
///
/// The signer must be in the epoch's signer snapshot. Two snapshot forms:
/// a mapping (epoch, signer) => registered, and a Merkle root over the
/// snapshot's signer addresses with a path per receipt (16 signers, depth 4).
contract TeeReceiptVerifier {
    struct Receipt {
        uint64 servedAt;
        bytes32 requestHash;
        bytes32 responseHash;
        bytes32 providerId;
        bytes32 modelId;
        bytes32 workloadId;
        uint32 flags;
    }

    bytes32 internal constant RECEIPT_TYPEHASH = keccak256(
        "AciReceipt(uint64 servedAt,bytes32 requestHash,bytes32 responseHash,bytes32 providerId,bytes32 modelId,bytes32 workloadId,uint32 flags)"
    );
    bytes32 internal constant LEAF_DOMAIN = keccak256("fairbind/signer-leaf/v1");
    bytes32 public immutable DOMAIN_SEPARATOR;
    uint64 internal constant WINDOW = 120;

    mapping(uint64 => mapping(address => bool)) public inSnapshot;
    mapping(uint64 => bytes32) public snapshotRoot;

    constructor() {
        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256("TeeGatewayReceipt"),
                keccak256("1"),
                block.chainid,
                address(this)
            )
        );
    }

    function setSnapshot(uint64 epoch, address[] calldata signers, bytes32 root) external {
        for (uint256 i; i < signers.length; i++) inSnapshot[epoch][signers[i]] = true;
        snapshotRoot[epoch] = root;
    }

    function digestOf(Receipt calldata r) public view returns (bytes32) {
        return G10Sig.typed(DOMAIN_SEPARATOR, keccak256(abi.encode(RECEIPT_TYPEHASH, r)));
    }

    /// The checks a verification contract makes against what FairBind passes:
    /// the leaf's request and response hash, the recorded validAfter, the
    /// required model, no modification flag, and the signer in the snapshot.
    function _check(Receipt calldata r, bytes calldata sig, bytes32 req, bytes32 resp, uint64 validAfter, bytes32 model)
        internal
        view
        returns (address signer)
    {
        if (r.requestHash != req || r.responseHash != resp || r.modelId != model || r.flags != 0) return address(0);
        if (r.servedAt < validAfter || r.servedAt > validAfter + WINDOW) return address(0);
        signer = G10Sig.recover(digestOf(r), sig);
    }

    function verifyMapping(
        uint64 epoch,
        Receipt calldata r,
        bytes calldata sig,
        bytes32 req,
        bytes32 resp,
        uint64 validAfter,
        bytes32 model
    ) external returns (bool) {
        address s = _check(r, sig, req, resp, validAfter, model);
        return s != address(0) && inSnapshot[epoch][s];
    }

    function verifyMerkle(
        uint64 epoch,
        Receipt calldata r,
        bytes calldata sig,
        bytes32 req,
        bytes32 resp,
        uint64 validAfter,
        bytes32 model,
        uint256 signerIndex,
        bytes32[] calldata signerPath
    ) external returns (bool) {
        address s = _check(r, sig, req, resp, validAfter, model);
        if (s == address(0)) return false;
        bytes32 leaf = keccak256(abi.encode(LEAF_DOMAIN, s));
        return G10Merkle.rootOf(leaf, signerIndex, signerPath) == snapshotRoot[epoch];
    }

    struct Item {
        Receipt r;
        bytes sig;
        bytes32 req;
        bytes32 resp;
        uint64 validAfter;
    }

    /// A batch of receipts, each checked in full, signer by mapping.
    function verifyBatchMapping(uint64 epoch, Item[] calldata items, bytes32 model) external returns (uint256 ok) {
        for (uint256 i; i < items.length; i++) {
            Item calldata it = items[i];
            address s = _check(it.r, it.sig, it.req, it.resp, it.validAfter, model);
            if (s != address(0) && inSnapshot[epoch][s]) ok++;
        }
    }

    /// A batch with a signer path per receipt.
    function verifyBatchMerkle(
        uint64 epoch,
        Item[] calldata items,
        bytes32 model,
        uint256 signerIndex,
        bytes32[] calldata signerPath
    ) external returns (uint256 ok) {
        bytes32 root = snapshotRoot[epoch];
        for (uint256 i; i < items.length; i++) {
            Item calldata it = items[i];
            address s = _check(it.r, it.sig, it.req, it.resp, it.validAfter, model);
            if (s == address(0)) continue;
            if (G10Merkle.rootOf(keccak256(abi.encode(LEAF_DOMAIN, s)), signerIndex, signerPath) == root) ok++;
        }
    }

    /// Raw-bytes variant: keccak over the receipt bytes, one recovery, signer
    /// by mapping; field extraction is not included.
    function verifyRaw(uint64 epoch, bytes calldata receipt, bytes calldata sig) external returns (bool) {
        address s = G10Sig.recover(keccak256(receipt), sig);
        return s != address(0) && inSnapshot[epoch][s];
    }

    /// The raw-bytes variant with SHA-256 (precompile) as the receipt digest.
    function verifyRawSha(uint64 epoch, bytes calldata receipt, bytes calldata sig) external returns (bool) {
        address s = G10Sig.recover(sha256(receipt), sig);
        return s != address(0) && inSnapshot[epoch][s];
    }
}

/// Run with --isolate: each measured call is one transaction (21,000 base,
/// calldata, cold slots). Every number is logged; only correctness of the
/// sketch is asserted, nothing about gas.
contract TeeReceiptGasTest is G10Base {
    TeeReceiptVerifier internal v;
    uint256 internal constant TEE_KEY = 0x7EE1;
    uint64 internal constant EPOCH = 3;
    bytes32 internal constant MODEL = keccak256("model:example-70b");
    bytes32 internal constant LEAF_DOMAIN = keccak256("fairbind/signer-leaf/v1");
    address[] internal signers;
    bytes32[][] internal lv;
    uint256 internal teeIndex = 5;

    function setUp() public {
        v = new TeeReceiptVerifier();
        bytes32[] memory leaves = new bytes32[](16);
        for (uint256 i; i < 16; i++) {
            address a = i == teeIndex ? hv.addr(TEE_KEY) : hv.addr(0x1000 + i);
            signers.push(a);
            leaves[i] = keccak256(abi.encode(LEAF_DOMAIN, a));
        }
        lv = _levels(leaves);
        v.setSnapshot(EPOCH, signers, lv[lv.length - 1][0]);
        hv.roll(1000);
    }

    function _receipt(uint256 i) internal pure returns (TeeReceiptVerifier.Receipt memory r) {
        r.servedAt = uint64(1_800_000_000 + i);
        r.requestHash = keccak256(abi.encode("request", i));
        r.responseHash = keccak256(abi.encode("response", i));
        r.providerId = keccak256("provider:example");
        r.modelId = MODEL;
        r.workloadId = keccak256("workload:example");
        r.flags = 0;
    }

    function _item(uint256 i) internal returns (TeeReceiptVerifier.Item memory it) {
        it.r = _receipt(i);
        bytes32 d = _digest(it.r);
        it.sig = _sig(TEE_KEY, d);
        it.req = it.r.requestHash;
        it.resp = it.r.responseHash;
        it.validAfter = it.r.servedAt - 10;
    }

    function _digest(TeeReceiptVerifier.Receipt memory r) internal view returns (bytes32) {
        bytes32 typeHash = keccak256(
            "AciReceipt(uint64 servedAt,bytes32 requestHash,bytes32 responseHash,bytes32 providerId,bytes32 modelId,bytes32 workloadId,uint32 flags)"
        );
        return G10Sig.typed(v.DOMAIN_SEPARATOR(), keccak256(abi.encode(typeHash, r)));
    }

    function test_gas_teeReceiptSingle() public {
        TeeReceiptVerifier.Item memory it = _item(0);
        uint256 g = gasleft();
        bool ok = v.verifyMapping(EPOCH, it.r, it.sig, it.req, it.resp, it.validAfter, MODEL);
        g -= gasleft();
        _rec(address(v), abi.encodeCall(v.verifyMapping, (EPOCH, it.r, it.sig, it.req, it.resp, it.validAfter, MODEL)));
        require(ok, "mapping receipt verifies");
        _log("G10-1 single receipt, snapshot mapping, tx gas", g);
        _log(
            "G10-1 single receipt, snapshot mapping, calldata gas",
            _cdGas(abi.encodeCall(v.verifyMapping, (EPOCH, it.r, it.sig, it.req, it.resp, it.validAfter, MODEL)))
        );
        bytes32[] memory path = _path(lv, teeIndex);
        g = gasleft();
        ok = v.verifyMerkle(EPOCH, it.r, it.sig, it.req, it.resp, it.validAfter, MODEL, teeIndex, path);
        g -= gasleft();
        _rec(address(v), abi.encodeCall(v.verifyMerkle, (EPOCH, it.r, it.sig, it.req, it.resp, it.validAfter, MODEL, teeIndex, path)));
        require(ok, "merkle receipt verifies");
        _log("G10-1 single receipt, snapshot Merkle (16 signers, depth 4), tx gas", g);
        _log(
            "G10-1 single receipt, snapshot Merkle, calldata gas",
            _cdGas(abi.encodeCall(v.verifyMerkle, (EPOCH, it.r, it.sig, it.req, it.resp, it.validAfter, MODEL, teeIndex, path)))
        );
        // A wrong response hash is rejected, not reverted.
        require(!v.verifyMapping(EPOCH, it.r, it.sig, it.req, bytes32(uint256(1)), it.validAfter, MODEL), "mismatch rejects");
    }

    function _batch(uint256 n) internal returns (TeeReceiptVerifier.Item[] memory items) {
        items = new TeeReceiptVerifier.Item[](n);
        for (uint256 i; i < n; i++) items[i] = _item(i);
    }

    function test_gas_teeReceiptBatch() public {
        uint256[4] memory sizes = [uint256(1), 2, 8, 32];
        for (uint256 k; k < sizes.length; k++) {
            uint256 n = sizes[k];
            TeeReceiptVerifier.Item[] memory items = _batch(n);
            uint256 g = gasleft();
            uint256 ok = v.verifyBatchMapping(EPOCH, items, MODEL);
            g -= gasleft();
            _rec(address(v), abi.encodeCall(v.verifyBatchMapping, (EPOCH, items, MODEL)));
            require(ok == n, "every receipt verifies");
            _log(string.concat("G10-1 batch mapping n=", _u(n), " tx gas"), g);
            _log(
                string.concat("G10-1 batch mapping n=", _u(n), " calldata gas"),
                _cdGas(abi.encodeCall(v.verifyBatchMapping, (EPOCH, items, MODEL)))
            );
            bytes32[] memory path = _path(lv, teeIndex);
            g = gasleft();
            ok = v.verifyBatchMerkle(EPOCH, items, MODEL, teeIndex, path);
            g -= gasleft();
            _rec(address(v), abi.encodeCall(v.verifyBatchMerkle, (EPOCH, items, MODEL, teeIndex, path)));
            require(ok == n, "every receipt verifies (merkle)");
            _log(string.concat("G10-1 batch Merkle n=", _u(n), " tx gas"), g);
        }
    }

    function test_gas_teeReceiptRaw() public {
        bytes memory receipt = new bytes(1024);
        for (uint256 i; i < 1024; i++) receipt[i] = bytes1(uint8(0x20 + (i * 7) % 90));
        bytes memory sigK = _sig(TEE_KEY, keccak256(receipt));
        uint256 g = gasleft();
        bool ok = v.verifyRaw(EPOCH, receipt, sigK);
        g -= gasleft();
        _rec(address(v), abi.encodeCall(v.verifyRaw, (EPOCH, receipt, sigK)));
        require(ok, "raw receipt verifies");
        _log("G10-1 raw 1 KB receipt, keccak digest, tx gas", g);
        _log("G10-1 raw 1 KB receipt, calldata gas", _cdGas(abi.encodeCall(v.verifyRaw, (EPOCH, receipt, sigK))));
        bytes memory sigS = _sig(TEE_KEY, sha256(receipt));
        g = gasleft();
        ok = v.verifyRawSha(EPOCH, receipt, sigS);
        g -= gasleft();
        _rec(address(v), abi.encodeCall(v.verifyRawSha, (EPOCH, receipt, sigS)));
        require(ok, "raw sha receipt verifies");
        _log("G10-1 raw 1 KB receipt, sha256 digest, tx gas", g);
    }
}
