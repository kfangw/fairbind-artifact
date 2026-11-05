// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { TEST_BEACON_DELAY_BLOCKS, TEST_EPOCH0_BEACON_BLOCK } from "../TestProfileConstants.sol";
import { FairBindCore } from "../../src/FairBindCore.sol";
import { FairBindMerkle } from "../../src/FairBindMerkle.sol";
import { FairBind } from "../../src/FairBind.sol";
import { DeployFairBind } from "../DeployFairBind.sol";
import { DeployFairBindWithoutFreeze } from "../invariant/FreezeDisabled.sol";
import { DeployFairBindWithAdmissionOverride } from "../AdmissionOverrideRegistry.sol";
import { MockEIP3009Token } from "../MockEIP3009Token.sol";

interface ReproVm {
    function addr(uint256 key) external returns (address);
    function sign(uint256 key, bytes32 digest) external returns (uint8, bytes32, bytes32);
    function prank(address caller) external;
    function startPrank(address caller) external;
    function stopPrank() external;
    function roll(uint256 height) external;
    function setBlockhash(uint256 height, bytes32 hash) external;
    function expectRevert(bytes4 selector) external;
    function expectRevert(bytes calldata message) external;
}

/// Shared deployment and driving helpers for the reproduction tests.
/// The seller owner is a dedicated address so that seller revenue can be read
/// directly from its token balance.
abstract contract ReproBase is DeployFairBind, DeployFairBindWithoutFreeze, DeployFairBindWithAdmissionOverride {
    /// Deploys the mutation build without the bond-level freeze (pre-ADR 0012 rule).
    bool internal disableFreeze;
    ReproVm internal constant hv =
        ReproVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    address internal constant CONSOLE = 0x000000000000000000636F6e736F6c652e6c6f67;
    address internal constant TREASURY = address(0xCAFE);
    address internal constant SELLER_OWNER = address(0x5E11E7);
    uint256 internal constant SELLER_KEY = 55555;
    uint256 internal constant BUYER_KEY = 77777;
    uint32 internal constant PROFILE = 3;
    uint256 internal constant PPM = 1_000_000;
    bytes32 internal constant CLAIMS = keccak256("claims");
    bytes internal constant EVIDENCE = bytes("canonical evidence fixture");
    bytes32 internal constant LEAF_DOMAIN = keccak256("fairbind/epoch-leaf/v1");
    bytes32 internal constant NODE_DOMAIN = keccak256("fairbind/epoch-node/v1");

    MockEIP3009Token internal token;
    FairBind internal fairbind;
    uint32 internal sellerId;
    address internal buyer;
    uint128 internal nextKey = 1;

    // Receipt tree of the most recent _buildTree call.
    bytes32[] internal sortedNonces;
    bytes32[] internal sortedLeaves;
    bytes32[][] internal levels;
    mapping(bytes32 => uint32) internal treeIndex;

    // ---------------------------------------------------------------- logging

    function _log(string memory label, uint256 value) internal view {
        (bool ok,) = CONSOLE.staticcall(abi.encodeWithSignature("log(string,uint256)", label, value));
        ok;
    }

    function _logInt(string memory label, int256 value) internal view {
        (bool ok,) = CONSOLE.staticcall(abi.encodeWithSignature("log(string,int256)", label, value));
        ok;
    }

    function _logStr(string memory text) internal view {
        (bool ok,) = CONSOLE.staticcall(abi.encodeWithSignature("log(string)", text));
        ok;
    }

    /// Beacon block of epoch 0 under the base profile: the anchor deadline
    /// (block 700) plus one plus beaconDelayBlocks.
    uint256 internal constant BEACON_BLOCK = TEST_EPOCH0_BEACON_BLOCK;

    // ------------------------------------------------------------- deployment

    function _baseProfile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p.classId = 1;
        p.predicateId = keccak256("predicate");
        p.canonId = keccak256("fairbind/http-canon/v1");
        p.epochOrigin = 1;
        p.epochBlocks = 300;
        p.samplePpm = 40_000;
        p.effectivePpm = 40_000;
        p.recheckPpm = 1_000_000;
        p.bucketCapacity = 20;
        p.refillPpmPerBlock = 50_000;
        p.maxRatePpmPerBlock = 60_000;
        p.enforcementBlocks = 30_000;
        p.deferBlocks = 40_000;
        p.retentionBlocks = 40_000;
        p.marginBlocks = 500;
        p.maxRequestBytes = 65_536;
        p.maxResponseBytes = 65_536;
        p.maxEvidenceBytes = 131_072;
        p.maxPublicationCost = 5_000_000;
        p.maxReviewCost = 1_000_000;
        p.maxPurchaseValue = 10_000;
        p.maxBadGain = 10_000;
        p.sellerPenalty = 10_000_000;
        p.minVerifierBond = 1_000_000;
        p.verifierBondCap = 100_000_000;
        p.verifierLatePenalty = 500_000;
        p.verifierWrongPenalty = 1_000_000;
        p.disputeDeposit = 5_000_000;
        p.appealDeposit = 5_000_000;
        p.verifierExposurePpm = 500_000;
        p.maxAssignments = 3;
        p.minVerifiers = 14;
        p.strikeLimit = 3;
        p.deadlineConfigId = 1;
        p.claimWindowBlocks = p.retentionBlocks;
        p.failureLimit = 3;
        p.failureWindowBlocks = p.retentionBlocks;
        p.maxInconclusivePpm = 1_000_000;
        p.inconclusiveWindowBlocks = p.retentionBlocks;
        p.forfeitVerifierPpm = 500_000;
        // The comparison profile freezes at the initial FAIL (ADR 0012 as first
        // implemented); only the admission-override build admits it. A profile
        // with freezeOnInitialFail = false is deployed on the production build.
        p.freezeOnInitialFail = true;
        p.minJudgedCount = 1;
        p.beaconDelayBlocks = TEST_BEACON_DELAY_BLOCKS;
        p.parameterHash = keccak256("profile");
    }

    /// The base profile as a production build admits it: the freeze, the
    /// suspension and the claim window start at the confirmed failure.
    function _productionProfile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _baseProfile();
        p.freezeOnInitialFail = false;
    }

    /// Deploys FairBind, one profile, fourteen verifiers, a seller whose bond equals
    /// the profile seller penalty, and a buyer with a signing key. A profile
    /// that freezes at the initial FAIL needs the admission-override build.
    function _deploy(FairBindCore.ServiceProfileInput memory p) internal {
        token = new MockEIP3009Token();
        token.setVerifySignatures(true);
        fairbind = disableFreeze
            ? deployFairBindWithoutFreeze(address(token), address(this), address(0xA11CE), TREASURY, REWARD_POOL)
            : p.freezeOnInitialFail
                ? deployFairBindWithAdmissionOverride(address(token), address(this), address(0xA11CE), TREASURY, REWARD_POOL)
                : deployFairBind(address(token), address(this), address(0xA11CE), TREASURY);
        fairbind.createDeadlineConfig(
            1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600)
        );
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

    // ------------------------------------------------------- design 2 terms

    /// Commitment to design 2 profile terms (ADR 0025), as setProfileTerms checks it.
    function _termsHash(uint32 p0, uint96[] memory caps, FairBindCore.SalesTier[] memory tiers)
        internal
        pure
        returns (bytes32)
    {
        return keccak256(abi.encode(keccak256("fairbind/profile-terms/v1"), p0, caps, tiers));
    }

    function _setProfileTerms(uint32 id, uint32 p0, uint96[] memory caps, FairBindCore.SalesTier[] memory tiers)
        internal
    {
        fairbind.setProfileTerms(id, _termsHash(p0, caps, tiers), p0, caps, tiers);
    }

    // --------------------------------------------------------------- purchase

    struct SettleArgs {
        bytes16 key;
        bytes32 req;
        bytes32 nonce;
        FairBindCore.TransferAuthorization auth;
        bytes sig;
    }

    /// Builds a buyer-signed EIP-3009 authorization whose payee is the FairBind contract.
    function _settleArgs(uint256 value) internal returns (SettleArgs memory a) {
        a.key = bytes16(nextKey++);
        a.req = keccak256(abi.encode(a.key));
        a.nonce = fairbind.deriveNonce(sellerId, PROFILE, CLAIMS, buyer, a.key, a.req);
        a.auth = FairBindCore.TransferAuthorization(buyer, address(fairbind), value, 0, 100, a.nonce);
        a.sig = _sig(
            BUYER_KEY, token.receiveAuthorizationDigest(buyer, address(fairbind), value, 0, 100, a.nonce)
        );
    }

    function _settle(SettleArgs memory a) internal {
        fairbind.settle(sellerId, PROFILE, CLAIMS, a.key, a.req, a.auth, a.sig);
    }

    function _purchase(uint256 value) internal returns (bytes32) {
        SettleArgs memory a = _settleArgs(value);
        _settle(a);
        return a.nonce;
    }

    // ---------------------------------------------------- receipts and verdicts

    function _receipt(bytes32 n) internal view returns (FairBindCore.FairBindReceipt memory r) {
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        r = FairBindCore.FairBindReceipt(
            1,
            p.sellerId,
            p.profileId,
            n,
            p.requestHash,
            keccak256("response"),
            CLAIMS,
            keccak256("commitment"),
            p.epoch,
            1
        );
    }

    function _sig(uint256 key, bytes32 hash) internal returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = hv.sign(key, hash);
        return abi.encodePacked(r, s, v);
    }

    function _verdict(bytes32 n, uint8 result)
        internal
        view
        returns (FairBindCore.SignedVerdict memory v)
    {
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        v = FairBindCore.SignedVerdict(
            1, n, c.stage, c.attempt, c.assignedVerifierId, result, keccak256(EVIDENCE)
        );
    }

    /// Submits a signed verdict with a seller-signed receipt and its inclusion
    /// proof from the tree built by _buildTree.
    function _judge(bytes32 n, uint8 result) internal {
        FairBindCore.SignedVerdict memory v = _verdict(n, result);
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        fairbind.judge(
            v,
            _sig(1000 + v.verifierId, fairbind.verdictDigest(v)),
            r,
            _sig(SELLER_KEY, fairbind.receiptDigest(r)),
            _proof(n)
        );
    }

    // ----------------------------------------------------------- receipt tree

    /// Builds the ordered receipt tree of merkle-v1 over the given nonces.
    function _buildTree(bytes32[] memory nonces) internal returns (bytes32 root) {
        uint256 n = nonces.length;
        bytes32[] memory s = new bytes32[](n);
        for (uint256 i; i < n; i++) s[i] = nonces[i];
        for (uint256 i = 1; i < n; i++) {
            bytes32 x = s[i];
            uint256 j = i;
            while (j > 0 && uint256(s[j - 1]) > uint256(x)) {
                s[j] = s[j - 1];
                j--;
            }
            s[j] = x;
        }
        delete sortedNonces;
        delete sortedLeaves;
        delete levels;
        bytes32[] memory level = new bytes32[](n);
        for (uint256 i; i < n; i++) {
            sortedNonces.push(s[i]);
            sortedLeaves.push(fairbind.receiptDigest(_receipt(s[i])));
            treeIndex[s[i]] = uint32(i);
            level[i] = keccak256(abi.encode(LEAF_DOMAIN, s[i], sortedLeaves[i]));
        }
        levels.push(level);
        while (level.length > 1) {
            uint256 w = (level.length + 1) / 2;
            bytes32[] memory up = new bytes32[](w);
            for (uint256 i; i < w; i++) {
                bytes32 left = level[2 * i];
                bytes32 right = 2 * i + 1 < level.length ? level[2 * i + 1] : left;
                up[i] = keccak256(abi.encode(NODE_DOMAIN, left, right));
            }
            levels.push(up);
            level = up;
        }
        root = level[0];
    }

    /// The (nonce, receiptLeaf) pairs of the tree built by _buildTree, in
    /// nonce order: the list an anchor carries. It reads storage only, so a
    /// prank set before an anchor call that takes it as argument survives.
    function _treeEntries() internal view returns (FairBindMerkle.ReceiptEntry[] memory list) {
        uint256 n = sortedNonces.length;
        list = new FairBindMerkle.ReceiptEntry[](n);
        for (uint256 i; i < n; i++) list[i] = FairBindMerkle.ReceiptEntry(sortedNonces[i], sortedLeaves[i]);
    }

    function _proof(bytes32 n) internal view returns (FairBindCore.ReceiptProof memory p) {
        uint256 idx = treeIndex[n];
        uint256 height = levels.length - 1;
        bytes32[] memory siblings = new bytes32[](height);
        uint256 cursor = idx;
        for (uint256 h; h < height; h++) {
            bytes32[] storage lvl = levels[h];
            uint256 other = cursor ^ 1;
            siblings[h] = other < lvl.length ? lvl[other] : lvl[cursor];
            cursor >>= 1;
        }
        p = FairBindCore.ReceiptProof(uint32(idx), uint32(sortedNonces.length), siblings);
    }

    // ----------------------------------------------------- sampling predicate

    /// Copy of the ledger-nonce sampling predicate (fairbind-v1 section 12,
    /// cryptography-v1 sample value) used to cross-check the contract.
    function _sampledCopy(bytes32 randomness, uint32 seller, uint24 epoch, bytes32 nonce, uint32 ppm)
        internal
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
        uint256 threshold = quotient * ppm + ((remainder + 1) * ppm) / PPM;
        return value < threshold;
    }
}
