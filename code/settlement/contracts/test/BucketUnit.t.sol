// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { ExchangeBase } from "./ExchangeBase.sol";
import { MockUniquePriceFeed } from "./ExchangeMocks.sol";

/// A refund never returns its unit to the seller's rate-limit bucket (rule
/// D2-7, D2-33 (c) as of v2.15): after the refund of an unbound purchase, of
/// a lapsed key dispute or wrong-delivery dispute of a proof profile, or of
/// a lapsed non-delivery dispute of a receipt-signature vote profile, the
/// bucket in the same block is what it was, so a window of length Lambda
/// still admits at most S settlements. The bucket refills by one ppm a block
/// so that it stays below its capacity and a returned unit would show.
contract BucketUnitTest is ExchangeBase {
    string internal constant UNIT_BACK_EXCHANGE = "ExchangeMutants.sol:UnitBackExchange";
    string internal constant UNIT_BACK_PROOF = "ExchangeMutants.sol:UnitBackProof";
    string internal constant UNIT_BACK_DELIVERY = "ExchangeMutants.sol:UnitBackDelivery";

    function _start(uint8 m) internal {
        mode = m;
        FairBindCore.ServiceProfileInput memory p = _exchangeProfile();
        p.refillPpmPerBlock = 1;
        feed = new MockUniquePriceFeed(hv.addr(GUARDIAN_KEY));
        _deployExchange(p, _input(m), true);
        hv.roll(10);
    }

    function _bucket() internal view returns (uint256 balance, uint32 remaining) {
        FairBindCore.SellerQuote memory q = fairbind.quoteSeller(sellerId);
        return (q.bucketBalancePpm, q.remaining);
    }

    /// The bucket right before and right after `refund` runs, in one block
    /// (the mutation tests show it is below its capacity there).
    function _around(bytes memory refund) internal returns (uint256 before, uint256 after_) {
        uint32 r0;
        uint32 r1;
        (before, r0) = _bucket();
        (bool ok, bytes memory ret) = address(fairbind).call(refund);
        if (!ok) {
            assembly {
                revert(add(ret, 0x20), mload(ret))
            }
        }
        (after_, r1) = _bucket();
        require(r1 == r0 || after_ != before, "settlements left follow the bucket");
        _log("bucket before (ppm)", before);
        _log("bucket after (ppm)", after_);
    }

    // -------------------------------------------------------- scenarios

    function _unbound(string memory ex) internal returns (uint256, uint256) {
        if (bytes(ex).length != 0) exchangeArtifact = ex;
        _start(ExchangeStore.MODE_PROOF);
        bytes32 n = _buy();
        bytes32 m = _buy();
        bytes32 k = _buy();
        _postSigned(m);
        bytes32[] memory ns = new bytes32[](3);
        ns[0] = n;
        ns[1] = m;
        ns[2] = k;
        _anchorX(0, ns);
        _matchAll(_one(m));
        hv.roll(701);
        (uint256 b, uint256 a) = _around(abi.encodeWithSelector(fx.refundUnbound.selector, n));
        require(_fs(n) == uint8(FairBindCore.FinancialState.REFUNDABLE), "refunded");
        return (b, a);
    }

    function _proofDispute(string memory pass, uint8 kind) internal returns (uint256, uint256) {
        if (bytes(pass).length != 0) passArtifact = pass;
        _start(ExchangeStore.MODE_PROOF);
        bytes32 n = _buy();
        _buy();
        _postSigned(n);
        hv.prank(buyer);
        fx.openProofDispute(n, kind);
        hv.roll(uint256(_record(n).disputeDue) + 1);
        (uint256 b, uint256 a) = _around(abi.encodeWithSelector(fx.timeoutProof.selector, n));
        require(_fs(n) == uint8(FairBindCore.FinancialState.REFUNDABLE), "refunded");
        require(_record(n).disputeState == ExchangeStore.DISPUTE_FAILED, "dispute failed");
        return (b, a);
    }

    function _voteNonDelivery(string memory delivery) internal returns (uint256, uint256) {
        if (bytes(delivery).length != 0) moduleNames[3] = delivery;
        _start(ExchangeStore.MODE_VOTE_SIG);
        bytes32 n = _buy();
        _buy();
        _postSigned(n);
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        hv.roll(uint256(p.responseDue) + 1);
        FairBindCore.FairBindReceipt memory empty;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
        hv.roll(uint256(fairbind.getCase(n).serveDue) + 1);
        (uint256 b, uint256 a) = _around(abi.encodeWithSelector(fairbind.timeoutServe.selector, n));
        require(_fs(n) == uint8(FairBindCore.FinancialState.REFUNDABLE), "refunded");
        require(_bond().failureCount == 0, "a refund, no failure");
        return (b, a);
    }

    // ------------------------------------------------------------ tests

    function test_unboundRefundKeepsTheBucket() public {
        (uint256 b, uint256 a) = _unbound("");
        require(a == b, "no unit back");
    }

    function test_unboundRefundReturningTheUnitIsCaught() public {
        (uint256 b, uint256 a) = _unbound(UNIT_BACK_EXCHANGE);
        require(a != b, "mutation caught");
    }

    function test_keyDisputeRefundKeepsTheBucket() public {
        (uint256 b, uint256 a) = _proofDispute("", uint8(FairBindCore.CaseTrigger.NON_DELIVERY));
        require(a == b, "no unit back");
    }

    function test_keyDisputeRefundReturningTheUnitIsCaught() public {
        (uint256 b, uint256 a) = _proofDispute(UNIT_BACK_PROOF, uint8(FairBindCore.CaseTrigger.NON_DELIVERY));
        require(a != b, "mutation caught");
    }

    function test_wrongDeliveryRefundKeepsTheBucket() public {
        (uint256 b, uint256 a) = _proofDispute("", uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY));
        require(a == b, "no unit back");
    }

    function test_wrongDeliveryRefundReturningTheUnitIsCaught() public {
        (uint256 b, uint256 a) = _proofDispute(UNIT_BACK_PROOF, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY));
        require(a != b, "mutation caught");
    }

    function test_voteNonDeliveryRefundKeepsTheBucket() public {
        (uint256 b, uint256 a) = _voteNonDelivery("");
        require(a == b, "no unit back");
    }

    function test_voteNonDeliveryRefundReturningTheUnitIsCaught() public {
        (uint256 b, uint256 a) = _voteNonDelivery(UNIT_BACK_DELIVERY);
        require(a != b, "mutation caught");
    }
}
