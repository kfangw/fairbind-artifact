// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../../src/FairBindCore.sol";
import { ReproBase } from "./ReproBase.sol";

/// Test-only model of an alternative ordering in which the seller chooses the
/// committed receipt set after the sampling beacon is known, and sampling runs
/// over the committed set. It exists only in this test harness.
contract LateCommitHarness {
    uint256 internal constant PPM = 1_000_000;

    function sampled(bytes32 randomness, uint32 seller, uint24 epoch, bytes32 nonce, uint32 ppm)
        public
        pure
        returns (bool)
    {
        if (ppm == PPM) return true;
        if (ppm == 0) return false;
        uint256 value = uint256(
            keccak256(abi.encode(keccak256("fairbind/sample/v1"), randomness, seller, epoch, nonce))
        );
        uint256 quotient = type(uint256).max / PPM;
        uint256 remainder = type(uint256).max % PPM;
        return value < quotient * ppm + ((remainder + 1) * ppm) / PPM;
    }

    /// Seller strategy under the late-commit rule: include only receipts the
    /// known beacon does not sample. Returns how many included receipts are
    /// then sampled (judged).
    function judgedUnderLateCommit(
        bytes32 beacon,
        uint32 seller,
        uint24 epoch,
        bytes32[] calldata ledger,
        uint32 ppm
    ) external pure returns (uint256 judged, uint256 excluded) {
        for (uint256 i; i < ledger.length; i++) {
            if (sampled(beacon, seller, epoch, ledger[i], ppm)) {
                excluded++;
                continue;
            }
            // Included receipt; sampling runs over the committed set only.
            if (sampled(beacon, seller, epoch, ledger[i], ppm)) judged++;
        }
    }

    /// Current rule: the commitment count is fixed to the ledger before the
    /// beacon, and sampling runs over ledger nonces, so every sampled nonce is
    /// judged whether or not its receipt was committed.
    function judgedUnderLedgerSampling(
        bytes32 beacon,
        uint32 seller,
        uint24 epoch,
        bytes32[] calldata ledger,
        uint32 ppm
    ) external pure returns (uint256 judged) {
        for (uint256 i; i < ledger.length; i++) {
            if (sampled(beacon, seller, epoch, ledger[i], ppm)) judged++;
        }
    }
}

/// Case D: randomness ordering.
contract ReproD_RandomnessOrdering is ReproBase {
    uint256 internal constant G = 10_000;
    uint256 internal constant N = 8;

    function _profileD() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _baseProfile();
        p.samplePpm = 500_000;
    }

    /// D1: anchor fixed before the beacon, ledger-nonce sampling, seller
    /// withholds every receipt. The seller never signs a receipt.
    function test_D1_withheldReceiptsCannotEscapeLedgerSampling() public {
        _deploy(_profileD());
        bytes32[] memory ns = new bytes32[](N);
        for (uint256 i; i < N; i++) ns[i] = _purchase(G);

        hv.roll(600);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.CountMismatch.selector);
        fairbind.anchor(sellerId, 0, _filledEntries(keccak256("root without receipts"), N - 1), uint32(N - 1), keccak256("pub"));
        _logStr("D1 anchor with count N-1 reverted CountMismatch");
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _filledEntries(keccak256("root without receipts"), N), uint32(N), keccak256("pub"));
        _logStr("D1 anchor with count N and a root holding no real receipt accepted");

        bytes32 beacon = keccak256("epoch randomness d1");
        // The beacon is no longer the block after the anchor deadline: sealing
        // there is too early, and that block's hash is never read.
        hv.roll(702);
        hv.setBlockhash(701, keccak256("pre-delay beacon"));
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.seal(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).randomBlock == BEACON_BLOCK, "D1 delayed beacon block");
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, beacon);
        fairbind.seal(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).randomness == beacon, "D1 beacon");

        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.anchor(sellerId, 0, _filledEntries(keccak256("second root"), N), uint32(N), keccak256("pub2"));
        _logStr("D1 re-anchor after seal reverted InvalidTransition");

        uint256 sampledCount;
        uint256 mismatches;
        uint256 escaped;
        uint256 failed;
        hv.roll(BEACON_BLOCK + 10);
        for (uint256 i; i < N; i++) {
            (bool e,) = fairbind.isSampled(ns[i]);
            if (e != _sampledCopy(beacon, sellerId, 0, ns[i], 500_000)) mismatches++;
            if (!e) continue;
            sampledCount++;
            fairbind.openSample(ns[i]);
            // The assigned verifier has no receipt to judge and asks the seller to serve.
            fairbind.requestServe(ns[i]);
        }
        hv.roll(BEACON_BLOCK + 10 + 300 + 1);
        for (uint256 i; i < N; i++) {
            (bool e,) = fairbind.isSampled(ns[i]);
            if (!e) continue;
            fairbind.timeoutServe(ns[i]);
            FairBindCore.CaseView memory c = fairbind.getCase(ns[i]);
            FairBindCore.PurchaseView memory pv = fairbind.getPurchase(ns[i]);
            if (
                c.state == uint8(FairBindCore.CaseState.UNSERVED)
                    && pv.financialState == uint8(FairBindCore.FinancialState.REFUNDABLE)
            ) failed++;
            else escaped++;
        }
        _log("D1 ledger purchases", N);
        _log("D1 sampled (contract)", sampledCount);
        _log("D1 predicate copy mismatches", mismatches);
        _log("D1 sampled cases ending UNSERVED+REFUNDABLE", failed);
        _log("D1 sampled cases escaping", escaped);
        _log("D1 seller status (3=SANCTIONED)", fairbind.getSeller(sellerId).status);
        require(sampledCount > 0, "D1 precondition: at least one sample");
        require(mismatches == 0, "D1 predicate copy");
        require(escaped == 0 && failed == sampledCount, "D1 no escape");
    }

    /// D1 variant: the seller does not anchor at all.
    function test_D1b_noAnchorFailsWholeEpoch() public {
        _deploy(_profileD());
        bytes32[] memory ns = new bytes32[](N);
        for (uint256 i; i < N; i++) ns[i] = _purchase(G);
        hv.roll(701);
        fairbind.timeoutAnchor(sellerId, 0);
        uint256 refundable;
        for (uint256 i; i < N; i++) {
            fairbind.claimEpochFailure(ns[i]);
            if (fairbind.getPurchase(ns[i]).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE)) {
                refundable++;
            }
        }
        _log("D1b epoch state (3=EPOCH_FAILED)", fairbind.getAnchor(sellerId, 0).state);
        _log("D1b purchases refundable", refundable);
        _log("D1b purchases escaping", N - refundable);
        require(refundable == N, "D1b all refundable");
    }

    /// D2: same ledgers and beacons under the current rule and under the
    /// hypothetical late-commit rule.
    function test_D2_lateCommitLetsSellerExcludeEverySample() public {
        LateCommitHarness h = new LateCommitHarness();
        uint256 ledgerSize = 64;
        uint256 beacons = 32;
        uint32 ppm = 500_000;
        bytes32[] memory ledger = new bytes32[](ledgerSize);
        for (uint256 i; i < ledgerSize; i++) ledger[i] = keccak256(abi.encode("ledger nonce", i));
        uint256 totalSampled;
        uint256 judgedCurrent;
        uint256 judgedLate;
        uint256 excludedLate;
        for (uint256 j; j < beacons; j++) {
            bytes32 beacon = keccak256(abi.encode("beacon", j));
            uint256 s = h.judgedUnderLedgerSampling(beacon, 1, 0, ledger, ppm);
            (uint256 jl, uint256 ex) = h.judgedUnderLateCommit(beacon, 1, 0, ledger, ppm);
            totalSampled += s;
            judgedCurrent += s;
            judgedLate += jl;
            excludedLate += ex;
            for (uint256 i; i < ledgerSize; i++) {
                require(
                    h.sampled(beacon, 1, 0, ledger[i], ppm) == _sampledCopy(beacon, 1, 0, ledger[i], ppm),
                    "D2 predicate copy"
                );
            }
        }
        _log("D2 ledger size", ledgerSize);
        _log("D2 beacons", beacons);
        _log("D2 total sampled nonces (sum |S_j|)", totalSampled);
        _log("D2 current rule: judged", judgedCurrent);
        _log("D2 current rule: escaped", totalSampled - judgedCurrent);
        _log("D2 late-commit rule: judged", judgedLate);
        _log("D2 late-commit rule: excluded (escaped)", excludedLate);
        require(judgedLate == 0, "D2 late commit never judged");
        require(excludedLate == totalSampled, "D2 every sample excluded");
        require(judgedCurrent == totalSampled && totalSampled > 0, "D2 current rule judges all");
    }
}
