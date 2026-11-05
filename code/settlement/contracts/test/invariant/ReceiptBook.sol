// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBind } from "../../src/FairBind.sol";
import { FairBindCore } from "../../src/FairBindCore.sol";
import { FairBindMerkle } from "../../src/FairBindMerkle.sol";
import { Inv } from "./InvariantBase.sol";

/// Canonical requests, seller-signed receipts, verdict signatures and the
/// ordered receipt tree of every anchored seller epoch of the stateful suite.
contract ReceiptBook {
    bytes32 internal constant LEAF_DOMAIN = keccak256("fairbind/epoch-leaf/v1");
    bytes32 internal constant NODE_DOMAIN = keccak256("fairbind/epoch-node/v1");

    FairBind public immutable fb;
    address public immutable writer;

    mapping(uint32 => uint256) public sellerKey;
    mapping(bytes32 => bytes16) public keyOf;
    mapping(uint256 => bytes32[]) internal members;
    mapping(uint256 => bytes32[][]) internal levels;
    mapping(uint256 => bool) public built;
    mapping(uint256 => bytes32[]) internal sortedMembers;
    mapping(bytes32 => uint32) internal leafIndex;

    constructor(FairBind fairbind, address handler) {
        fb = fairbind;
        writer = handler;
    }

    modifier onlyWriter() {
        require(msg.sender == writer, "writer");
        _;
    }

    function epochKey(uint32 sellerId, uint24 epoch) public pure returns (uint256) {
        return (uint256(sellerId) << 24) | epoch;
    }

    function setSellerKey(uint32 sellerId, uint256 key) external onlyWriter {
        sellerKey[sellerId] = key;
    }

    function request(bytes16 key) public pure returns (FairBindCore.CanonicalRequest memory r) {
        r = FairBindCore.CanonicalRequest(bytes("GET"), bytes("/item"), bytes(""), bytes(""), abi.encode(key));
    }

    function requestHash(bytes16 key) external view returns (bytes32) {
        return fb.canonicalRequestHash(request(key), Inv.CANON);
    }

    function addPurchase(bytes32 nonce, bytes16 key) external onlyWriter {
        FairBindCore.PurchaseView memory p = fb.getPurchase(nonce);
        keyOf[nonce] = key;
        members[epochKey(p.sellerId, p.epoch)].push(nonce);
    }

    function memberCount(uint32 sellerId, uint24 epoch) external view returns (uint256) {
        return members[epochKey(sellerId, epoch)].length;
    }

    function receipt(bytes32 nonce) public view returns (FairBindCore.FairBindReceipt memory r) {
        FairBindCore.PurchaseView memory p = fb.getPurchase(nonce);
        r = FairBindCore.FairBindReceipt(
            1,
            p.sellerId,
            p.profileId,
            nonce,
            p.requestHash,
            keccak256(Inv.RESPONSE_BODY),
            p.claimsHash,
            Inv.COMMITMENT,
            p.epoch,
            1
        );
    }

    function sign(uint256 key, bytes32 digest) public returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = Inv.vm.sign(key, digest);
        return abi.encodePacked(r, s, v);
    }

    function signedReceipt(bytes32 nonce)
        external
        returns (FairBindCore.FairBindReceipt memory r, bytes memory signature)
    {
        r = receipt(nonce);
        signature = sign(sellerKey[r.sellerId], fb.receiptDigest(r));
    }

    /// A receipt for the purchase signed with another seller's key.
    function foreignReceipt(bytes32 nonce, uint256 key)
        external
        returns (FairBindCore.FairBindReceipt memory r, bytes memory signature)
    {
        r = receipt(nonce);
        signature = sign(key, fb.receiptDigest(r));
    }

    function signedVerdict(bytes32 nonce, uint8 result)
        external
        returns (FairBindCore.SignedVerdict memory v, bytes memory signature)
    {
        FairBindCore.CaseView memory c = fb.getCase(nonce);
        v = FairBindCore.SignedVerdict(
            1, nonce, c.stage, c.attempt, c.assignedVerifierId, result, keccak256(Inv.EVIDENCE)
        );
        signature = sign(Inv.VERIFIER_KEY_BASE + c.assignedVerifierId, fb.verdictDigest(v));
    }

    /// Builds the ordered receipt tree of merkle-v1 over every purchase of the
    /// seller epoch.
    function build(uint32 sellerId, uint24 epoch) external onlyWriter returns (bytes32 root, uint32 count) {
        uint256 ek = epochKey(sellerId, epoch);
        bytes32[] memory s = members[ek];
        uint256 n = s.length;
        count = uint32(n);
        for (uint256 i = 1; i < n; i++) {
            bytes32 x = s[i];
            uint256 j = i;
            while (j > 0 && uint256(s[j - 1]) > uint256(x)) {
                s[j] = s[j - 1];
                j--;
            }
            s[j] = x;
        }
        delete levels[ek];
        sortedMembers[ek] = s;
        bytes32[] memory level = new bytes32[](n);
        for (uint256 i; i < n; i++) {
            leafIndex[s[i]] = uint32(i);
            level[i] = keccak256(abi.encode(LEAF_DOMAIN, s[i], fb.receiptDigest(receipt(s[i]))));
        }
        levels[ek].push(level);
        while (level.length > 1) {
            uint256 w = (level.length + 1) / 2;
            bytes32[] memory up = new bytes32[](w);
            for (uint256 i; i < w; i++) {
                bytes32 left = level[2 * i];
                bytes32 right = 2 * i + 1 < level.length ? level[2 * i + 1] : left;
                up[i] = keccak256(abi.encode(NODE_DOMAIN, left, right));
            }
            levels[ek].push(up);
            level = up;
        }
        root = level[0];
        built[ek] = true;
    }

    /// The (nonce, receiptLeaf) pairs of the built tree in nonce order: the
    /// list an anchor carries.
    function entries(uint32 sellerId, uint24 epoch)
        external
        view
        returns (FairBindMerkle.ReceiptEntry[] memory list)
    {
        bytes32[] storage s = sortedMembers[epochKey(sellerId, epoch)];
        list = new FairBindMerkle.ReceiptEntry[](s.length);
        for (uint256 i; i < s.length; i++) {
            list[i] = FairBindMerkle.ReceiptEntry(s[i], fb.receiptDigest(receipt(s[i])));
        }
    }

    function proof(bytes32 nonce) external view returns (FairBindCore.ReceiptProof memory p) {
        FairBindCore.PurchaseView memory pv = fb.getPurchase(nonce);
        uint256 ek = epochKey(pv.sellerId, pv.epoch);
        if (!built[ek]) return FairBindCore.ReceiptProof(0, 0, new bytes32[](0));
        bytes32[][] storage lv = levels[ek];
        uint256 height = lv.length - 1;
        bytes32[] memory siblings = new bytes32[](height);
        uint256 cursor = leafIndex[nonce];
        for (uint256 h; h < height; h++) {
            bytes32[] storage row = lv[h];
            uint256 other = cursor ^ 1;
            siblings[h] = other < row.length ? row[other] : row[cursor];
            cursor >>= 1;
        }
        p = FairBindCore.ReceiptProof(leafIndex[nonce], uint32(lv[0].length), siblings);
    }
}
