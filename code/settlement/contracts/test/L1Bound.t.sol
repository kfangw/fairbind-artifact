// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { ExchangeBase } from "./ExchangeBase.sol";
import { MockGasPriceOracle, MockUniquePriceFeed } from "./ExchangeMocks.sol";
import { L1ShareProbe, GetL1FeeShareProbe } from "./ExchangeMutants.sol";

/// The L1 share of a measured cost (rule D2-33 (e') 1 as of v2.15, ADR
/// 0037): UB(|xhat| + bEnv) of the oracle's getL1FeeUpperBound for the first
/// measured call of a transaction, UB(|xhat| + bEnv) - UB(bEnv) for a later
/// one; it depends on the length of the call data only. A profile with
/// exchange terms activates only where the bound answers, and once the
/// deployment requires exchange terms, no profile activates without them.
contract L1BoundTest is ExchangeBase {
    uint256 internal constant ENV = 100;
    uint256 internal constant LEN = 968;

    function _etchOracle() internal returns (MockGasPriceOracle o) {
        o = new MockGasPriceOracle();
        xv.etch(ORACLE, address(o).code);
        o = MockGasPriceOracle(ORACLE);
        o.set(L1_UNIT, 20_000_000_000);
    }

    function _inputs() internal pure returns (bytes memory mixed, bytes memory zeros) {
        mixed = new bytes(LEN);
        for (uint256 i; i < LEN; i++) mixed[i] = i % 3 == 0 ? bytes1(0) : bytes1(uint8(i | 1));
        zeros = new bytes(LEN);
    }

    /// Shares of the probe for a mixed and an all-zero input of one length,
    /// as the first and as a later call of a transaction.
    function _shares(L1ShareProbe probe)
        internal
        view
        returns (uint256 mixedFirst, uint256 zeroFirst, uint256 mixedLater, uint256 zeroLater)
    {
        (bytes memory mixed, bytes memory zeros) = _inputs();
        mixedFirst = probe.l1Share(mixed, ENV, true);
        zeroFirst = probe.l1Share(zeros, ENV, true);
        mixedLater = probe.l1Share(mixed, ENV, false);
        zeroLater = probe.l1Share(zeros, ENV, false);
    }

    function _probe(bool content) internal returns (L1ShareProbe) {
        address[5] memory a = [address(0x1001), address(0x1002), address(0x1003), address(0x1004), address(0x1005)];
        if (content) return L1ShareProbe(new GetL1FeeShareProbe(a[0], a[1], a[2], a[3], a[4]));
        return new L1ShareProbe(a[0], a[1], a[2], a[3], a[4]);
    }

    function test_sameLengthInputsTakeTheSameL1Share() public {
        MockGasPriceOracle o = _etchOracle();
        (uint256 mf, uint256 zf, uint256 ml, uint256 zl) = _shares(_probe(false));
        _log("L1 share, 968 bytes, first call", mf);
        _log("L1 share, 968 bytes, later call", ml);
        require(mf == zf && ml == zl, "same length, same share");
        require(mf == o.getL1FeeUpperBound(LEN + ENV), "UB(|xhat| + bEnv)");
        require(ml == o.getL1FeeUpperBound(LEN + ENV) - o.getL1FeeUpperBound(ENV), "later call: less UB(bEnv)");
        require(ml < mf, "the envelope and the floor stay with the first call");
    }

    function test_l1ShareByContentIsCaught() public {
        _etchOracle();
        (uint256 mf, uint256 zf, uint256 ml, uint256 zl) = _shares(_probe(true));
        require(mf != zf || ml != zl, "mutation caught");
    }

    /// Below the size floor of the bound a later call adds no L1 share.
    function test_laterShortCallAddsNothingUnderTheFloor() public {
        MockGasPriceOracle o = _etchOracle();
        L1ShareProbe probe = _probe(false);
        require(o.getL1FeeUpperBound(10) == o.getL1FeeUpperBound(0), "both under the floor");
        require(probe.l1Share(new bytes(10), 0, false) == 0, "nothing beyond the floor");
    }

    function _startUnactivated(uint8 m) internal {
        mode = m;
        skipActivation = true;
        feed = new MockUniquePriceFeed(hv.addr(GUARDIAN_KEY));
        _deployExchange(_exchangeProfile(), _input(m), true);
    }

    function activateExternal(uint32 id) external {
        fairbind.setServiceProfileActive(id, true);
    }

    function _activates(uint32 id) internal returns (bool) {
        try this.activateExternal(id) {
            return true;
        } catch (bytes memory err) {
            require(bytes4(err) == FairBindCore.InvalidProfile.selector, "refused as an invalid profile");
            return false;
        }
    }

    /// An oracle without the bound (a chain before Fjord) refuses the
    /// activation of a profile with exchange terms; so does a chain without
    /// the oracle. A profile without exchange terms activates as before.
    function test_activationNeedsTheL1Bound() public {
        oracleBoundOff = true;
        _startUnactivated(ExchangeStore.MODE_PROOF);
        require(!_activates(PROFILE), "bound reverts: refused");
        oracle.setBoundOff(false);
        require(_activates(PROFILE), "bound answers: active");
    }

    function test_activationWithoutTheOracleIsRefused() public {
        noOracle = true;
        _startUnactivated(ExchangeStore.MODE_VOTE_SIG);
        require(!_activates(PROFILE), "no oracle: refused");
        fairbind.createServiceProfile(7, _exchangeProfile());
        fairbind.checkpointVerifierTree(7);
        require(_activates(7), "no exchange terms: active as before");
    }

    function test_voteTermsOffKeepsTheBoundCheck() public {
        oracleBoundOff = true;
        _startUnactivated(ExchangeStore.MODE_NONE);
        require(!_activates(PROFILE), "measured costs need the bound");
    }

    /// The deployment setting of the evaluation setting (rule 8.2 row 23):
    /// a vote profile without exchange terms does not activate; with exchange
    /// terms (receipt signatures on or off) it does.
    function test_requiredTermsRefuseAVoteProfileWithoutThem() public {
        termsRequired = true;
        _startUnactivated(ExchangeStore.MODE_VOTE_SIG);
        require(_activates(PROFILE), "with exchange terms: active");
        fairbind.createServiceProfile(8, _exchangeProfile());
        fairbind.checkpointVerifierTree(8);
        require(!_activates(8), "without: refused");
        fairbind.createServiceProfile(9, _exchangeProfile());
        ExchangeStore.Input memory off = _input(ExchangeStore.MODE_NONE);
        off.termsHash = fx.exchangeTermsHash(9, off);
        fx.setExchangeTerms(9, off);
        fairbind.checkpointVerifierTree(9);
        require(_activates(9), "signature-free terms: active");
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        fx.requireExchangeTerms();
    }

    function test_withoutTheSettingAProfileWithoutTermsActivates() public {
        _startUnactivated(ExchangeStore.MODE_VOTE_SIG);
        fairbind.createServiceProfile(8, _exchangeProfile());
        fairbind.checkpointVerifierTree(8);
        require(_activates(8), "the setting is off: active");
    }
}
