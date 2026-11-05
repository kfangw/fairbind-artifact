// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBind } from "../src/FairBind.sol";
import { ReproBase } from "./repro/ReproBase.sol";
import { ArtifactVm } from "./DeployFairBind.sol";
import { MockEIP3009Token } from "./MockEIP3009Token.sol";
import { FairBindRegistry } from "../src/modules/FairBindRegistry.sol";
import { FairBindSettlement } from "../src/modules/FairBindSettlement.sol";
import { FairBindSampling } from "../src/modules/FairBindSampling.sol";
import { FairBindDelivery } from "../src/modules/FairBindDelivery.sol";
import { FairBindPublication } from "../src/modules/FairBindPublication.sol";
import { FairBindRecovery } from "../src/modules/FairBindRecovery.sol";
import { FairBindJudgment } from "../src/modules/FairBindJudgment.sol";
import { FairBindReview } from "../src/modules/FairBindReview.sol";
import { FairBindBond } from "../src/modules/FairBindBond.sol";
import { FairBindLens } from "../src/modules/FairBindLens.sol";

interface SwapVm {
    function getBlockNumber() external view returns (uint256);
    function snapshotState() external returns (uint256);
    function revertToState(uint256) external returns (bool);
}

/// ReproBase with the module set chosen per test: a mutation build replaces
/// one module by an artifact of the test tree.
abstract contract ModuleSwapBase is ReproBase {
    ArtifactVm internal constant swapArtifacts = ArtifactVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    SwapVm internal constant sw = SwapVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    uint256 internal constant REGISTRY = 0;
    uint256 internal constant SETTLEMENT = 1;
    uint256 internal constant SAMPLING = 2;
    uint256 internal constant DELIVERY = 3;
    uint256 internal constant PUBLICATION = 4;
    uint256 internal constant RECOVERY = 5;

    /// The current block through the cheatcode (via_ir may read a stale block.number).
    function _now() internal view returns (uint256) {
        return sw.getBlockNumber();
    }

    function _productionModules() internal pure returns (string[10] memory) {
        return [
            "FairBindRegistry.sol:FairBindRegistry",
            "FairBindSettlement.sol:FairBindSettlement",
            "FairBindSampling.sol:FairBindSampling",
            "FairBindDelivery.sol:FairBindDelivery",
            "FairBindPublication.sol:FairBindPublication",
            "FairBindRecovery.sol:FairBindRecovery",
            "FairBindJudgment.sol:FairBindJudgment",
            "FairBindReview.sol:FairBindReview",
            "FairBindBond.sol:FairBindBond",
            "FairBindLens.sol:FairBindLens"
        ];
    }

    /// ReproBase._deploy on a production profile with the given modules.
    function _deployModules(string[10] memory names, FairBindCore.ServiceProfileInput memory p) internal {
        token = new MockEIP3009Token();
        token.setVerifySignatures(true);
        bytes memory args = abi.encode(address(token), address(this), address(0xA11CE), TREASURY, REWARD_POOL);
        address[10] memory modules;
        for (uint256 i; i < 10; i++) modules[i] = swapArtifacts.deployCode(names[i], args);
        fairbind = FairBind(
            swapArtifacts.deployCode(
                "FairBind.sol:FairBind",
                abi.encode(address(token), address(this), address(0xA11CE), TREASURY, REWARD_POOL, modules)
            )
        );
        fairbind.createDeadlineConfig(1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600));
        fairbind.createServiceProfile(PROFILE, p);
        token.mint(address(this), 1_000_000_000);
        token.approve(address(fairbind), type(uint256).max);
        for (uint32 i = 1; i <= 14; i++) {
            fairbind.registerVerifier(uint256(1) << 1, hv.addr(1000 + i), 10_000_000);
        }
        fairbind.checkpointVerifierTree(PROFILE);
        fairbind.setServiceProfileActive(PROFILE, true);
        token.mint(SELLER_OWNER, p.sellerPenalty);
        hv.startPrank(SELLER_OWNER);
        token.approve(address(fairbind), type(uint256).max);
        sellerId = registerSellerWithBond(fairbind, PROFILE, hv.addr(SELLER_KEY), CLAIMS, uint128(p.sellerPenalty));
        hv.stopPrank();
        buyer = hv.addr(BUYER_KEY);
        token.mint(buyer, 100_000_000);
        hv.prank(buyer);
        token.approve(address(fairbind), type(uint256).max);
    }

    function _bondId() internal view returns (uint32) {
        return fairbind.getSeller(sellerId).bondId;
    }

    function _bond() internal view returns (FairBindCore.BondView memory) {
        return fairbind.getBond(_bondId());
    }

    /// Buyer non-delivery dispute that ends UNSERVED: a confirmed seller failure
    /// tied to purchase n.
    function _unserved(bytes32 n) internal {
        _disputeNonDelivery(n);
        hv.roll(uint256(fairbind.getCase(n).serveDue) + 1);
        fairbind.timeoutServe(n);
    }

    function _disputeNonDelivery(bytes32 n) internal {
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        if (_now() <= p.responseDue) hv.roll(uint256(p.responseDue) + 1);
        FairBindCore.FairBindReceipt memory empty;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
    }

    function _emptyProof() internal pure returns (FairBindCore.ReceiptProof memory) {
        return FairBindCore.ReceiptProof(0, 0, new bytes32[](0));
    }

    function _claimWith(bytes32 n, FairBindCore.ReceiptProof memory proof) internal {
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        fairbind.claimRefund(n, r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), proof);
    }

    function claimExternal(bytes32 n, FairBindCore.ReceiptProof memory proof) external {
        _claimWith(n, proof);
    }

    function releaseExternal(bytes32 n) external {
        fairbind.releasePurchase(n);
    }

    /// A beacon hash under which none of the given purchases of `epoch` is sampled.
    function _unsampledBeacon(uint24 epoch, bytes32[] memory ns) internal view returns (bytes32 h) {
        uint256 ppm = fairbind.getServiceProfile(PROFILE).parameters.samplePpm;
        uint256 threshold = type(uint256).max / PPM * ppm + ((type(uint256).max % PPM + 1) * ppm) / PPM;
        for (uint256 salt;; salt++) {
            h = keccak256(abi.encode("beacon", epoch, salt));
            bool any;
            for (uint256 i; i < ns.length; i++) {
                uint256 v = uint256(keccak256(abi.encode(fairbind.SAMPLE_DOMAIN(), h, sellerId, epoch, ns[i])));
                if (v < threshold) any = true;
            }
            if (!any) return h;
        }
    }

    /// Anchors and seals an epoch on the block hash path with every purchase unsampled.
    function _anchorAndSealUnsampled(uint24 epoch, bytes32[] memory ns) internal {
        _buildTree(ns);
        uint256 base = 300 * (uint256(epoch) + 2);
        if (_now() < base) hv.roll(base);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, epoch, _treeEntries(), uint32(ns.length), keccak256("publication"));
        uint64 rb = fairbind.getAnchor(sellerId, epoch).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, _unsampledBeacon(epoch, ns));
        fairbind.seal(sellerId, epoch);
    }
}
