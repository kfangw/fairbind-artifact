// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBind } from "../src/FairBind.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { ReproBase } from "./repro/ReproBase.sol";
import { AnchorLeaves } from "./AnchorLeaves.sol";

struct CallGas {
    uint64 gasLimit;
    uint64 gasTotalUsed;
    uint64 gasMemoryUsed;
    int64 gasRefunded;
    uint64 gasRemaining;
}

interface AnchorVm {
    function store(address target, bytes32 slot, bytes32 value) external;
    function cool(address target) external;
    function lastCallGas() external view returns (CallGas memory);
    function snapshotState() external returns (uint256);
    function revertToState(uint256 snapshotId) external returns (bool);
}

/// Exposes the library functions, which take call data, to a test.
contract AnchorMerkleHarness {
    function computeRoot(FairBindMerkle.ReceiptEntry[] calldata entries) external pure returns (bytes32) {
        return FairBindMerkle.computeRoot(entries);
    }

    function strictlyAscending(FairBindMerkle.ReceiptEntry[] calldata entries) external pure returns (bool) {
        return FairBindMerkle.strictlyAscending(entries);
    }
}

/// ADR 0026: the anchor carries the (nonce, receiptLeaf) list in strictly
/// ascending nonce order and the contract computes the root from it.
contract AnchorEntryListTest is ReproBase {
    AnchorVm internal constant av = AnchorVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 internal constant G = 10_000;
    /// Storage slot of epochPurchaseCount (test-vectors/deployment/monolith-storage.json).
    uint256 internal constant EPOCH_PURCHASE_COUNT_SLOT = 14;

    function _sampledProfile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
    }

    function _purchases(uint256 k) internal returns (bytes32[] memory ns) {
        hv.roll(10);
        ns = new bytes32[](k);
        for (uint256 i; i < k; i++) ns[i] = _purchase(G);
    }

    function _entryOf(bytes32 n) internal view returns (FairBindMerkle.ReceiptEntry memory) {
        return FairBindMerkle.ReceiptEntry(n, fairbind.receiptDigest(_receipt(n)));
    }

    /// merkle-v1 inclusion proof for position idx of an arbitrary ordered list.
    function _proofOf(FairBindMerkle.ReceiptEntry[] memory list, uint256 idx)
        internal
        pure
        returns (FairBindCore.ReceiptProof memory p)
    {
        bytes32[] memory level = AnchorLeaves.hashes(list);
        uint256 n = level.length;
        uint256 height;
        for (uint256 w = n; w > 1; w = (w + 1) / 2) height++;
        bytes32[] memory siblings = new bytes32[](height);
        uint256 cursor = idx;
        for (uint256 h; h < height; h++) {
            uint256 other = cursor ^ 1;
            siblings[h] = other < level.length ? level[other] : level[cursor];
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
        p = FairBindCore.ReceiptProof(uint32(idx), uint32(n), siblings);
    }

    function _anchorList(FairBindMerkle.ReceiptEntry[] memory list) internal {
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, list, uint32(list.length), keccak256("publication"));
    }

    // ------------------------------------------------------------ (a) root

    /// For list lengths 1 to 9 (odd last nodes at several levels) the stored
    /// root equals the off-chain root, and every purchase's inclusion proof
    /// from the off-chain tree verifies against it.
    function test_anchorStoresTheRootOfItsEntryList() public {
        for (uint256 k = 1; k <= 9; k++) {
            // Each deployment starts at block 1, as a test's first one does.
            hv.roll(1);
            _deploy(_productionProfile());
            bytes32[] memory ns = _purchases(k);
            bytes32 expected = _buildTree(ns);
            FairBindMerkle.ReceiptEntry[] memory entries = _treeEntries();
            require(_anchorRoot(entries) == expected, "off-chain helpers agree");
            _anchorList(entries);
            FairBindCore.AnchorView memory a = fairbind.getAnchor(sellerId, 0);
            require(a.root == expected, "stored root is the off-chain root");
            require(a.count == k, "count");
            require(a.publicationHash == keccak256("publication"), "publication hash kept");
            for (uint256 i; i < k; i++) {
                bytes32 n = ns[i];
                FairBindCore.ReceiptProof memory p = _proof(n);
                require(
                    FairBindMerkle.verify(
                        a.root, n, fairbind.receiptDigest(_receipt(n)), p.index, p.count, p.siblings
                    ),
                    "inclusion proof verifies"
                );
            }
        }
    }

    /// The contract's own proof check accepts the off-chain proof against the
    /// computed root: a sampled receipt with its inclusion proof is accepted.
    function test_contractAcceptsInclusionProofAgainstComputedRoot() public {
        _deploy(_sampledProfile());
        bytes32[] memory ns = _purchases(5);
        bytes32 expected = _buildTree(ns);
        _anchorList(_treeEntries());
        require(fairbind.getAnchor(sellerId, 0).root == expected, "root");
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
        for (uint256 i; i < 5; i++) {
            fairbind.openSample(ns[i]);
            FairBindCore.FairBindReceipt memory r = _receipt(ns[i]);
            fairbind.submitSampleReceipt(ns[i], r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(ns[i]));
        }
    }

    /// Shared vectors with the Go services (x402.EntriesRoot): the
    /// three-entry list of test-vectors/merkle-v1.json and a seven-entry list
    /// (nonce i + 1, leaf keccak256 of the byte i). The same roots are
    /// asserted in services/internal/x402/x402_test.go.
    function test_computeRootSharedVectors() public {
        AnchorMerkleHarness h = new AnchorMerkleHarness();
        FairBindMerkle.ReceiptEntry[] memory three = new FairBindMerkle.ReceiptEntry[](3);
        three[0] = FairBindMerkle.ReceiptEntry(
            bytes32(uint256(0x10)), 0xd0d879d3e6036e918857021e097d5a13b213974d6fcba3756efbd512d0ce1a27
        );
        three[1] = FairBindMerkle.ReceiptEntry(
            bytes32(uint256(0x30)), 0x9e19446555a83d5e12578fee5fdc10a13e1d57272f8fd65730f16cd65fb03caf
        );
        three[2] = FairBindMerkle.ReceiptEntry(
            bytes32(uint256(0x50)), 0xa92aa3c109a64b75827620efd7ec7aef1dbd7e02f6e8bd15df81a39b6e031a3b
        );
        require(
            h.computeRoot(three) == 0xb0e5ce6b84df6db5f7e3847d05560064b749bdc676f4ad8ff9338ca0a71bf28a,
            "merkle-v1.json root"
        );
        FairBindMerkle.ReceiptEntry[] memory seven = new FairBindMerkle.ReceiptEntry[](7);
        for (uint256 i; i < 7; i++) {
            seven[i] = FairBindMerkle.ReceiptEntry(bytes32(i + 1), keccak256(abi.encodePacked(uint8(i))));
        }
        require(
            h.computeRoot(seven) == 0x08cb9f67335b1ed71e5d9fec9415beb67e03f1064e97899b17d9cce31fba8f0f,
            "seven-entry root"
        );
        require(h.strictlyAscending(three) && h.strictlyAscending(seven), "vectors ascend");
    }

    // ------------------------------------------------- (b) length and order

    function test_anchorRevertsWhenListLengthDiffersFromCount() public {
        _deploy(_productionProfile());
        bytes32[] memory ns = _purchases(3);
        _buildTree(ns);
        FairBindMerkle.ReceiptEntry[] memory entries = _treeEntries();
        FairBindMerkle.ReceiptEntry[] memory shorter = new FairBindMerkle.ReceiptEntry[](2);
        shorter[0] = entries[0];
        shorter[1] = entries[1];
        FairBindMerkle.ReceiptEntry[] memory longer = new FairBindMerkle.ReceiptEntry[](4);
        for (uint256 i; i < 3; i++) longer[i] = entries[i];
        longer[3] = FairBindMerkle.ReceiptEntry(bytes32(type(uint256).max), keccak256("extra"));
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.CountMismatch.selector);
        fairbind.anchor(sellerId, 0, shorter, 3, keccak256("publication"));
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.CountMismatch.selector);
        fairbind.anchor(sellerId, 0, longer, 3, keccak256("publication"));
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.CountMismatch.selector);
        fairbind.anchor(sellerId, 0, new FairBindMerkle.ReceiptEntry[](0), 3, keccak256("publication"));
        // A list matching a wrong count still meets the purchase count check.
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.CountMismatch.selector);
        fairbind.anchor(sellerId, 0, shorter, 2, keccak256("publication"));
        require(fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.NONE), "not anchored");
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, entries, 3, keccak256("publication"));
        require(fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.ANCHORED), "anchored");
    }

    /// The nonces must increase strictly: a swapped pair, a repeated nonce and
    /// a descending list revert, and the sorted list is accepted.
    function test_anchorRevertsUnlessNoncesStrictlyAscend() public {
        _deploy(_productionProfile());
        bytes32[] memory ns = _purchases(3);
        _buildTree(ns);
        FairBindMerkle.ReceiptEntry[] memory sorted = _treeEntries();
        FairBindMerkle.ReceiptEntry[] memory swapped = _treeEntries();
        (swapped[1], swapped[2]) = (swapped[2], swapped[1]);
        FairBindMerkle.ReceiptEntry[] memory repeated = _treeEntries();
        repeated[2] = FairBindMerkle.ReceiptEntry(repeated[1].nonce, keccak256("second leaf at one nonce"));
        FairBindMerkle.ReceiptEntry[] memory descending = new FairBindMerkle.ReceiptEntry[](3);
        for (uint256 i; i < 3; i++) descending[i] = sorted[2 - i];
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.EntriesNotAscending.selector);
        fairbind.anchor(sellerId, 0, swapped, 3, keccak256("publication"));
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.EntriesNotAscending.selector);
        fairbind.anchor(sellerId, 0, repeated, 3, keccak256("publication"));
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.EntriesNotAscending.selector);
        fairbind.anchor(sellerId, 0, descending, 3, keccak256("publication"));
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, sorted, 3, keccak256("publication"));
        require(fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.ANCHORED), "anchored");
    }

    // ------------------------------------------------- (c) omission proofs

    /// The seller drops the middle purchase and keeps the count with a filler
    /// placed in order. The buyer's true proof fails, and a third party
    /// proves the omission from the purchase nonce and two adjacent list
    /// entries; no receipt or signature is used.
    function test_omittedReceiptIsProvenFromThePublishedList() public {
        _deploy(_productionProfile());
        bytes32[] memory ns = _purchases(3);
        bytes32 trueRoot = _buildTree(ns);
        bytes32 a = sortedNonces[0];
        bytes32 b = sortedNonces[1];
        bytes32 c = sortedNonces[2];
        FairBindMerkle.ReceiptEntry[] memory published = new FairBindMerkle.ReceiptEntry[](3);
        published[0] = _entryOf(a);
        published[1] = _entryOf(c);
        published[2] = FairBindMerkle.ReceiptEntry(bytes32(type(uint256).max), keccak256("filler"));
        _anchorList(published);
        bytes32 stored = fairbind.getAnchor(sellerId, 0).root;
        require(stored != trueRoot, "omission moves the root");
        FairBindCore.ReceiptProof memory trueProof = _proof(b);
        require(
            !FairBindMerkle.verify(
                stored, b, fairbind.receiptDigest(_receipt(b)), trueProof.index, trueProof.count, trueProof.siblings
            ),
            "true proof fails"
        );
        // Non-adjacent or non-bracketing pairs do not prove anything.
        uint8 interior = uint8(FairBindCore.ProofBoundary.INTERIOR);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        fairbind.proveOmission(b, published[0], _proofOf(published, 0), published[2], _proofOf(published, 2), interior);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        fairbind.proveOmission(c, published[0], _proofOf(published, 0), published[1], _proofOf(published, 1), interior);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        fairbind.proveOmission(a, published[0], _proofOf(published, 0), published[1], _proofOf(published, 1), interior);
        hv.prank(address(0xBEEF));
        fairbind.proveOmission(b, published[0], _proofOf(published, 0), published[1], _proofOf(published, 1), interior);
        require(
            fairbind.getPurchase(b).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE),
            "omitted purchase refundable"
        );
        require(fairbind.getCase(b).trigger == uint8(FairBindCore.CaseTrigger.OMISSION), "omission trigger");
    }

    /// Against the honest list no purchase admits an omission proof in any
    /// of the three forms, and an unknown nonce is rejected.
    function test_honestListAdmitsNoOmissionProof() public {
        _deploy(_productionProfile());
        bytes32[] memory ns = _purchases(4);
        _buildTree(ns);
        FairBindMerkle.ReceiptEntry[] memory list = _treeEntries();
        _anchorList(list);
        FairBindMerkle.ReceiptEntry memory none;
        FairBindCore.ReceiptProof memory noProof;
        for (uint256 o; o < 4; o++) {
            bytes32 n = list[o].nonce;
            for (uint256 i; i + 1 < 4; i++) {
                hv.expectRevert(FairBindCore.InvalidProof.selector);
                fairbind.proveOmission(
                    n, list[i], _proofOf(list, i), list[i + 1], _proofOf(list, i + 1),
                    uint8(FairBindCore.ProofBoundary.INTERIOR)
                );
            }
            hv.expectRevert(FairBindCore.InvalidProof.selector);
            fairbind.proveOmission(n, none, noProof, list[0], _proofOf(list, 0), uint8(FairBindCore.ProofBoundary.LOWER));
            hv.expectRevert(FairBindCore.InvalidProof.selector);
            fairbind.proveOmission(n, list[3], _proofOf(list, 3), none, noProof, uint8(FairBindCore.ProofBoundary.UPPER));
        }
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        fairbind.proveOmission(
            bytes32(uint256(list[0].nonce) - 1), none, noProof, list[0], _proofOf(list, 0),
            uint8(FairBindCore.ProofBoundary.LOWER)
        );
    }

    /// One-entry list: the single entry bounds an omitted purchase from
    /// above (LOWER, index 0) or from below (UPPER, last index 0).
    function test_singleEntryListBoundsOmissionOnBothSides() public {
        _deploy(_productionProfile());
        bytes32 n = _purchases(1)[0];
        FairBindMerkle.ReceiptEntry memory none;
        FairBindCore.ReceiptProof memory noProof;
        uint256 snap = av.snapshotState();
        FairBindMerkle.ReceiptEntry[] memory above = AnchorLeaves.pair(bytes32(uint256(n) + 1), keccak256("filler"));
        _anchorList(above);
        fairbind.proveOmission(n, none, noProof, above[0], _proofOf(above, 0), uint8(FairBindCore.ProofBoundary.LOWER));
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE), "lower");
        av.revertToState(snap);
        FairBindMerkle.ReceiptEntry[] memory below = AnchorLeaves.pair(bytes32(uint256(n) - 1), keccak256("filler"));
        _anchorList(below);
        fairbind.proveOmission(n, below[0], _proofOf(below, 0), none, noProof, uint8(FairBindCore.ProofBoundary.UPPER));
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE), "upper");
    }

    // ---------------------------------------- (d) a substituted receipt leaf

    /// A tampered entry moves the root, so the buyer's inclusion proof from
    /// the true list fails against the anchor.
    function test_tamperedEntryBreaksTheTrueInclusionProof() public {
        _deploy(_productionProfile());
        bytes32[] memory ns = _purchases(3);
        bytes32 trueRoot = _buildTree(ns);
        bytes32 b = sortedNonces[1];
        FairBindMerkle.ReceiptEntry[] memory tampered = _treeEntries();
        tampered[1].receiptLeaf = keccak256("another receipt");
        _anchorList(tampered);
        bytes32 stored = fairbind.getAnchor(sellerId, 0).root;
        require(stored == _anchorRoot(tampered), "root of the list sent");
        require(stored != trueRoot, "tampering moves the root");
        FairBindCore.ReceiptProof memory p = _proof(b);
        require(
            !FairBindMerkle.verify(stored, b, fairbind.receiptDigest(_receipt(b)), p.index, p.count, p.siblings),
            "true proof fails"
        );
    }

    /// The seller anchors another leaf at the buyer's nonce (J2). The buyer
    /// proves it with its signed receipt and the inclusion proof of the
    /// anchored entry at its nonce. The proof confirms a seller failure with
    /// the same effect as a double-signing proof on the same purchase.
    function test_misanchoredReceiptIsProvenByItsBuyer() public {
        hv.roll(1);
        _deploy(_productionProfile());
        bytes32[] memory ns = _purchases(3);
        _buildTree(ns);
        bytes32 b = sortedNonces[1];
        FairBindMerkle.ReceiptEntry[] memory tampered = _treeEntries();
        bytes32 otherLeaf = keccak256("another receipt");
        tampered[1].receiptLeaf = otherLeaf;
        _anchorList(tampered);
        FairBindCore.FairBindReceipt memory rb = _receipt(b);
        bytes32 digest = fairbind.receiptDigest(rb);
        bytes memory sb = _sig(SELLER_KEY, digest);
        bytes memory foreign = _sig(SELLER_KEY + 1, digest);
        // The leaf the buyer holds is not a substitution.
        FairBindCore.ReceiptProof memory atB = _proofOf(tampered, 1);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        fairbind.proveMisanchoredReceipt(rb, sb, digest, atB);
        // An entry of another nonce is not the entry at the buyer's nonce.
        FairBindCore.ReceiptProof memory atA = _proofOf(tampered, 0);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        fairbind.proveMisanchoredReceipt(rb, sb, tampered[0].receiptLeaf, atA);
        // A receipt the seller did not sign proves nothing.
        hv.expectRevert(FairBindCore.InvalidSignature.selector);
        fairbind.proveMisanchoredReceipt(rb, foreign, otherLeaf, atB);
        fairbind.proveMisanchoredReceipt(rb, sb, otherLeaf, atB);
        FairBindCore.PurchaseView memory pm = fairbind.getPurchase(b);
        uint8 triggerM = fairbind.getCase(b).trigger;
        uint8 statusM = fairbind.getSeller(sellerId).status;
        uint256 bondM = fairbind.getBond(fairbind.getSeller(sellerId).bondId).balance;
        require(pm.financialState == uint8(FairBindCore.FinancialState.REFUNDABLE), "refundable");
        require(triggerM == uint8(FairBindCore.CaseTrigger.EQUIVOCATION), "equivocation class");
        hv.expectRevert(FairBindCore.AlreadyFinalized.selector);
        fairbind.proveMisanchoredReceipt(rb, sb, otherLeaf, atB);

        // The same purchase position proven by two signed receipts instead.
        hv.roll(1);
        _deploy(_productionProfile());
        ns = _purchases(3);
        _buildTree(ns);
        b = sortedNonces[1];
        _anchorList(_treeEntries());
        rb = _receipt(b);
        FairBindCore.FairBindReceipt memory second = _receipt(b);
        second.responseHash = keccak256("another response");
        fairbind.proveEquivocation(
            rb, _sig(SELLER_KEY, fairbind.receiptDigest(rb)), second, _sig(SELLER_KEY, fairbind.receiptDigest(second))
        );
        require(fairbind.getPurchase(b).financialState == pm.financialState, "same financial state");
        require(fairbind.getCase(b).trigger == triggerM, "same trigger");
        require(fairbind.getSeller(sellerId).status == statusM, "same seller status");
        require(fairbind.getBond(fairbind.getSeller(sellerId).bondId).balance == bondM, "same bond");
    }

    // ---------------------------------------------------------------- (e) gas

    /// Anchors k entries on a fresh deployment and returns the call frame gas
    /// (lastCallGas), the call data gas under EIP-2028 (4 per zero byte, 16
    /// per nonzero byte) and the EIP-7623 tokens (zero bytes + 4 per nonzero
    /// byte). The purchase count is written to storage so that only anchor
    /// runs; the router's storage and the sampling module are cooled first,
    /// as at the start of a transaction. The nonces ascend (a 4-byte rank
    /// above 28 pseudo-random bytes) and the leaves are pseudo-random.
    /// Called through `this` so that the test's memory is released between lists.
    function measureAnchor(uint256 k) external returns (uint256 frame, uint256 dataGas, uint256 tokens) {
        hv.roll(1);
        _deploy(_productionProfile());
        bytes32 slot = keccak256(
            abi.encode(uint256(0), keccak256(abi.encode(uint256(sellerId), EPOCH_PURCHASE_COUNT_SLOT)))
        );
        av.store(address(fairbind), slot, bytes32(k));
        require(fairbind.epochPurchaseCount(sellerId, 0) == k, "count slot");
        FairBindMerkle.ReceiptEntry[] memory entries = new FairBindMerkle.ReceiptEntry[](k);
        for (uint256 i; i < k; i++) {
            uint256 rank = 0x01010101 + i;
            bytes32 nonce = bytes32((rank << 224) | (uint256(keccak256(abi.encode("gas probe nonce", i))) >> 32));
            entries[i] = FairBindMerkle.ReceiptEntry(nonce, keccak256(abi.encode("gas probe leaf", i)));
        }
        bytes memory data = abi.encodeWithSelector(
            FairBind.anchor.selector, sellerId, uint24(0), entries, uint32(k), keccak256("publication")
        );
        require(data.length == 196 + 64 * k, "64 bytes per entry");
        uint256 zeros;
        for (uint256 i; i < data.length; i++) if (data[i] == 0) zeros++;
        uint256 nonzeros = data.length - zeros;
        hv.roll(600);
        av.cool(address(fairbind));
        av.cool(fairbind.samplingModule());
        hv.prank(SELLER_OWNER);
        (bool ok,) = address(fairbind).call(data);
        require(ok, "anchor");
        frame = av.lastCallGas().gasTotalUsed;
        require(fairbind.getAnchor(sellerId, 0).root == _anchorRoot(entries), "root");
        dataGas = zeros * 4 + nonzeros * 16;
        tokens = zeros + nonzeros * 4;
        _log("anchor entries", k);
        _log("  call frame gas (lastCallGas.gasTotalUsed)", frame);
        _log("  calldata bytes", data.length);
        _log("  calldata zero bytes", zeros);
        _log("  calldata gas EIP-2028", dataGas);
        _log("  EIP-7623 tokens", tokens);
    }

    /// Transaction gas after EIP-7623: 21,000 plus the larger of the standard
    /// cost (call data gas and execution) and the floor of 10 per token.
    function _txGas(uint256 frame, uint256 dataGas, uint256 tokens) internal pure returns (uint256) {
        uint256 standard = dataGas + frame;
        uint256 floor = 10 * tokens;
        return 21_000 + (standard > floor ? standard : floor);
    }

    /// Anchor gas by list length: the call frame gas must stay within 5% of
    /// the recorded value (ADR 0026 table).
    function test_anchorGasByListLength() public {
        uint256[5] memory sizes = [uint256(1), 10, 100, 1000, 3245];
        uint256[5] memory recorded = [uint256(108_928), 113_949, 154_606, 563_890, 1_644_343];
        uint256[5] memory measured;
        for (uint256 s; s < sizes.length; s++) {
            (uint256 frame, uint256 dataGas, uint256 tokens) = this.measureAnchor(sizes[s]);
            _log("  transaction gas after EIP-7623", _txGas(frame, dataGas, tokens));
            measured[s] = frame;
        }
        for (uint256 s; s < sizes.length; s++) {
            require(measured[s] * 100 <= recorded[s] * 105, "frame gas above recorded + 5%");
            require(measured[s] * 100 >= recorded[s] * 95, "frame gas below recorded - 5%");
        }
    }

    /// The largest list one anchor transaction holds (ADR 0026, limit 4): n
    /// entries fit a transaction gas limit and n + 1 do not, for 30,000,000
    /// and for 16,777,216 (EIP-7825). Above n a seller cannot anchor.
    function test_anchorEntryLimitPerTransaction() public {
        uint256[2] memory limits = [uint256(30_000_000), 16_777_216];
        uint256[2] memory maxEntries = [uint256(MAX_ENTRIES_30M), MAX_ENTRIES_16M];
        for (uint256 j; j < 2; j++) {
            (uint256 f, uint256 d, uint256 t) = this.measureAnchor(maxEntries[j]);
            uint256 fits = _txGas(f, d, t);
            (f, d, t) = this.measureAnchor(maxEntries[j] + 1);
            uint256 over = _txGas(f, d, t);
            _log("  limit", limits[j]);
            _log("  transaction gas at the largest list", fits);
            _log("  transaction gas at one entry more", over);
            require(fits <= limits[j], "largest list fits");
            require(over > limits[j], "one more entry does not fit");
        }
    }

    uint256 internal constant MAX_ENTRIES_30M = 11_742;
    uint256 internal constant MAX_ENTRIES_16M = 6_562;
}
