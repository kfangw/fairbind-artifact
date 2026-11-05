// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindCommitReveal } from "../src/randomness/FairBindCommitReveal.sol";
import { BlockhashRandomness } from "../src/randomness/BlockhashRandomness.sol";
import { IRandomness } from "../src/randomness/IRandomness.sol";
import { ReproBase } from "./repro/ReproBase.sol";

/// Commit-reveal sampling value (journal J2, rule D2-16 with a source behind
/// IRandomness). Epoch 0 of the base profile has its anchor deadline A = 700.
contract J2RandomnessTest is ReproBase {
    uint64 internal constant A = 700;
    uint32 internal constant R = 100;
    uint256 internal constant PEN = 1 ether;
    address internal constant ALICE = address(0xA11CE1);
    address internal constant BOB = address(0xB0B);
    address internal constant CAROL = address(0xCA201);
    bytes32 internal constant S_A = keccak256("secret alice");
    bytes32 internal constant S_B = keccak256("secret bob");
    bytes32 internal constant S_C = keccak256("secret carol");

    FairBindCommitReveal internal cr;

    function _deal(address who) internal {
        (bool ok,) = address(hv).call(abi.encodeWithSignature("deal(address,uint256)", who, 10 ether));
        require(ok, "deal");
    }

    function _setUpWith(uint32 samplePpm, uint32 window) internal {
        _deploy(_baseProductionWith(samplePpm));
        cr = new FairBindCommitReveal(window, PEN, TREASURY);
        fairbind.setRandomness(address(cr));
        _deal(ALICE);
        _deal(BOB);
        _deal(CAROL);
    }

    function _baseProductionWith(uint32 samplePpm) internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _productionProfile();
        p.samplePpm = samplePpm;
        p.recheckPpm = 0;
    }

    function _commit(FairBindCommitReveal c, address who, bytes32 secret) internal {
        bytes32 h = c.commitmentOf(A, who, secret);
        hv.prank(who);
        c.commit{ value: PEN }(A, h);
    }

    function _reveal(FairBindCommitReveal c, address who, bytes32 secret) internal {
        hv.prank(who);
        c.reveal(A, secret);
    }

    function _purchases(uint256 count) internal returns (bytes32[] memory ns) {
        hv.roll(10);
        ns = new bytes32[](count);
        for (uint256 i; i < count; i++) ns[i] = _purchase(10_000);
    }

    function _anchor(bytes32[] memory ns) internal {
        _buildTree(ns);
        hv.roll(650);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), uint32(ns.length), keccak256("publication"));
    }

    function _expected(bytes32 mix, uint32 reveals) internal pure returns (bytes32) {
        return keccak256(abi.encode(keccak256("fairbind/commit-reveal/v1"), uint64(A), mix, reveals));
    }

    // ---------------------------------------------------------- happy path

    /// Three commit, all reveal: the sampling value is the hash of the XOR of
    /// the secrets, the epoch seals with it, and every deposit is refunded.
    function test_commitRevealHappyPath() public {
        _setUpWith(500_000, R);
        bytes32[] memory ns = _purchases(8);
        _anchor(ns);
        require(fairbind.getAnchor(sellerId, 0).randomBlock == A + 1 + R, "randomBlock uses the reveal window");
        _commit(cr, ALICE, S_A);
        _commit(cr, BOB, S_B);
        _commit(cr, CAROL, S_C);
        hv.roll(A + 1);
        _reveal(cr, ALICE, S_A);
        _reveal(cr, BOB, S_B);
        _reveal(cr, CAROL, S_C);
        (bool ready,) = cr.valueOf(A);
        require(!ready, "no value inside the reveal window");
        hv.roll(A + R + 2);
        bytes32 want = _expected(S_A ^ S_B ^ S_C, 3);
        (bool ok, bytes32 v) = cr.valueOf(A);
        require(ok && v == want, "value");
        fairbind.seal(sellerId, 0);
        FairBindCore.AnchorView memory rec = fairbind.getAnchor(sellerId, 0);
        require(rec.state == uint8(FairBindCore.EpochState.SEALED) && rec.randomness == want, "sealed with the value");
        require(address(cr).balance == 0, "all deposits refunded");
        // The draw of every purchase follows the value (sampling predicate copy).
        FairBindCore.ServiceProfileInput memory p = fairbind.getServiceProfile(PROFILE).parameters;
        uint256 sampled;
        for (uint256 i; i < ns.length; i++) {
            (bool eligible, bool known) = fairbind.isSampled(ns[i]);
            require(known, "known");
            require(eligible == _sampledCopy(want, sellerId, 0, ns[i], p.samplePpm), "draw follows the value");
            if (eligible) sampled++;
        }
        require(sampled != 0 && sampled != ns.length, "a partial sample, so the check has content");
    }

    // ---------------------------------------------------------- non-reveal

    /// Carol commits and does not reveal: her commit is dropped from the value
    /// and her deposit is forfeited to the treasury; the others are refunded.
    function test_nonRevealIsDroppedAndPenalised() public {
        _setUpWith(500_000, R);
        _commit(cr, ALICE, S_A);
        _commit(cr, BOB, S_B);
        _commit(cr, CAROL, S_C);
        hv.roll(A + 1);
        _reveal(cr, ALICE, S_A);
        _reveal(cr, BOB, S_B);
        hv.roll(A + R); // the last block of the window
        try cr.forfeit(A, CAROL) { revert("forfeit inside the window"); } catch { }
        hv.roll(A + R + 1);
        uint256 treasuryBefore = TREASURY.balance;
        cr.forfeit(A, CAROL);
        require(TREASURY.balance - treasuryBefore == PEN, "penalty to the treasury");
        (bool ok, bytes32 v) = cr.valueOf(A);
        require(ok && v == _expected(S_A ^ S_B, 2), "value excludes the non-revealer");
        (, uint8 status) = cr.commits(A, CAROL);
        require(status == 3, "forfeited");
        try cr.forfeit(A, CAROL) { revert("double forfeit"); } catch { }
        try cr.forfeit(A, ALICE) { revert("revealed commit cannot be forfeited"); } catch { }
    }

    /// A reveal after the window is rejected and the commit is then forfeited.
    function test_lateRevealRejected() public {
        _setUpWith(500_000, R);
        _commit(cr, ALICE, S_A);
        _commit(cr, BOB, S_B);
        hv.roll(A); // still the commit window: reveal not open
        hv.expectRevert(FairBindCommitReveal.RevealNotOpen.selector);
        _reveal(cr, ALICE, S_A);
        hv.roll(A + R);
        _reveal(cr, ALICE, S_A); // last block of the window is accepted
        hv.roll(A + R + 1);
        hv.expectRevert(FairBindCommitReveal.RevealClosed.selector);
        _reveal(cr, BOB, S_B);
        cr.forfeit(A, BOB);
        (bool ok, bytes32 v) = cr.valueOf(A);
        require(ok && v == _expected(S_A, 1), "late revealer is not in the value");
    }

    function test_commitAfterDeadlineAndBadRevealRejected() public {
        _setUpWith(500_000, R);
        _commit(cr, ALICE, S_A);
        hv.roll(A + 1);
        bytes32 h = cr.commitmentOf(A, BOB, S_B);
        hv.expectRevert(FairBindCommitReveal.CommitClosed.selector);
        hv.prank(BOB);
        cr.commit{ value: PEN }(A, h);
        hv.expectRevert(FairBindCommitReveal.BadSecret.selector);
        _reveal(cr, ALICE, S_B);
        // A commitment is bound to its sender: Bob cannot reveal Alice's.
        hv.expectRevert(FairBindCommitReveal.NotCommitted.selector);
        _reveal(cr, BOB, S_A);
    }

    // --------------------------------------------------------- determinism

    /// The value depends on the set of revealed secrets only, not on the order
    /// of the reveals, the number of callers or who delivers it; the draw of a
    /// purchase from it is a pure function of the value.
    function test_valueIsDeterministicGivenReveals() public {
        _setUpWith(500_000, R);
        FairBindCommitReveal cr2 = new FairBindCommitReveal(R, PEN, TREASURY);
        _commit(cr, ALICE, S_A);
        _commit(cr, BOB, S_B);
        _commit(cr, CAROL, S_C);
        _commit(cr2, CAROL, S_C);
        _commit(cr2, BOB, S_B);
        _commit(cr2, ALICE, S_A);
        hv.roll(A + 1);
        _reveal(cr, ALICE, S_A);
        _reveal(cr, BOB, S_B);
        _reveal(cr, CAROL, S_C);
        _reveal(cr2, CAROL, S_C);
        _reveal(cr2, BOB, S_B);
        _reveal(cr2, ALICE, S_A);
        hv.roll(A + R + 2);
        (, bytes32 v1) = cr.valueOf(A);
        (, bytes32 v2) = cr2.valueOf(A);
        require(v1 == v2 && v1 == _expected(S_A ^ S_B ^ S_C, 3), "order-independent");
        // A different reveal set gives a different value.
        require(v1 != _expected(S_A ^ S_B, 2), "set-dependent");
    }

    // ------------------------------------------------------ zero reveals

    /// No reveal: the round has no value until finalize fixes the documented
    /// fallback, the hash of block A + R + 1; the epoch then seals, and the
    /// deposits are forfeited.
    function test_zeroRevealsFallBackToTheBlockHash() public {
        _setUpWith(500_000, R);
        bytes32[] memory ns = _purchases(4);
        _anchor(ns);
        _commit(cr, ALICE, S_A);
        hv.roll(A + R + 2);
        (bool ready,) = cr.valueOf(A);
        require(!ready, "no value before finalize");
        try fairbind.seal(sellerId, 0) { revert("seal without value"); } catch { }
        bytes32 fixedHash = keccak256("hash of A+R+1");
        hv.setBlockhash(A + R + 1, fixedHash);
        cr.finalize(A);
        bytes32 want = keccak256(abi.encode(cr.DOMAIN(), uint64(A), fixedHash));
        (bool ok, bytes32 v) = cr.valueOf(A);
        require(ok && v == want, "fallback value");
        require(v != bytes32(0), "nonzero");
        (,,, bool used,,) = cr.rounds(A);
        require(used, "flagged");
        fairbind.seal(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).randomness == want, "sealed with the fallback");
        cr.forfeit(A, ALICE);
        try cr.finalize(A) { revert("finalize twice"); } catch { }
    }

    // ------------------------------------------------- the interface seam

    /// With no source set the prototype's block hash path runs unchanged; the
    /// BlockhashRandomness adapter returns the same value through IRandomness.
    function test_blockhashAdapterMatchesTheBuiltInPath() public {
        _deploy(_baseProductionWith(500_000));
        BlockhashRandomness adapter = new BlockhashRandomness(TEST_BEACON_DELAY());
        bytes32[] memory ns = _purchases(2);
        _anchor(ns);
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        (bool ok, bytes32 v) = adapter.valueOf(A);
        require(ok && v == keccak256("beacon"), "adapter value");
        fairbind.seal(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).randomness == v, "built-in path equals the adapter");
    }

    function TEST_BEACON_DELAY() internal pure returns (uint32) {
        return uint32(BEACON_BLOCK - A - 1);
    }

    function test_sourceMustFitTheProfileDelay() public {
        _deploy(_baseProductionWith(500_000));
        FairBindCommitReveal slow = new FairBindCommitReveal(TEST_BEACON_DELAY() + 1, PEN, TREASURY);
        fairbind.setRandomness(address(slow));
        bytes32[] memory ns = _purchases(1);
        _buildTree(ns);
        hv.roll(650);
        hv.expectRevert(FairBindCore.InvalidConfiguration.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 1, keccak256("publication"));
    }

    function test_setRandomnessOnceAndOnlyByGovernance() public {
        _deploy(_baseProductionWith(500_000));
        FairBindCommitReveal c = new FairBindCommitReveal(R, PEN, TREASURY);
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        hv.prank(ALICE);
        fairbind.setRandomness(address(c));
        fairbind.setRandomness(address(c));
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.setRandomness(address(c));
        (address src,) = fairbind.getRandomness();
        require(src == address(c), "recorded");
    }

    /// An epoch anchored before the source was set keeps the block hash path.
    function test_epochAnchoredBeforeActivationKeepsTheBlockhashPath() public {
        _deploy(_baseProductionWith(500_000));
        bytes32[] memory ns = _purchases(2);
        _anchor(ns);
        FairBindCommitReveal c = new FairBindCommitReveal(R, PEN, TREASURY);
        fairbind.setRandomness(address(c));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).randomness == keccak256("beacon"), "old path");
    }
}
