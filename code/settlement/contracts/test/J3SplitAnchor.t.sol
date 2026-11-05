// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { SamplingStore } from "../src/modules/SamplingStore.sol";
import { ReproBase } from "./repro/ReproBase.sol";

interface J3Vm {
    function snapshotState() external returns (uint256);
    function revertToState(uint256 id) external returns (bool);
}

/// Split anchoring (journal J3): an epoch's list posted in units of 2^unitLog2
/// entries, one transaction each, anchored when the last unit is in, with the
/// root of the whole list. Epoch 0 of the base profile has its anchor window
/// at blocks 600..700.
contract J3SplitAnchorTest is ReproBase {
    J3Vm internal constant jv = J3Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    bytes32 internal constant PUB = keccak256("publication");

    function _setUp(uint256 purchases) internal returns (bytes32[] memory ns, bytes32 wholeRoot) {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        p.bucketCapacity = 200;
        _deploy(p);
        hv.roll(10);
        ns = new bytes32[](purchases);
        for (uint256 i; i < purchases; i++) ns[i] = _purchase(10_000);
        wholeRoot = _buildTree(ns);
    }

    function _slice(uint256 from, uint256 to) internal view returns (FairBindMerkle.ReceiptEntry[] memory part) {
        FairBindMerkle.ReceiptEntry[] memory all = _treeEntries();
        part = new FairBindMerkle.ReceiptEntry[](to - from);
        for (uint256 i = from; i < to; i++) part[i - from] = all[i];
    }

    function _unit(uint32 unit, uint8 log2, uint256 from, uint256 to) internal {
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, unit, log2, _slice(from, to), keccak256(abi.encode(PUB, unit)));
    }

    /// Posts every unit of the tree built by _setUp.
    function _postAll(uint256 n, uint8 log2) internal {
        uint256 size = uint256(1) << log2;
        uint32 unit;
        for (uint256 from; from < n; from += size) {
            uint256 to = from + size < n ? from + size : n;
            _unit(unit++, log2, from, to);
        }
    }

    function _state() internal view returns (uint8) {
        return fairbind.getAnchor(sellerId, 0).state;
    }

    // ------------------------------------------------------- two units

    function test_twoUnitsGiveTheRootOfTheWholeList() public {
        (bytes32[] memory ns, bytes32 whole) = _setUp(8);
        hv.roll(650);
        _unit(0, 2, 0, 4);
        require(_state() == uint8(FairBindCore.EpochState.NONE), "not anchored by the first unit");
        _unit(1, 2, 4, 8);
        FairBindCore.AnchorView memory rec = fairbind.getAnchor(sellerId, 0);
        require(rec.state == uint8(FairBindCore.EpochState.ANCHORED), "anchored by the last unit");
        require(rec.root == whole, "root of the whole list");
        require(rec.count == 8, "count");
        require(rec.randomBlock == 700 + 1 + 768, "value block");
        (uint8 log2, bytes32[] memory roots, bytes32[] memory pubs) = fairbind.getAnchorUnits(sellerId, 0);
        require(log2 == 2 && roots.length == 2 && pubs.length == 2, "units recorded");
        require(rec.publicationHash == keccak256(abi.encodePacked(pubs)), "publication hash covers the units");
        // The unit roots are the level-two nodes of the whole-list tree.
        require(roots[0] == levels[2][0] && roots[1] == levels[2][1], "sub-roots");
        // The existing machinery runs on the split epoch unchanged: seal, open, receipt with a whole-list proof.
        hv.roll(700 + 1 + 768 + 1);
        hv.setBlockhash(700 + 1 + 768, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
        fairbind.openSample(ns[3]);
        FairBindCore.FairBindReceipt memory r = _receipt(ns[3]);
        fairbind.submitSampleReceipt(ns[3], r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(ns[3]));
    }

    /// Membership over (unit, leaf): the proof is as deep as the unit.
    function test_membershipProofOverUnitAndLeaf() public {
        (bytes32[] memory ns, ) = _setUp(8);
        hv.roll(650);
        _postAll(8, 2);
        for (uint256 i; i < ns.length; i++) {
            uint32 idx = treeIndex[ns[i]];
            FairBindCore.ReceiptProof memory whole = _proof(ns[i]);
            bytes32[] memory sib = new bytes32[](2);
            sib[0] = whole.siblings[0];
            sib[1] = whole.siblings[1];
            bytes32 leaf = sortedLeaves[idx];
            require(fairbind.verifyUnitMember(sellerId, 0, idx / 4, ns[i], leaf, idx % 4, sib), "member");
            require(!fairbind.verifyUnitMember(sellerId, 0, 1 - idx / 4, ns[i], leaf, idx % 4, sib), "other unit");
            require(!fairbind.verifyUnitMember(sellerId, 0, idx / 4, ns[i], keccak256("x"), idx % 4, sib), "other leaf");
        }
    }

    // ------------------------------------------- uneven last unit, one unit

    function _rootAfter(uint256 n, uint8 log2) internal returns (bytes32 splitRoot, bytes32 whole) {
        bytes32[] memory ns;
        (ns, whole) = _setUp(n);
        hv.roll(650);
        _postAll(n, log2);
        splitRoot = fairbind.getAnchor(sellerId, 0).root;
    }

    function test_unevenLastUnitMatchesTheWholeListTree() public {
        uint256[4] memory sizes = [uint256(9), 10, 11, 13];
        for (uint256 k; k < sizes.length; k++) {
            uint256 snap = jv.snapshotState();
            (bytes32 splitRoot, bytes32 whole) = _rootAfter(sizes[k], 2);
            require(splitRoot == whole, "9, 10, 11, 13 entries in units of 4");
            jv.revertToState(snap);
        }
    }

    function test_oneUnitEqualsTheSingleTransactionAnchor() public {
        uint256 snap = jv.snapshotState();
        (bytes32 splitRoot, bytes32 whole) = _rootAfter(3, 13);
        require(splitRoot == whole, "single unit: its root is the root");
        jv.revertToState(snap);
        (, whole) = _setUp(3);
        hv.roll(650);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 3, PUB);
        require(fairbind.getAnchor(sellerId, 0).root == whole, "legacy root");
        // The single-unit publication hash is the unit's own, as for anchor.
    }

    // -------------------------------------------------------- cap checks

    function test_unitSizeCapAndBoundary() public {
        _setUp(5);
        hv.roll(650);
        // 2^14 is over the cap; 2^13 is the largest admitted size.
        hv.expectRevert(SamplingStore.UnitTooLarge.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 0, 14, _slice(0, 5), PUB);
        // A unit is exactly as long as the epoch count and the unit size fix it.
        hv.expectRevert(FairBindCore.CountMismatch.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 0, 2, _slice(0, 5), PUB); // 5 entries in a unit of 4
        hv.expectRevert(FairBindCore.CountMismatch.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 0, 2, _slice(0, 3), PUB); // 3 entries where 4 are due
        _unit(0, 2, 0, 4); // exactly full: admitted
        hv.expectRevert(FairBindCore.CountMismatch.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 1, 2, _slice(0, 2), PUB); // the last unit holds the rest: 1, not 2
    }

    function test_unitOrderAndSizeAreChecked() public {
        _setUp(8);
        hv.roll(650);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 1, 2, _slice(4, 8), PUB); // unit 1 before unit 0
        _unit(0, 2, 0, 4);
        hv.expectRevert(FairBindCore.InvalidConfiguration.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 1, 1, _slice(4, 6), PUB); // another unit size
        hv.expectRevert(FairBindCore.EntriesNotAscending.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 1, 2, _slice(0, 4), PUB); // nonces do not continue the list
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        fairbind.anchorUnit(sellerId, 0, 1, 2, _slice(4, 8), PUB); // not the seller
        _unit(1, 2, 4, 8);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 2, 2, _slice(4, 8), PUB); // anchored already
    }

    function test_incompleteUnitsEndAsAMissedAnchor() public {
        _setUp(8);
        hv.roll(650);
        _unit(0, 2, 0, 4);
        hv.roll(701);
        hv.expectRevert(FairBindCore.AnchorWindowClosed.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 1, 2, _slice(4, 8), PUB);
        fairbind.timeoutAnchor(sellerId, 0);
        require(_state() == uint8(FairBindCore.EpochState.EPOCH_FAILED), "missed anchor");
        require(!fairbind.verifyUnitMember(sellerId, 0, 0, sortedNonces[0], sortedLeaves[0], 0, new bytes32[](2)), "no member of an unanchored epoch");
    }

    function test_singleTransactionAnchorStillWorksAndBlocksUnits() public {
        _setUp(4);
        hv.roll(650);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 4, PUB);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 0, 2, _slice(0, 4), PUB);
    }

    // --------------------------------------------------------------- gas

    function _gasLine(string memory label, uint256 g) internal view {
        _log(string.concat("J3 ", label), g);
    }

    /// Gas of the anchor transactions of a 64-entry epoch as one transaction,
    /// as a single unit, and as 2 and 4 units, and of a membership proof.
    function test_gas_anchorOneVersusTwoUnits() public {
        uint256 n = 64;
        _setUp(n);
        hv.roll(650);
        uint256 snap = jv.snapshotState();
        uint256 g;
        hv.prank(SELLER_OWNER);
        g = gasleft();
        fairbind.anchor(sellerId, 0, _treeEntries(), uint32(n), PUB);
        _gasLine("anchor 64 entries, one transaction (anchor)", g - gasleft());
        jv.revertToState(snap);
        uint8[3] memory logs = [uint8(6), 5, 4];
        for (uint256 k; k < logs.length; k++) {
            uint256 size = uint256(1) << logs[k];
            uint256 total;
            uint32 unit;
            for (uint256 from; from < n; from += size) {
                FairBindMerkle.ReceiptEntry[] memory part = _slice(from, from + size);
                hv.prank(SELLER_OWNER);
                g = gasleft();
                fairbind.anchorUnit(sellerId, 0, unit, logs[k], part, keccak256(abi.encode(PUB, unit)));
                g -= gasleft();
                total += g;
                _gasLine(string.concat("anchorUnit ", _u(n / size), " unit(s) of ", _u(size), ", unit ", _u(unit)), g);
                unit++;
            }
            _gasLine(string.concat("sum of the ", _u(n / size), " transaction(s) of ", _u(size), " entries"), total);
            jv.revertToState(snap);
        }
        // Membership: whole-list proof against the root (library call) and unit proof (router view).
        _postAll(n, 5);
        bytes32 nonce = sortedNonces[40];
        bytes32 leaf = sortedLeaves[40];
        FairBindCore.ReceiptProof memory whole = _proof(nonce);
        bytes32 root = fairbind.getAnchor(sellerId, 0).root;
        g = gasleft();
        bool ok = _verifyWhole(root, nonce, leaf, whole);
        _gasLine("membership check, whole list of 64 (depth 6), internal call", g - gasleft());
        require(ok, "whole proof");
        bytes32[] memory sib = new bytes32[](5);
        for (uint256 i; i < 5; i++) sib[i] = whole.siblings[i];
        g = gasleft();
        ok = fairbind.verifyUnitMember(sellerId, 0, 1, nonce, leaf, 8, sib);
        _gasLine("membership check over (unit, leaf), unit of 32 (depth 5), router view", g - gasleft());
        require(ok, "unit proof");
    }

    function _verifyWhole(bytes32 root, bytes32 nonce, bytes32 leaf, FairBindCore.ReceiptProof memory pr)
        internal
        pure
        returns (bool)
    {
        return FairBindMerkle.verify(root, nonce, leaf, pr.index, pr.count, pr.siblings);
    }

    function _u(uint256 x) internal pure returns (string memory) {
        if (x == 0) return "0";
        uint256 d;
        for (uint256 t = x; t != 0; t /= 10) d++;
        bytes memory b = new bytes(d);
        while (x != 0) {
            b[--d] = bytes1(uint8(48 + (x % 10)));
            x /= 10;
        }
        return string(b);
    }
}
