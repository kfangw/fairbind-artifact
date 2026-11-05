// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindExchange } from "../src/modules/FairBindExchange.sol";
import { FairBindPassProof } from "../src/modules/FairBindPassProof.sol";
import { FairBindSelfProof } from "../src/modules/FairBindSelfProof.sol";
import { FairBindSettlement } from "../src/modules/FairBindSettlement.sol";
import { FairBindDelivery } from "../src/modules/FairBindDelivery.sol";
import { FairBindBatchAdmin } from "../src/modules/FairBindBatchAdmin.sol";
import { ExchangeShared } from "../src/modules/ExchangeShared.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";

/// Mutation builds of the receipt-signature and proof modules (ADR 0037).
/// Each breaks one rule a test checks.

/// A match after the anchor deadline still binds the sale.
contract LateMatchExchange is FairBindExchange {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindExchange(token, gov, guard, treasury, pool)
    { }

    function _matchInTime(PurchaseView storage) internal pure override returns (bool) {
        return true;
    }
}

/// Any posting signature is taken.
contract AnyPosterExchange is FairBindExchange {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindExchange(token, gov, guard, treasury, pool)
    { }

    function _postingSignatureOk(uint32, bytes32, bytes calldata, ExchangeStore.Terms storage)
        internal
        pure
        override
        returns (bool)
    {
        return true;
    }
}

/// A later posting of a nonce replaces the first.
contract RepostExchange is FairBindExchange {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindExchange(token, gov, guard, treasury, pool)
    { }

    function _slotFree(bytes32) internal pure override returns (bool) {
        return true;
    }
}

/// The delivered share is the cap itself.
contract LadderCapExchange is FairBindExchange {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindExchange(token, gov, guard, treasury, pool)
    { }

    function _ladderShare(uint256, uint256 cap, uint256 deposit) internal pure override returns (uint256) {
        return cap < deposit ? cap : deposit;
    }
}

/// The admission checks are skipped.
contract OpenAdmissionExchange is FairBindExchange {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindExchange(token, gov, guard, treasury, pool)
    { }

    function _admit(ServiceProfileInput storage, ExchangeStore.Input calldata, uint32, uint8) internal pure override { }
}

/// The key dispute's share is the constant cap c_key.
contract CapShareProof is FairBindPassProof {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindPassProof(token, gov, guard, treasury, pool)
    { }

    function _keyShare(uint256, uint256 cap, uint256 deposit) internal pure override returns (uint256) {
        return cap < deposit ? cap : deposit;
    }
}

/// The key stream ignores the nonce.
contract NoNonceProof is FairBindPassProof {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindPassProof(token, gov, guard, treasury, pool)
    { }

    function _decrypt(bytes32 ek, bytes32, bytes calldata ct) internal pure override returns (bytes memory pt) {
        pt = new bytes(ct.length);
        for (uint256 i; i < ct.length; i++) {
            bytes32 ks = keccak256(abi.encode(ek, bytes32(0), i / 32));
            pt[i] = ct[i] ^ ks[i % 32];
        }
    }
}

/// Unpad strips trailing zero bytes without asking for the 0x80 mark.
contract NoMarkProof is FairBindPassProof {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindPassProof(token, gov, guard, treasury, pool)
    { }

    function _unpad(bytes memory pt) internal pure override returns (uint256 len) {
        uint256 i = pt.length;
        while (i > 32 && pt[i - 1] == 0) i--;
        len = i - 32;
    }
}

/// Every measured call counts the fixed share of a transaction.
contract EveryCallFixedProof is FairBindPassProof {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindPassProof(token, gov, guard, treasury, pool)
    { }

    function _firstCostOfTx() internal pure override returns (bool) {
        return true;
    }
}

/// A proven entry is paid at the last block of the receipt-binding window.
contract EarlyReleaseSelf is FairBindSelfProof {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindSelfProof(token, gov, guard, treasury, pool)
    { }

    function _bindingWindowOver(uint256 age, uint256 retainUntil) internal pure override returns (bool) {
        return age >= retainUntil;
    }
}

/// A seller's proof is confirmed whatever the account's open cases.
contract EarlyReadySelf is FairBindSelfProof {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindSelfProof(token, gov, guard, treasury, pool)
    { }

    function _selfReady(bytes32) internal pure override returns (bool) {
        return true;
    }
}

/// The reference time of any validAfter is accepted.
contract StaleRefSettlement is FairBindSettlement {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindSettlement(token, gov, guard, treasury, pool)
    { }

    function _referenceTimeOk(uint256, uint256) internal pure override returns (bool) {
        return true;
    }
}

/// The L1 share priced by content, as before rule v2.15: getL1Fee of the
/// call data followed by bEnv bytes 0xff, the envelope fee taken off a later
/// call of the transaction.
library GetL1FeeShare {
    address internal constant ORACLE = 0x420000000000000000000000000000000000000F;

    function share(bytes memory xhat, uint256 env, bool first) internal view returns (uint256 l1) {
        l1 = fee(xhat, env);
        if (!first) {
            uint256 f = fee("", env);
            l1 = l1 > f ? l1 - f : 0;
        }
    }

    function fee(bytes memory data, uint256 env) internal view returns (uint256 out) {
        if (ORACLE.code.length == 0) return 0;
        uint256 n = data.length;
        bytes memory full = new bytes(n + env);
        for (uint256 i; i < n; i++) full[i] = data[i];
        for (uint256 i; i < env; i++) full[n + i] = 0xff;
        (bool ok, bytes memory ret) = ORACLE.staticcall(abi.encodeWithSignature("getL1Fee(bytes)", full));
        if (ok && ret.length >= 32) out = abi.decode(ret, (uint256));
    }
}

/// The key dispute's measured cost prices the L1 share with getL1Fee.
contract GetL1FeeProof is FairBindPassProof {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindPassProof(token, gov, guard, treasury, pool)
    { }

    function _l1Share(bytes memory xhat, uint256 env, bool first) internal view override returns (uint256) {
        return GetL1FeeShare.share(xhat, env, first);
    }
}

/// Exposes the L1 share of a measured call, outside the router.
contract L1ShareProbe is ExchangeShared {
    constructor(address token, address gov, address guard, address treasury, address pool)
        ExchangeShared(token, gov, guard, treasury, pool)
    { }

    function l1Share(bytes memory xhat, uint256 env, bool first) external view returns (uint256) {
        return _l1Share(xhat, env, first);
    }
}

/// The gas of the measured cost itself (UB form), outside the router: the
/// terms of profile 1 hold the cost constants; the slot is read once before
/// so that, as in a PASS proof, it is warm. The oracle's account is cold in
/// the first measurement, as in the proof transaction.
contract CostProbe is L1ShareProbe {
    constructor(address token, address gov, address guard, address treasury, address pool)
        L1ShareProbe(token, gov, guard, treasury, pool)
    { }

    function setCostTerms(uint96 priceCap, uint32 gFixTx, uint32 gFixCall, uint32 bEnv) external {
        ExchangeStore.Terms storage t = ExchangeStore.layout().terms[1];
        t.costOn = true;
        t.priceCap = priceCap;
        t.gFixTx = gFixTx;
        t.gFixCall = gFixCall;
        t.bEnv = bEnv;
    }

    function measureGas(bytes memory xhat) external returns (uint256 gFirst, uint256 gLater, uint256 cFirst, uint256 cLater) {
        ExchangeStore.Terms storage t = ExchangeStore.layout().terms[1];
        if (!t.costOn) revert();
        uint256 g = gasleft();
        cFirst = _measuredCost(t, g, 0, xhat);
        gFirst = g - gasleft();
        g = gasleft();
        cLater = _measuredCost(t, g, 0, xhat);
        gLater = g - gasleft();
    }
}

/// The probe of the getL1Fee mutation.
contract GetL1FeeShareProbe is L1ShareProbe {
    constructor(address token, address gov, address guard, address treasury, address pool)
        L1ShareProbe(token, gov, guard, treasury, pool)
    { }

    function _l1Share(bytes memory xhat, uint256 env, bool first) internal view override returns (uint256) {
        return GetL1FeeShare.share(xhat, env, first);
    }
}

/// Batch terms with the side-gain grade (or any batch terms under a proof
/// profile) are taken after exchange terms.
contract SideGainAfterTermsAdmin is FairBindBatchAdmin {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindBatchAdmin(token, gov, guard, treasury, pool)
    { }

    function _excludedByExchange(uint32, uint256) internal pure override returns (bool) {
        return false;
    }
}

/// A refund returns its unit to the seller's bucket, in the three modules
/// that refund: the unbound refund, the dispute refunds of a proof profile
/// (key dispute and wrong delivery), and the non-delivery refund of a
/// receipt-signature vote profile.
contract UnitBackExchange is FairBindExchange {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindExchange(token, gov, guard, treasury, pool)
    { }

    function _setFinancialState(bytes32 nonce, FinancialState next) internal override {
        super._setFinancialState(nonce, next);
        if (next == FinancialState.REFUNDABLE) bonds[sellers[purchases[nonce].sellerId].viewData.bondId].bucketBalancePpm += PPM;
    }
}

contract UnitBackProof is FairBindPassProof {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindPassProof(token, gov, guard, treasury, pool)
    { }

    function _setFinancialState(bytes32 nonce, FinancialState next) internal override {
        super._setFinancialState(nonce, next);
        if (next == FinancialState.REFUNDABLE) bonds[sellers[purchases[nonce].sellerId].viewData.bondId].bucketBalancePpm += PPM;
    }
}

contract UnitBackDelivery is FairBindDelivery {
    constructor(address token, address gov, address guard, address treasury, address pool)
        FairBindDelivery(token, gov, guard, treasury, pool)
    { }

    function _setFinancialState(bytes32 nonce, FinancialState next) internal override {
        super._setFinancialState(nonce, next);
        if (next == FinancialState.REFUNDABLE) bonds[sellers[purchases[nonce].sellerId].viewData.bondId].bucketBalancePpm += PPM;
    }
}
