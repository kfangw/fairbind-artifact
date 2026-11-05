// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBase } from "./SdkBase.sol";
import { SampledSettlement, SettlementBase, Receipt, Leaf, Unit, Opening } from "./SampledSettlement.sol";

/// The sample value over Chainlink VRF v2.5 (VRFCoordinatorV2_5Mock): one
/// request per profile epoch after A_e and until M_e, for a complete anchor;
/// the request input binds the chain, the contract, the profile, the epoch
/// and the anchor commitment; the callback only from the coordinator, only
/// for a known request fulfilled by M_e, only once; the subscription owned
/// by the settlement contract; labels U_n = H(R_e || nonce_n) / 2^256 and a
/// sale sampled when U_n < v_n / V.
contract VrfCasesTest is SdkBase {
    address internal stranger = address(0xBAD);

    /// n sales of `amount` in the current epoch of pid, anchored in one unit.
    function _epochOf(bytes32 pid, uint256 n, uint64 amount) internal returns (Leaf[] memory ls) {
        return _epochOf(pid, n, amount, 0);
    }

    function _epochOf(bytes32 pid, uint256 n, uint64 amount, uint256 off) internal returns (Leaf[] memory ls) {
        ls = new Leaf[](n);
        for (uint256 i; i < n; i++) ls[i].rs = _buy(pid, _rs(pid, off + i, amount), off + i);
        _anchor(pid, ls);
    }

    function _input(bytes32 pid, uint256 ep) internal view returns (bytes32) {
        return keccak256(
            abi.encode(f.VRF_TAG(), block.chainid, address(f), pid, ep, m.anchorCommitment(pid, ep))
        );
    }

    /// U_n < v / V computed apart from the contract: floor(h * V / 2^256) < v
    /// with h split into 128-bit halves (V < 2^64).
    function _label(uint256 value, bytes32 nonce, uint64 v, uint64 cap) internal pure returns (bool) {
        if (value == 0 || v >= cap) return true;
        uint256 h = uint256(keccak256(abi.encode(value, nonce)));
        uint256 hi = h >> 128;
        uint256 lo = h & type(uint128).max;
        uint256 top = (hi * cap + ((lo * cap) >> 128)) >> 128;
        return top < v;
    }

    // ------------------------------------------------------------ request

    function test_V1_requestOnlyAfterAnchorDeadline() public {
        _epochOf(pidP, 2, PRICE);
        vm.roll(f.anchorDeadline(epoch));
        vm.expectRevert(SettlementBase.Timing.selector);
        m.requestSample(pidP, epoch);
        vm.roll(f.anchorDeadline(epoch) + 1);
        uint256 id = m.requestSample(pidP, epoch);
        require(id != 0 && f.sampleInput(_ek(pidP, epoch)) == _input(pidP, epoch), "request at A_e + 1");
        SettlementBase.VrfReq memory r = m.vrfRequest(id);
        require(r.pid == pidP && r.epoch == epoch && r.deadline == f.valueDeadline(epoch), "request record");
    }

    function test_V2_requestDuringTheEpochReverts() public {
        Leaf[] memory ls = new Leaf[](1);
        ls[0].rs = _buy(pidP, _rs(pidP, 0, PRICE), 0);
        vm.expectRevert(SettlementBase.Timing.selector);
        m.requestSample(pidP, epoch); // the epoch is still open
        _anchor(pidP, ls);
        vm.expectRevert(SettlementBase.Timing.selector);
        m.requestSample(pidP, epoch); // anchored, before A_e
    }

    function test_V3_requestAfterValueDeadlineReverts() public {
        _epochOf(pidP, 1, PRICE);
        vm.roll(f.valueDeadline(epoch) + 1);
        vm.expectRevert(SettlementBase.Timing.selector);
        m.requestSample(pidP, epoch);
    }

    function test_V4_requestNeedsACompleteAnchor() public {
        _buy(pidP, _rs(pidP, 0, PRICE), 0); // settled, never anchored
        vm.roll(f.anchorDeadline(epoch) + 1);
        vm.expectRevert(SettlementBase.State.selector);
        m.requestSample(pidP, epoch);
        vm.expectRevert(SettlementBase.State.selector);
        m.requestSample(pidC, epoch); // no settlement: no value needed
    }

    /// No repeated input: one request per profile epoch; a second request,
    /// before or after the value, by anyone, reverts.
    function test_V5_noSecondRequest() public {
        _epochOf(pidP, 2, PRICE);
        uint256 id = _requestSample(pidP, epoch);
        vm.prank(seller);
        vm.expectRevert(SettlementBase.State.selector);
        m.requestSample(pidP, epoch);
        _fulfill(id, 7);
        vm.prank(stranger);
        vm.expectRevert(SettlementBase.State.selector);
        m.requestSample(pidP, epoch);
    }

    /// Inputs of different profile epochs differ: other profile, same epoch;
    /// same profile, next epoch. The coordinator's request ids differ too.
    function test_V6_inputsNeverRepeat() public {
        uint256 e = epoch;
        Leaf[] memory a = new Leaf[](1);
        a[0].rs = _buy(pidP, _rs(pidP, 0, PRICE), 0);
        Leaf[] memory b = new Leaf[](1);
        b[0].rs = _buy(pidC, _rs(pidC, 0, PRICE), 0);
        _sort(a);
        _sort(b);
        Unit memory ua = _unit(pidP, a);
        Unit memory ub = _unit(pidC, b);
        _toAnchor();
        require(f.anchorUnit(ua) == 0 && f.anchorUnit(ub) == 0, "anchors");
        uint256 id1 = _requestSample(pidP, e);
        uint256 id2 = m.requestSample(pidC, e);
        epoch = e + 1; // the head (A_e + 1) lies in epoch e + 1
        require(f.epochOf(block.number) == e + 1, "next epoch");
        _epochOf(pidP, 1, PRICE, 100);
        uint256 id3 = _requestSample(pidP, e + 1);
        bytes32 i1 = f.sampleInput(_ek(pidP, e));
        bytes32 i2 = f.sampleInput(_ek(pidC, e));
        bytes32 i3 = f.sampleInput(_ek(pidP, e + 1));
        require(i1 != i2 && i1 != i3 && i2 != i3, "distinct inputs");
        require(id1 != id2 && id1 != id3 && id2 != id3, "distinct request ids");
        require(i1 == _input(pidP, e) && i3 == _input(pidP, e + 1), "input formula");
        require(m.anchorCommitment(pidP, e) == keccak256(abi.encode(bytes32(0), ua.root)), "anchor commitment");
    }

    // --------------------------------------------------------- fulfillment

    function test_V7_fulfillmentOnlyFromTheCoordinator() public {
        _epochOf(pidP, 2, PRICE);
        uint256 id = _requestSample(pidP, epoch);
        uint256[] memory ws = new uint256[](1);
        ws[0] = 42;
        vm.prank(stranger);
        vm.expectRevert(SettlementBase.Unauthorized.selector);
        m.rawFulfillRandomWords(id, ws);
        vm.prank(seller);
        vm.expectRevert(SettlementBase.Unauthorized.selector);
        m.rawFulfillRandomWords(id, ws);
        require(f.sampleValue(_ek(pidP, epoch)) == 0, "no value from others");
        _fulfill(id, 42); // the coordinator's callback
        require(f.sampleValue(_ek(pidP, epoch)) == _valueOf(pidP, epoch, id, 42), "value from the coordinator");
    }

    function test_V8_valueIsDerivedFromInputRequestAndWord() public {
        _epochOf(pidP, 2, PRICE);
        uint256 id = _requestSample(pidP, epoch);
        _fulfill(id, 123_456);
        uint256 want = uint256(keccak256(abi.encode(_input(pidP, epoch), id, uint256(123_456))));
        require(f.sampleValue(_ek(pidP, epoch)) == want, "R_e = H(input, request id, word)");
    }

    /// A second fulfillment (the coordinator calling again with another
    /// word) leaves the value unchanged; so does a callback for an unknown
    /// request id.
    function test_V9_firstValueOnly() public {
        _epochOf(pidP, 2, PRICE);
        uint256 id = _requestSample(pidP, epoch);
        _fulfill(id, 1);
        uint256 v = f.sampleValue(_ek(pidP, epoch));
        uint256[] memory ws = new uint256[](1);
        ws[0] = 2;
        vm.prank(address(vrf));
        m.rawFulfillRandomWords(id, ws);
        require(f.sampleValue(_ek(pidP, epoch)) == v, "first value kept");
        vm.prank(address(vrf));
        m.rawFulfillRandomWords(id + 1000, ws);
        require(f.sampleValue(_ek(pidP, epoch)) == v, "unknown id ignored");
    }

    /// A fulfillment after M_e gives no value: every sale stays sampled.
    function test_V10_lateFulfillmentIgnored() public {
        Leaf[] memory ls = _epochOf(pidP, 4, PRICE);
        uint256 id = _requestSample(pidP, epoch);
        vm.roll(f.valueDeadline(epoch) + 1);
        _fulfill(id, 9);
        require(f.sampleValue(_ek(pidP, epoch)) == 0, "late value ignored");
        for (uint256 i; i < ls.length; i++) require(f.isSampled(pidP, ls[i].rs.nonce), "all sampled");
    }

    /// A fulfillment at M_e still counts.
    function test_V11_fulfillmentAtValueDeadline() public {
        _epochOf(pidP, 1, PRICE);
        uint256 id = _requestSample(pidP, epoch);
        vm.roll(f.valueDeadline(epoch));
        _fulfill(id, 9);
        require(f.sampleValue(_ek(pidP, epoch)) != 0, "value at M_e");
    }

    /// No fulfillment at all: after M_e every sale is sampled.
    function test_V12_noValueEverySaleSampled() public {
        Leaf[] memory ls = _epochOf(pidP, 4, PRICE);
        _requestSample(pidP, epoch);
        vm.roll(f.valueDeadline(epoch) + 1);
        for (uint256 i; i < ls.length; i++) require(f.isSampled(pidP, ls[i].rs.nonce), "all sampled");
    }

    // -------------------------------------------------------------- labels

    /// Labels as the rule specifies: U_n = H(R_e || nonce_n) / 2^256, sampled
    /// when U_n < v_n / V; 24 sales at v = V / 2 give both outcomes.
    function test_V13_labelsAsSpecified() public {
        uint64 half = CAP / 2;
        Leaf[] memory ls = _epochOf(pidP, 24, half);
        uint256 id = _requestSample(pidP, epoch);
        _fulfill(id, 2026);
        uint256 R = f.sampleValue(_ek(pidP, epoch));
        uint256 ins;
        for (uint256 i; i < ls.length; i++) {
            bool want = _label(R, ls[i].rs.nonce, half, CAP);
            require(f.isSampled(pidP, ls[i].rs.nonce) == want, "label");
            if (want) ins++;
        }
        require(ins > 0 && ins < ls.length, "both outcomes");
    }

    function testFuzz_V14_labels(uint256 word, bytes32 nonce, uint64 v) public {
        v = uint64(bound(v, 1, CAP));
        _epochOf(pidP, 1, PRICE);
        uint256 id = _requestSample(pidP, epoch);
        uint256 R = _valueOf(pidP, epoch, id, word);
        require(f.sampledBy(R, nonce, v, CAP) == _label(R, nonce, v, CAP), "sampledBy");
        _fulfill(id, word);
        require(f.sampleValue(_ek(pidP, epoch)) == R, "stored");
    }

    function bound(uint256 x, uint256 lo, uint256 hi) internal pure returns (uint256) {
        return lo + x % (hi - lo + 1);
    }

    /// With a value, a sampled sale is provable before M_e and an unsampled
    /// one is not (NotSampled); the value arrived after the anchor was fixed.
    function test_V15_proofWindowOpensWithTheValue() public {
        uint64 half = CAP / 2;
        Leaf[] memory ls = _epochOf(pidP, 16, half);
        uint256 id = _requestSample(pidP, epoch);
        _fulfill(id, 5);
        require(block.number < f.valueDeadline(epoch), "before M_e");
        for (uint256 i; i < ls.length; i++) {
            if (!f.isSampled(pidP, ls[i].rs.nonce)) {
                Opening memory o = _opening(pidP, ls, i);
                vm.expectRevert(SettlementBase.NotSampled.selector);
                f.prove(o, "");
                return;
            }
        }
        revert("no unsampled sale");
    }

    // ----------------------------------------------------- adversarial seller

    /// The subscription belongs to the settlement contract: the seller (or
    /// anyone) can neither cancel it, move it, nor remove the consumer, so
    /// it cannot cancel a request and reissue one for another value.
    function test_V16_subscriptionOwnedByTheContract() public {
        uint256 sub = f.vrfSubId();
        (,,, address owner, address[] memory consumers) = vrf.getSubscription(sub);
        require(owner == address(f) && consumers.length == 1 && consumers[0] == address(f), "owner and consumer");
        vm.prank(seller);
        vm.expectRevert();
        vrf.cancelSubscription(sub, seller);
        vm.prank(seller);
        vm.expectRevert();
        vrf.removeConsumer(sub, address(f));
        vm.prank(seller);
        vm.expectRevert();
        vrf.requestSubscriptionOwnerTransfer(sub, seller);
    }

    /// A seller that sees the value cannot change what is sampled: no new
    /// anchor unit after A_e, no second request, no callback of its own.
    function test_V17_sellerCannotRedrawAfterTheValue() public {
        Leaf[] memory ls = new Leaf[](2);
        ls[0].rs = _buy(pidP, _rs(pidP, 0, PRICE), 0);
        ls[1].rs = _buy(pidP, _rs(pidP, 1, PRICE), 1);
        _sort(ls);
        Unit memory u = _unit(pidP, ls);
        _toAnchor();
        require(f.anchorUnit(u) == 0, "anchor");
        uint256 id = _requestSample(pidP, epoch);
        _fulfill(id, 77);
        bytes32 commit = m.anchorCommitment(pidP, epoch);
        // a re-signed unit after A_e is rejected (reason 3: outside the window)
        Unit memory u2 = _unit(pidP, ls);
        u2.unitNo = 2;
        require(f.anchorUnit(u2) == 3, "late unit rejected");
        require(m.anchorCommitment(pidP, epoch) == commit, "anchor unchanged");
        vm.prank(seller);
        vm.expectRevert(SettlementBase.State.selector);
        m.requestSample(pidP, epoch);
        uint256[] memory ws = new uint256[](1);
        vm.prank(seller);
        vm.expectRevert(SettlementBase.Unauthorized.selector);
        m.rawFulfillRandomWords(id, ws);
    }

    /// The fulfillment is paid from the contract's subscription (native).
    function test_V18_fulfillmentPaidFromTheSubscription() public {
        _epochOf(pidP, 1, PRICE);
        uint256 id = _requestSample(pidP, epoch);
        (, uint96 before,,,) = vrf.getSubscription(f.vrfSubId());
        _fulfill(id, 3);
        (, uint96 afterBal,,,) = vrf.getSubscription(f.vrfSubId());
        require(afterBal < before, "native balance charged");
    }
}
