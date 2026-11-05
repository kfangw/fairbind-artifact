// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBind } from "../src/FairBind.sol";
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";

interface ScriptVm {
    function envOr(string calldata name, uint256 defaultValue) external view returns (uint256);
    function envOr(string calldata name, address defaultValue) external view returns (address);
    function envOr(string calldata name, bytes32 defaultValue) external view returns (bytes32);
    function envOr(string calldata name, bytes calldata defaultValue) external view returns (bytes memory);
    function addr(uint256 key) external pure returns (address);
    function startBroadcast(uint256 key) external;
    function stopBroadcast() external;
    function deployCode(string calldata artifact, bytes calldata args) external returns (address);
    function deployCode(string calldata artifact) external returns (address);
    function etch(address target, bytes calldata code) external;
    function getBlockNumber() external view returns (uint256);
}

interface IEvalRouter {
    function setExtensions(address[] calldata list) external;
    function requireExchangeTerms() external;
    function setExchangeTerms(uint32 profileId, ExchangeStore.Input calldata x) external;
    function exchangeTermsHash(uint32 profileId, ExchangeStore.Input calldata x) external pure returns (bytes32);
    function setBatchTerms(uint32 profileId, BatchStore.Terms calldata t) external;
    function getExchangeTerms(uint32 profileId) external view returns (ExchangeStore.Terms memory);
}

interface IScriptToken {
    function mint(address to, uint256 value) external;
    function approve(address spender, uint256 value) external returns (bool);
}

interface IScriptVrf {
    function publicKey() external view returns (bytes memory);
    function responseBlocks() external view returns (uint32);
    function deadlineSlackBlocks() external view returns (uint32);
}

interface IScriptOracle {
    function set(uint256 feePerUnit, uint256 floor) external;
}

/// Evaluation-setting deployment (deploy/README.md, "Evaluation-setting
/// deployment"): the router with its ten modules, the seven extension
/// modules, the request-based randomness source, requireExchangeTerms()
/// before any activation, and two profiles of data-api-design2-v1 timing:
/// profile 5, the default vote profile (receipt signatures, batched
/// assignment), and profile 7, a proof profile of the UNIQUE kind. Fourteen
/// verifiers are registered and checkpointed for both.
///
/// Local run (no RPC: an in-process chain, chain id 31337): the token, the VRF
/// proof check, the price feed and the L1 fee oracle are the test mocks, the
/// oracle etched at its predeploy, and every key is a default test key.
///   forge script contracts/script/DeployEvalSetting.s.sol -vv
/// Testnet run: the RPC and the deployer key come from the environment, and
/// the deployment refuses to stand in mocks for the token, the VRF proof
/// check and the price feed; the chain must serve the Fjord GasPriceOracle.
///   FAIRBIND_RPC_URL=... FAIRBIND_DEPLOYER_KEY=... FAIRBIND_TOKEN=...
///   FAIRBIND_VRF_VERIFIER=... FAIRBIND_VRF_PUBLIC_KEY=0x... FAIRBIND_PRICE_VERIFIER=...
///   FAIRBIND_FEED_ID=0x... FAIRBIND_GUARDIAN=... FAIRBIND_TREASURY=... FAIRBIND_REWARD_POOL=...
///   forge script contracts/script/DeployEvalSetting.s.sol --rpc-url "$FAIRBIND_RPC_URL" --broadcast
/// FAIRBIND_VERIFIER_KEY_BASE (default 1000) seeds the fourteen verifier
/// signing addresses of a local run; a testnet run takes them as
/// FAIRBIND_VERIFIER_SIGNER_0 .. _13.
///
/// The timing constants are those of profiles/design2-v1.json and of the path
/// enumeration: D_V = 10, T_V = 20, assignDelay = 20, T_p = 300, so L_F is
/// 29,454 for the default vote profile and 1,412 for the proof profile.
/// F_max is 30,008 for the vote profile, inside check 8's [29,953, 31,072]
/// (L_F + marginBlocks - 1 through T_hold - 1), and L_F,P + marginBlocks - 1
/// = 1,911 for the proof profile. The prices and gas bounds of the exchange
/// terms are placeholders until measured.
contract DeployEvalSetting {
    ScriptVm internal constant vm = ScriptVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    address internal constant ORACLE = 0x420000000000000000000000000000000000000F;
    uint256 internal constant LOCAL_CHAIN = 31337;
    /// The first default test key of the Anvil mnemonic.
    uint256 internal constant LOCAL_KEY = 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80;
    uint32 internal constant VOTE = 5;
    uint32 internal constant PROOF = 7;
    uint32 internal constant D_V = 10;
    uint32 internal constant T_V = 20;
    uint256 internal constant VERIFIERS = 14;

    struct Deployment {
        address router;
        address token;
        address vrf;
        address priceVerifier;
        address[10] modules;
        address[7] extensions;
    }

    function run() external returns (Deployment memory out) {
        bool local = block.chainid == LOCAL_CHAIN;
        uint256 key = vm.envOr("FAIRBIND_DEPLOYER_KEY", local ? LOCAL_KEY : uint256(0));
        require(key != 0, "FAIRBIND_DEPLOYER_KEY");
        address gov = vm.addr(key);
        address guardian = vm.envOr("FAIRBIND_GUARDIAN", local ? address(0xA11CE) : address(0));
        address treasury = vm.envOr("FAIRBIND_TREASURY", local ? address(0x7EA5) : address(0));
        address pool = vm.envOr("FAIRBIND_REWARD_POOL", local ? address(0x9001) : address(0));
        require(guardian != address(0) && treasury != address(0) && pool != address(0), "role addresses");
        if (local && ORACLE.code.length == 0) {
            // The in-process chain has no OP Stack predeploy; a local run
            // stands in the test oracle, which computes the Fjord bound.
            vm.etch(ORACLE, _code(vm.deployCode("ExchangeMocks.sol:MockGasPriceOracle")));
            IScriptOracle(ORACLE).set(10_000_000, 20_000_000_000);
        }
        require(ORACLE.code.length != 0, "the chain serves no GasPriceOracle");

        vm.startBroadcast(key);
        out.token = vm.envOr("FAIRBIND_TOKEN", address(0));
        if (out.token == address(0)) {
            require(local, "FAIRBIND_TOKEN");
            out.token = vm.deployCode("MockEIP3009Token.sol:MockEIP3009Token");
            IScriptToken(out.token).mint(gov, 1_000_000_000_000);
        }
        bytes memory args = abi.encode(out.token, gov, guardian, treasury, pool);
        string[10] memory names = [
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
        for (uint256 i; i < 10; i++) out.modules[i] = vm.deployCode(names[i], args);
        out.router = vm.deployCode(
            "FairBind.sol:FairBind", abi.encode(out.token, gov, guardian, treasury, pool, out.modules)
        );
        FairBind fb = FairBind(out.router);
        IEvalRouter jr = IEvalRouter(out.router);
        string[7] memory extNames = [
            "FairBindBatch.sol:FairBindBatch",
            "FairBindBatchAdmin.sol:FairBindBatchAdmin",
            "FairBindProof.sol:FairBindProof",
            "FairBindDeposit.sol:FairBindDeposit",
            "FairBindExchange.sol:FairBindExchange",
            "FairBindPassProof.sol:FairBindPassProof",
            "FairBindSelfProof.sol:FairBindSelfProof"
        ];
        address[] memory exts = new address[](7);
        for (uint256 i; i < 7; i++) {
            exts[i] = vm.deployCode(extNames[i], args);
            out.extensions[i] = exts[i];
        }
        jr.setExtensions(exts);
        // Rule 8.2 row 23: no profile activates without exchange terms.
        jr.requireExchangeTerms();

        // The request-based source (rule D2-23, D_S = D_V + 1).
        address vrfVerifier = vm.envOr("FAIRBIND_VRF_VERIFIER", address(0));
        bytes memory vrfKey = vm.envOr("FAIRBIND_VRF_PUBLIC_KEY", bytes(""));
        if (vrfVerifier == address(0)) {
            require(local, "FAIRBIND_VRF_VERIFIER");
            vrfVerifier = vm.deployCode("MockVrfVerifier.sol:MockVrfVerifier");
            vrfKey = abi.encode(vm.addr(0x5EED));
        }
        require(vrfKey.length != 0, "FAIRBIND_VRF_PUBLIC_KEY");
        out.vrf = vm.deployCode("FairBindVrf.sol:FairBindVrf", abi.encode(out.router, vrfVerifier, vrfKey, D_V, T_V));
        fb.setRandomness(out.vrf);

        // Verifiers, one deadline configuration and the two profiles.
        uint256 origin = vm.getBlockNumber();
        fb.createDeadlineConfig(1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600));
        fb.createServiceProfile(VOTE, _profile(origin, keccak256("profile/data-api-design2-v1/vote")));
        fb.createServiceProfile(PROOF, _profile(origin, keccak256("profile/data-api-design2-v1/proof-unique")));
        IScriptToken(out.token).approve(out.router, type(uint256).max);
        uint256 base = vm.envOr("FAIRBIND_VERIFIER_KEY_BASE", uint256(1000));
        for (uint256 i; i < VERIFIERS; i++) {
            address signer = vm.envOr(string.concat("FAIRBIND_VERIFIER_SIGNER_", _decimal(i)), address(0));
            if (signer == address(0)) {
                require(local, "FAIRBIND_VERIFIER_SIGNER_<i>");
                signer = vm.addr(base + i);
            }
            fb.registerVerifier(uint256(1) << 1, signer, 1_000_000);
        }
        fb.checkpointVerifierTree(VOTE);
        fb.checkpointVerifierTree(PROOF);

        // Default vote profile: batched assignment, then receipt-signature terms.
        jr.setBatchTerms(VOTE, _batchTerms(out.vrf));
        _setTerms(jr, VOTE, _voteInput());
        // Proof profile of the UNIQUE kind.
        out.priceVerifier = vm.envOr("FAIRBIND_PRICE_VERIFIER", address(0));
        if (out.priceVerifier == address(0)) {
            require(local, "FAIRBIND_PRICE_VERIFIER");
            out.priceVerifier = vm.deployCode("ExchangeMocks.sol:MockUniquePriceFeed", abi.encode(vm.addr(0x6A2D)));
        }
        bytes32 feedId = vm.envOr("FAIRBIND_FEED_ID", local ? keccak256("BTC/USD") : bytes32(0));
        require(feedId != 0, "FAIRBIND_FEED_ID");
        _setTerms(jr, PROOF, _proofInput(out.priceVerifier, feedId));
        fb.setServiceProfileActive(VOTE, true);
        fb.setServiceProfileActive(PROOF, true);
        vm.stopBroadcast();

        require(jr.getExchangeTerms(VOTE).mode == ExchangeStore.MODE_VOTE_SIG, "vote profile mode");
        require(jr.getExchangeTerms(PROOF).mode == ExchangeStore.MODE_PROOF, "proof profile mode");
        require(fb.getServiceProfile(VOTE).active && fb.getServiceProfile(PROOF).active, "both active");
    }

    /// data-api-design2-v1 (profiles/design2-v1.json) with its origin moved to
    /// the deployment block; sales tiers are not set.
    function _profile(uint256 origin, bytes32 parameterHash)
        internal
        pure
        returns (FairBindCore.ServiceProfileInput memory p)
    {
        p.classId = 1;
        p.predicateId = 0xb1659e2eda6c17f24434be64972e5ce19d44b5b4154752bbe83418276831812f;
        p.canonId = 0x5935caa956c625c8ff2a65a874e14a464e435cc193a0742b6ace012ce81a7a3d;
        p.epochOrigin = uint64(origin);
        p.epochBlocks = 300;
        p.samplePpm = 1_000_000;
        p.effectivePpm = 400_000;
        p.recheckPpm = 200_000;
        p.bucketCapacity = 137;
        p.refillPpmPerBlock = 50_000;
        p.maxRatePpmPerBlock = 60_000;
        p.enforcementBlocks = 31_073;
        p.deferBlocks = 31_073;
        p.retentionBlocks = 31_073;
        p.marginBlocks = 500;
        p.maxRequestBytes = 65_536;
        p.maxResponseBytes = 65_536;
        p.maxEvidenceBytes = 131_072;
        p.maxPublicationCost = 5_000_000;
        p.maxReviewCost = 1_000_000;
        p.maxPurchaseValue = 1_000_000;
        p.maxBadGain = 1_000_000;
        p.sellerPenalty = 322_222_248;
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
        p.beaconDelayBlocks = 768;
        p.claimWindowBlocks = 31_073;
        p.failureLimit = 87;
        p.failureWindowBlocks = 31_073;
        p.maxInconclusivePpm = 200_000;
        p.inconclusiveWindowBlocks = 31_073;
        p.forfeitVerifierPpm = 500_000;
        p.minJudgedCount = 30;
        p.parameterHash = parameterHash;
    }

    function _batchTerms(address vrf) internal view returns (BatchStore.Terms memory t) {
        t.batched = true;
        t.assignDelay = 20;
        t.keeperSlack = 10;
        t.slotValue = 1_000_000;
        t.termsHash = keccak256(
            abi.encode(
                keccak256("fairbind/batch-terms/v1"), VOTE, t.assignDelay, t.keeperSlack, t.depositPpm, t.auditPpm,
                t.contestBlocks, t.sideGainPpm, t.slotValue, vrf, keccak256(IScriptVrf(vrf).publicKey()),
                uint256(IScriptVrf(vrf).responseBlocks()), uint256(IScriptVrf(vrf).deadlineSlackBlocks())
            )
        );
    }

    /// Terms every mode shares. Price caps (smallest token units) and gas
    /// bounds are placeholders until measured.
    function _common(ExchangeStore.Input memory x) internal pure {
        x.priceCap = 4_000_000_000;
        x.gFixTx = 21_000;
        x.gFixCall = 12_000;
        x.bEnv = 100;
        x.gasPriceCap = 1;
        x.l1PriceCap = 1;
        x.pubGas = 2_000_000;
        x.pubBytes = 70_000;
        x.keyGas = 400_000;
        x.keyBytes = 1_200;
        x.keyCap = 401_200;
        x.blockGasShare = 1_000_000;
        x.bundleBlocks = 20;
        x.keyBlocks = 20;
        x.disputeSlack = 10;
        x.postSlack = 30;
        x.confirmBlocks = 10;
        x.g1271 = 50_000;
        x.padLength = 64;
        x.sigLimit = 256;
        x.tag = keccak256("fairbind/response/v1");
        x.bindSlack = 100;
    }

    /// The default vote profile: receipt signatures on, F_max = 30,008 inside
    /// [L_F + marginBlocks - 1, T_hold - 1] = [29,953, 31,072].
    function _voteInput() internal pure returns (ExchangeStore.Input memory x) {
        _common(x);
        x.mode = ExchangeStore.INPUT_VOTE;
        x.bindWindow = 30_008;
    }

    /// The proof profile of the UNIQUE kind: T_p = 300, F_max = L_F,P +
    /// marginBlocks - 1 = (1,111 + 300 + 1) + 499.
    function _proofInput(address verifier, bytes32 feedId) internal pure returns (ExchangeStore.Input memory x) {
        _common(x);
        x.mode = ExchangeStore.INPUT_PROOF;
        x.proofBlocks = 300;
        x.refWindow = 120;
        x.freshWindow = 30;
        x.settleSlack = 30;
        x.maxSkew = 10;
        x.verifier = verifier;
        x.feedId = feedId;
        x.maxUpdateBytes = 512;
        x.tolerancePpm = 1_000;
        x.bindWindow = 1_911;
    }

    function _setTerms(IEvalRouter jr, uint32 id, ExchangeStore.Input memory x) internal {
        x.termsHash = jr.exchangeTermsHash(id, x);
        jr.setExchangeTerms(id, x);
    }

    function _code(address a) internal view returns (bytes memory c) {
        c = a.code;
    }

    function _decimal(uint256 v) internal pure returns (string memory) {
        if (v == 0) return "0";
        bytes memory b;
        while (v != 0) {
            b = abi.encodePacked(bytes1(uint8(48 + v % 10)), b);
            v /= 10;
        }
        return string(b);
    }
}
