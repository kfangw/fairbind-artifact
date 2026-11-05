// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { ReproBase } from "./repro/ReproBase.sol";
import { AnchorLeaves } from "./AnchorLeaves.sol";

/// Exposes the library function, which takes call data, to a test.
contract MerkleHarness {
    function computeRoot(FairBindMerkle.ReceiptEntry[] calldata entries) external pure returns (bytes32) {
        return FairBindMerkle.computeRoot(entries);
    }

    function verify(
        bytes32 root,
        bytes32 nonce,
        bytes32 receiptLeaf,
        uint32 index,
        uint32 count,
        bytes32[] calldata siblings
    ) external pure returns (bool) {
        return FairBindMerkle.verify(root, nonce, receiptLeaf, index, count, siblings);
    }
}

/// Independent checks of the anchor entry list (ADR 0026), from review 3 of
/// IMPL2: computeRoot against verify for random lists, and the omission
/// paths against lists a seller controls. Under the (nonce, receiptLeaf)
/// anchor with strictly ascending nonces, fillers and a bad order no longer
/// block an omission proof: a filler is just an entry whose nonce brackets
/// the omitted one, and a list out of order does not anchor.
contract AnchorReviewCheckTest is ReproBase {
    MerkleHarness internal h;

    function _siblings(bytes32[] memory entries, uint256 idx) internal pure returns (bytes32[] memory sib) {
        uint256 height;
        for (uint256 w = entries.length; w > 1; w = (w + 1) / 2) height++;
        sib = new bytes32[](height);
        bytes32[] memory level = entries;
        uint256 cursor = idx;
        for (uint256 hgt; hgt < height; hgt++) {
            uint256 other = cursor ^ 1;
            sib[hgt] = other < level.length ? level[other] : level[cursor];
            uint256 w = (level.length + 1) / 2;
            bytes32[] memory up = new bytes32[](w);
            for (uint256 i; i < w; i++) {
                bytes32 left = level[2 * i];
                bytes32 right = 2 * i + 1 < level.length ? level[2 * i + 1] : left;
                up[i] = keccak256(abi.encode(AnchorLeaves.NODE_DOMAIN, left, right));
            }
            level = up;
            cursor >>= 1;
        }
    }

    function test_computeRootEmptyAndSingle() public {
        h = new MerkleHarness();
        require(h.computeRoot(new FairBindMerkle.ReceiptEntry[](0)) == bytes32(0), "empty");
        bytes32 n = keccak256("n");
        bytes32 l = keccak256("l");
        FairBindMerkle.ReceiptEntry[] memory one = AnchorLeaves.pair(n, l);
        require(h.computeRoot(one) == AnchorLeaves.entryHash(n, l), "single entry hash is the root");
        require(h.verify(h.computeRoot(one), n, l, 0, 1, new bytes32[](0)), "single leaf proof");
        require(!h.verify(h.computeRoot(one), n, keccak256("other"), 0, 1, new bytes32[](0)), "other leaf");
    }

    /// Lengths 1 to 64 with 4 random lists each, then larger sizes: the
    /// on-chain root equals the reference root, and every entry's proof,
    /// built from the reference tree, verifies against the on-chain root.
    /// Each list is checked in its own call so memory is released between lists.
    function test_computeRootDifferentialAgainstVerify() public {
        h = new MerkleHarness();
        uint256 seed = uint256(keccak256("review3"));
        for (uint256 n = 1; n <= 64; n++) {
            for (uint256 r; r < 4; r++) this.checkList(n, seed = uint256(keccak256(abi.encode(seed, n, r))));
        }
        uint256[6] memory big = [uint256(65), 127, 128, 129, 255, 1000];
        for (uint256 s; s < big.length; s++) this.checkList(big[s], seed = uint256(keccak256(abi.encode(seed, s))));
    }

    function checkList(uint256 n, uint256 seed) external {
        FairBindMerkle.ReceiptEntry[] memory list = new FairBindMerkle.ReceiptEntry[](n);
        for (uint256 i; i < n; i++) {
            seed = uint256(keccak256(abi.encode(seed, i)));
            bytes32 nonce = bytes32(seed);
            seed = uint256(keccak256(abi.encode(seed)));
            list[i] = FairBindMerkle.ReceiptEntry(nonce, bytes32(seed));
        }
        bytes32[] memory entries = AnchorLeaves.hashes(list);
        bytes32 root = h.computeRoot(list);
        require(root == AnchorLeaves.rootOf(entries), "root equals reference");
        uint256 step = n > 130 ? n / 8 + 1 : 1;
        for (uint256 i; i < n; i += step) {
            require(
                h.verify(root, list[i].nonce, list[i].receiptLeaf, uint32(i), uint32(n), _siblings(entries, i)),
                "proof verifies against computeRoot"
            );
        }
        require(
            h.verify(
                root, list[n - 1].nonce, list[n - 1].receiptLeaf, uint32(n - 1), uint32(n), _siblings(entries, n - 1)
            ),
            "last leaf"
        );
    }

    // ------------------------------------------------ omission-path checks

    function _entryOf(bytes32 n) internal view returns (FairBindMerkle.ReceiptEntry memory) {
        return FairBindMerkle.ReceiptEntry(n, fairbind.receiptDigest(_receipt(n)));
    }

    function _proofAt(FairBindMerkle.ReceiptEntry[] memory list, uint256 idx)
        internal
        pure
        returns (FairBindCore.ReceiptProof memory)
    {
        return FairBindCore.ReceiptProof(uint32(idx), uint32(list.length), _siblings(AnchorLeaves.hashes(list), idx));
    }

    function _tryOmission(
        bytes32 omitted,
        FairBindMerkle.ReceiptEntry[] memory list,
        uint256 li,
        uint256 ri,
        uint8 boundary
    ) internal returns (bool ok) {
        try fairbind.proveOmission(omitted, list[li], _proofAt(list, li), list[ri], _proofAt(list, ri), boundary) {
            ok = true;
        } catch {
            ok = false;
        }
    }

    function _anchor(FairBindMerkle.ReceiptEntry[] memory list) internal {
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, list, uint32(list.length), keccak256("publication"));
        require(fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.ANCHORED), "anchored");
    }

    function _refundable(bytes32 n) internal view returns (bool) {
        return fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE);
    }

    /// A filler between two real entries, in the omitted purchase's place.
    /// The filler's nonce must sit between its neighbours, so it brackets the
    /// omitted nonce with one of them and anyone proves the omission. The
    /// pair that is not adjacent (a and c) still proves nothing.
    function test_fillerBetweenRealEntriesAdmitsOmissionProof() public {
        _deploy(_productionProfile());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](3);
        for (uint256 i; i < 3; i++) ns[i] = _purchase(10_000);
        _buildTree(ns);
        bytes32 a = sortedNonces[0];
        bytes32 b = sortedNonces[1];
        bytes32 c = sortedNonces[2];
        FairBindMerkle.ReceiptEntry[] memory published = new FairBindMerkle.ReceiptEntry[](3);
        published[0] = _entryOf(a);
        published[1] = FairBindMerkle.ReceiptEntry(
            bytes32(uint256(b) + 1), keccak256("filler in place of the omitted purchase")
        );
        published[2] = _entryOf(c);
        require(uint256(b) + 1 < uint256(c), "fixture: room above b");
        _anchor(published);
        uint8 interior = uint8(FairBindCore.ProofBoundary.INTERIOR);
        require(!_tryOmission(b, published, 0, 2, interior), "non-adjacent pair");
        require(!_tryOmission(b, published, 1, 2, interior), "pair above b");
        require(!_tryOmission(a, published, 0, 1, interior), "a is listed");
        require(!_tryOmission(c, published, 1, 2, interior), "c is listed");
        require(_tryOmission(b, published, 0, 1, interior), "a < b < filler proves omission");
        require(_refundable(b), "omitted purchase refundable");
        require(!_refundable(a) && !_refundable(c), "listed purchases untouched");
    }

    /// A list of fillers only: every real purchase of the epoch is missing,
    /// and each one's omission is provable. The fillers lie below all real
    /// nonces here, so the last filler bounds each purchase from below.
    function test_allFillerListAdmitsOmissionProofForEveryPurchase() public {
        _deploy(_productionProfile());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](3);
        for (uint256 i; i < 3; i++) ns[i] = _purchase(10_000);
        _buildTree(ns);
        FairBindMerkle.ReceiptEntry[] memory published = new FairBindMerkle.ReceiptEntry[](3);
        for (uint256 i; i < 3; i++) {
            published[i] = FairBindMerkle.ReceiptEntry(bytes32(i + 1), keccak256(abi.encode("filler", i)));
        }
        _anchor(published);
        uint8 upper = uint8(FairBindCore.ProofBoundary.UPPER);
        uint8 lower = uint8(FairBindCore.ProofBoundary.LOWER);
        for (uint256 o; o < 3; o++) {
            bytes32 n = sortedNonces[o];
            require(!_tryOmission(n, published, 1, 1, upper), "upper needs the last index");
            require(!_tryOmission(n, published, 0, 0, lower), "lower needs omitted < first");
            require(_tryOmission(n, published, 2, 2, upper), "omission proven");
            require(_refundable(n), "refundable");
        }
    }

    /// A list out of order does not anchor, so it cannot block an interior
    /// proof. With the real entries a and d in order and fillers above d,
    /// both omitted purchases b and c lie between a and d.
    function test_descendingOrderDoesNotAnchorAndSortedListAdmitsInteriorProof() public {
        _deploy(_productionProfile());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](4);
        for (uint256 i; i < 4; i++) ns[i] = _purchase(10_000);
        _buildTree(ns);
        bytes32 a = sortedNonces[0];
        bytes32 b = sortedNonces[1];
        bytes32 c = sortedNonces[2];
        bytes32 d = sortedNonces[3];
        FairBindMerkle.ReceiptEntry[] memory published = new FairBindMerkle.ReceiptEntry[](4);
        published[0] = _entryOf(d);
        published[1] = _entryOf(a);
        published[2] = FairBindMerkle.ReceiptEntry(bytes32(uint256(d) + 1), keccak256("f1"));
        published[3] = FairBindMerkle.ReceiptEntry(bytes32(uint256(d) + 2), keccak256("f2"));
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.EntriesNotAscending.selector);
        fairbind.anchor(sellerId, 0, published, 4, keccak256("publication"));
        (published[0], published[1]) = (published[1], published[0]);
        _anchor(published);
        uint8 interior = uint8(FairBindCore.ProofBoundary.INTERIOR);
        require(_tryOmission(b, published, 0, 1, interior), "b between a and d");
        require(_tryOmission(c, published, 0, 1, interior), "c between a and d");
        require(_refundable(b) && _refundable(c), "both refundable");
    }
}
