// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import {FairBindCore} from "../src/FairBindCore.sol";
import { TEST_BEACON_DELAY_BLOCKS } from "./TestProfileConstants.sol";
import {DeployFairBind} from "./DeployFairBind.sol";

import { FairBind } from "../src/FairBind.sol";
import { MockEIP3009Token } from "./MockEIP3009Token.sol";

interface VmM1 {
    function expectRevert(bytes4 selector) external;
    function expectRevert(bytes calldata message) external;
    function prank(address sender) external;
    function warp(uint256 timestamp) external;
    function addr(uint256 key) external returns (address);
    function sign(uint256 key, bytes32 digest) external returns (uint8, bytes32, bytes32);
    function roll(uint256 height) external;
}

contract FairBindM1Test is DeployFairBind {
    VmM1 private constant vm = VmM1(address(uint160(uint256(keccak256("hevm cheat code")))));

    MockEIP3009Token private token;
    FairBind private fairbind;
    uint32 private sellerId;
    address private constant BUYER = address(0xB0B);
    bytes32 private constant CLAIMS = keccak256("claims");

    function setUp() public {
        token = new MockEIP3009Token();
        fairbind = deployFairBind(address(token), address(this), address(0xA11CE), address(0xCAFE));
        fairbind.createDeadlineConfig(1, _deadlines());
        fairbind.createServiceProfile(3, _profile());
        token.mint(address(this), 200_000_000);
        token.approve(address(fairbind), type(uint256).max);
        for (uint32 i; i < 14; i++) {
            fairbind.registerVerifier(uint256(1) << 1, address(uint160(0x1000 + i)), 10_000_000);
        }
        fairbind.checkpointVerifierTree(3);
        fairbind.setServiceProfileActive(3, true);
        sellerId = registerSellerWithBond(fairbind, 3, address(0x515E), CLAIMS, 10_000_000);
        token.mint(BUYER, 100_000);
    }

    function testModulesRejectDirectMutation() public {
        address[10] memory modules = _moduleAddresses();
        bytes[10] memory calls;
        calls[0] = abi.encodeWithSignature("pauseNewSettlements(bool)", true);
        calls[1] = abi.encodeWithSelector(FairBind.settle.selector, sellerId, uint32(3), CLAIMS,
            bytes16(uint128(1)), keccak256("direct"),
            FairBindCore.TransferAuthorization(BUYER, address(fairbind), 1, 0, 100, bytes32(0)), new bytes(65));
        calls[2] = abi.encodeWithSignature("openSample(bytes32)", bytes32(0));
        calls[3] = abi.encodeWithSignature("requestServe(bytes32)", bytes32(0));
        calls[4] = abi.encodeWithSignature("finalizePublication(bytes32)", bytes32(0));
        calls[5] = abi.encodeWithSignature("claimRefund(bytes32)", bytes32(0));
        // timeoutJudge is served by the sampling module since ADR 0021; judge stays here.
        FairBindCore.SignedVerdict memory verdict;
        FairBindCore.FairBindReceipt memory receipt;
        FairBindCore.ReceiptProof memory proof;
        calls[6] = abi.encodeWithSelector(FairBind.judge.selector, verdict, bytes(""), receipt, bytes(""), proof);
        calls[7] = abi.encodeWithSignature("finalizeCase(bytes32)", bytes32(0));
        calls[8] = abi.encodeWithSignature("topUpBond(uint32,uint128)", uint32(1), uint128(1));
        calls[9] = abi.encodeWithSignature("getCase(bytes32)", bytes32(0));
        for (uint256 i; i < 10; i++) {
            (bool ok, bytes memory reason) = modules[i].call(calls[i]);
            require(!ok && reason.length >= 4 && bytes4(reason) == FairBindCore.Unauthorized.selector, "direct mutation");
        }
        (bool okTimeout, bytes memory why) = modules[2].call(abi.encodeWithSignature("timeoutJudge(bytes32)", bytes32(0)));
        require(!okTimeout && bytes4(why) == FairBindCore.Unauthorized.selector, "direct timeout");
    }

    function testUnknownSelectorRejected() public {
        (bool ok,) = address(fairbind).call(hex"deadbeef");
        require(!ok, "unknown selector");
    }

    function testConstructorRejectsSwappedModulesAndTokenMismatch() public {
        address[10] memory modules = _moduleAddresses();
        (modules[0], modules[1]) = (modules[1], modules[0]);
        vm.expectRevert(FairBindCore.InvalidConfiguration.selector);
        new FairBind(address(token), address(this), address(0xA11CE), address(0xCAFE), REWARD_POOL, modules);
        modules = _moduleAddresses();
        vm.expectRevert(FairBindCore.InvalidConfiguration.selector);
        new FairBind(address(0x1234), address(this), address(0xA11CE), address(0xCAFE), REWARD_POOL, modules);
    }

    function testSettlementCallbackCannotReenterRegistry() public {
        token.setCallback(address(fairbind), abi.encodeWithSignature("topUpBond(uint32,uint128)", uint32(1), uint128(1)));
        _settle(bytes16(uint128(91)), keccak256("callback"), 10_000);
        require(!token.callbackSuccess(), "reentered");
        require(token.callbackError() == FairBindCore.InvalidConfiguration.selector, "shared lock");
        require(token.balanceOf(address(fairbind)) == 150_010_000, "custody");
    }

    function _moduleAddresses() private view returns (address[10] memory modules) {
        modules = [fairbind.registryModule(), fairbind.settlementModule(), fairbind.samplingModule(),
            fairbind.deliveryModule(), fairbind.publicationModule(), fairbind.recoveryModule(), fairbind.judgmentModule(), fairbind.reviewModule(),
            fairbind.bondModule(), fairbind.lensModule()];
    }

    function testSolidityIdentifierVector() public pure {
        bytes32 keyId = keccak256(
            abi.encode(
                keccak256("fairbind/key/v1"),
                uint256(31337),
                address(0x1111111111111111111111111111111111111111),
                uint32(7),
                address(0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266),
                bytes16(hex"00112233445566778899aabbccddeeff")
            )
        );
        require(
            keyId == 0x60f593c6957ce4344a3cfd34999d975e2d30057a7bd2df9e3bb0c836edbbb7e7,
            "key vector"
        );

        bytes32 nonce = keccak256(
            abi.encode(
                keccak256("fairbind/v1"),
                uint256(31337),
                address(0x1111111111111111111111111111111111111111),
                uint32(7),
                uint32(3),
                bytes32(0xa17e50616e113c008c12499c061238d6ffac56c9396f4532ab080688f15ab4cf),
                address(0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266),
                bytes16(hex"00112233445566778899aabbccddeeff"),
                bytes32(0x6e6717945809f177d93714f3750a01da09d79ca8245518f15a475df062373246)
            )
        );
        require(
            nonce == 0x756eab6ff2c296fb7c9062d26fb7b473805da0509b1ac8e0331e7479d96f6d42,
            "nonce vector"
        );
    }

    function testSettlementRecordsFundsAndConsumesBucket() public {
        (bytes32 nonce, bytes32 keyId) = _settle(bytes16(uint128(1)), keccak256("request"), 10_000);
        FairBindCore.PurchaseView memory purchase = fairbind.getPurchase(nonce);
        require(purchase.keyId == keyId, "key");
        require(purchase.buyer == BUYER && purchase.value == 10_000, "purchase");
        require(purchase.financialState == uint8(FairBindCore.FinancialState.DEFERRED), "state");
        require(fairbind.purchaseByKey(keyId) == nonce, "lookup");
        require(token.balanceOf(address(fairbind)) == 150_010_000, "custody");

        FairBindCore.SellerQuote memory quote = fairbind.quoteSeller(sellerId);
        require(quote.remaining == 19, "bucket");
    }

    function testDuplicateKeyCannotChangeRequest() public {
        bytes16 key = bytes16(uint128(2));
        _settle(key, keccak256("first"), 10_000);
        bytes32 secondRequest = keccak256("second");
        bytes32 secondNonce = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, secondRequest);
        vm.expectRevert(FairBindCore.KeyAlreadyUsed.selector);
        _submit(key, secondRequest, 10_000, secondNonce);
    }

    function testTokenFailureRollsBackIdentifiersAndBucket() public {
        bytes16 key = bytes16(uint128(3));
        bytes32 requestHash = keccak256("failure");
        bytes32 keyId = fairbind.deriveKeyId(sellerId, BUYER, key);
        bytes32 nonce = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, requestHash);
        token.setFailAuthorization(true);
        vm.expectRevert(FairBindCore.TransferFailed.selector);
        _submit(key, requestHash, 10_000, nonce);
        require(fairbind.purchaseByKey(keyId) == bytes32(0), "key rollback");
        require(fairbind.getPurchase(nonce).nonce == bytes32(0), "purchase rollback");
        require(fairbind.quoteSeller(sellerId).remaining == 20, "bucket rollback");
    }

    function testFuzzInvalidValue(uint128 excess) public {
        bytes16 key = bytes16(uint128(50));
        bytes32 req = keccak256("bad-value");
        bytes32 n = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, req);
        vm.expectRevert(FairBindCore.ValueTooLarge.selector);
        _submit(key, req, 10_001 + uint256(excess), n);
        require(fairbind.getPurchase(n).nonce == bytes32(0), "no record");
    }

    function testZeroValueAndWrongNonceReject() public {
        bytes16 key = bytes16(uint128(51));
        bytes32 req = keccak256("invalid");
        bytes32 n = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, req);
        vm.expectRevert(FairBindCore.ValueTooLarge.selector);
        _submit(key, req, 0, n);
        vm.expectRevert(FairBindCore.NonceMismatch.selector);
        _submit(key, req, 1, bytes32(uint256(n) ^ 1));
    }

    function testPausedInactiveProfileAndSellerReject() public {
        bytes16 key = bytes16(uint128(52));
        bytes32 req = keccak256("paused");
        bytes32 n = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, req);
        fairbind.pauseNewSettlements(true);
        vm.expectRevert(FairBindCore.Paused.selector);
        _submit(key, req, 1, n);
        fairbind.pauseNewSettlements(false);
        fairbind.setServiceProfileActive(3, false);
        vm.expectRevert(FairBindCore.InactiveProfile.selector);
        _submit(key, req, 1, n);
        fairbind.setServiceProfileActive(3, true);
        fairbind.requestSellerExit(sellerId);
        vm.expectRevert(FairBindCore.SellerInactive.selector);
        _submit(key, req, 1, n);
    }

    function testAuthorizationBoundaries() public {
        bytes16 key = bytes16(uint128(53));
        bytes32 req = keccak256("expiry");
        bytes32 n = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, req);
        vm.warp(100);
        vm.expectRevert(FairBindCore.AuthorizationExpired.selector);
        _submit(key, req, 1, n);
        vm.warp(0);
        vm.expectRevert(FairBindCore.AuthorizationExpired.selector);
        _submit(key, req, 1, n);
        vm.warp(99);
        _submit(key, req, 1, n);
    }

    function testFuzzRollbackThenRetry(bytes16 key, bytes32 req, uint16 rawValue) public {
        uint256 value = uint256(rawValue) % 10_000 + 1;
        bytes32 n = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, req);
        uint256 custody = token.balanceOf(address(fairbind));
        uint256 buyer = token.balanceOf(BUYER);
        token.setFailAuthorization(true);
        vm.expectRevert(FairBindCore.TransferFailed.selector);
        _submit(key, req, value, n);
        require(token.balanceOf(address(fairbind)) == custody, "custody rollback");
        require(token.balanceOf(BUYER) == buyer && !token.used(n), "token rollback");
        require(fairbind.quoteSeller(sellerId).remaining == 20, "bucket rollback");
        token.setFailAuthorization(false);
        _submit(key, req, value, n);
        require(token.balanceOf(address(fairbind)) == custody + value, "custody");
        require(token.balanceOf(BUYER) == buyer - value, "payer");
        vm.expectRevert(FairBindCore.KeyAlreadyUsed.selector);
        _submit(key, req, value, n);
    }

    function testFuzzBurstConservationAndRefill(uint8 rawCount) public {
        uint256 count = uint256(rawCount) % 20 + 1;
        uint256 beforeBalance = token.balanceOf(address(fairbind));
        for (uint256 i; i < count; i++) {
            _settle(bytes16(uint128(100 + i)), keccak256(abi.encode(i)), 100);
        }
        require(token.balanceOf(address(fairbind)) == beforeBalance + count * 100, "sum");
        require(fairbind.quoteSeller(sellerId).remaining == 20 - count, "consumption");
        vm.roll(block.number + 400);
        require(fairbind.quoteSeller(sellerId).remaining == 20, "refill cap");
    }

    function testTwentyFirstSameBlockSettlementRejects() public {
        for (uint128 i; i < 20; i++) {
            _settle(bytes16(i + 200), keccak256(abi.encode(i)), 1);
        }
        bytes16 key = bytes16(uint128(250));
        bytes32 req = keccak256("burst");
        bytes32 n = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, req);
        vm.expectRevert(FairBindCore.RateLimitExceeded.selector);
        _submit(key, req, 1, n);
        require(!token.used(n), "rejected token nonce");
    }

    function testSignedAuthorizationRejectsTamperingThenAcceptsOriginal() public {
        token.setVerifySignatures(true);
        uint256 testKey = 0x515151;
        address payer = vm.addr(testKey);
        token.mint(payer, 20_000);
        bytes16 key = bytes16(uint128(600));
        bytes32 req = keccak256("signed");
        bytes32 n = fairbind.deriveNonce(sellerId, 3, CLAIMS, payer, key, req);
        FairBindCore.TransferAuthorization memory a =
            FairBindCore.TransferAuthorization(payer, address(fairbind), 10_000, 0, 100, n);
        bytes32 digest = token.receiveAuthorizationDigest(payer, address(fairbind), 10_000, 0, 100, n);
        (uint8 v, bytes32 rr, bytes32 ss) = vm.sign(testKey, digest);
        bytes memory signature = abi.encodePacked(rr, ss, v);
        a.value = 9_999;
        vm.expectRevert(FairBindCore.TransferFailed.selector);
        fairbind.settle(sellerId, 3, CLAIMS, key, req, a, signature);
        require(!token.used(n), "invalid signature consumed nonce");
        a.value = 10_000;
        fairbind.settle(sellerId, 3, CLAIMS, key, req, a, signature);
        require(token.balanceOf(payer) == 10_000, "signed payment");
        vm.expectRevert(FairBindCore.KeyAlreadyUsed.selector);
        fairbind.settle(sellerId, 3, CLAIMS, key, req, a, signature);
    }

    /// ADR 0016: the authorization a buyer signs for settle is a
    /// ReceiveWithAuthorization naming the contract as payee. When settle
    /// reverts, the authorization is public in the calldata, yet a direct token
    /// call from anyone else cannot spend it: receiveWithAuthorization requires
    /// the payee as caller, and transferWithAuthorization checks a different
    /// typed message.
    function testStrandedAuthorizationCannotBeSpentOutsideSettle() public {
        for (uint128 i; i < 20; i++) {
            _settle(bytes16(i + 700), keccak256(abi.encode("fill", i)), 1);
        }
        token.setVerifySignatures(true);
        uint256 testKey = 0x525252;
        address payer = vm.addr(testKey);
        token.mint(payer, 20_000);
        bytes16 key = bytes16(uint128(760));
        bytes32 req = keccak256("stranded");
        bytes32 n = fairbind.deriveNonce(sellerId, 3, CLAIMS, payer, key, req);
        FairBindCore.TransferAuthorization memory a =
            FairBindCore.TransferAuthorization(payer, address(fairbind), 10_000, 0, 100, n);
        (uint8 v, bytes32 rr, bytes32 ss) =
            vm.sign(testKey, token.receiveAuthorizationDigest(payer, address(fairbind), 10_000, 0, 100, n));
        bytes memory signature = abi.encodePacked(rr, ss, v);
        vm.expectRevert(FairBindCore.RateLimitExceeded.selector);
        fairbind.settle(sellerId, 3, CLAIMS, key, req, a, signature);
        uint256 custody = token.balanceOf(address(fairbind));

        vm.prank(address(0xFAC));
        vm.expectRevert(bytes("caller must be the payee"));
        token.receiveWithAuthorization(payer, address(fairbind), 10_000, 0, 100, n, v, rr, ss);
        vm.expectRevert(bytes("caller must be the payee"));
        token.receiveWithAuthorization(payer, address(fairbind), 10_000, 0, 100, n, v, rr, ss);
        vm.prank(address(0xFAC));
        vm.expectRevert(bytes("signature"));
        token.transferWithAuthorization(payer, address(fairbind), 10_000, 0, 100, n, v, rr, ss);
        require(!token.used(n), "authorization unspent");
        require(token.balanceOf(payer) == 20_000, "buyer untouched");
        require(token.balanceOf(address(fairbind)) == custody, "custody untouched");
        require(fairbind.getPurchase(n).nonce == bytes32(0), "no purchase");

        vm.roll(block.number + 400);
        fairbind.settle(sellerId, 3, CLAIMS, key, req, a, signature);
        require(fairbind.getPurchase(n).buyer == payer, "settled through settle");
        require(token.balanceOf(payer) == 10_000, "buyer paid once");
        require(token.balanceOf(address(fairbind)) == custody + 10_000, "custody credited");
    }

    /// ADR 0016 regression: the old wire signed TransferWithAuthorization.
    /// Anyone holding such an authorization can move the buyer's funds into
    /// the contract with no purchase record, and settle no longer accepts it.
    function testTransferTypedAuthorizationIsStrandableAndRejectedBySettle() public {
        token.setVerifySignatures(true);
        uint256 testKey = 0x535353;
        address payer = vm.addr(testKey);
        token.mint(payer, 20_000);
        bytes16 key = bytes16(uint128(770));
        bytes32 req = keccak256("transfer-typed");
        bytes32 n = fairbind.deriveNonce(sellerId, 3, CLAIMS, payer, key, req);
        (uint8 v, bytes32 rr, bytes32 ss) =
            vm.sign(testKey, token.authorizationDigest(payer, address(fairbind), 10_000, 0, 100, n));
        FairBindCore.TransferAuthorization memory a =
            FairBindCore.TransferAuthorization(payer, address(fairbind), 10_000, 0, 100, n);
        vm.expectRevert(FairBindCore.TransferFailed.selector);
        fairbind.settle(sellerId, 3, CLAIMS, key, req, a, abi.encodePacked(rr, ss, v));
        require(!token.used(n), "settle did not spend it");

        uint256 custody = token.balanceOf(address(fairbind));
        vm.prank(address(0xFAC));
        token.transferWithAuthorization(payer, address(fairbind), 10_000, 0, 100, n, v, rr, ss);
        require(token.balanceOf(address(fairbind)) == custody + 10_000, "moved into custody");
        require(fairbind.getPurchase(n).nonce == bytes32(0), "without a purchase record");
    }

    // A bounded stateful action sequence, distinct from a full protocol invariant harness.
    function testFuzzSettlementActionSequence(bytes32 seed) public {
        token.mint(BUYER, 1_000_000);
        uint256 buyerBefore = token.balanceOf(BUYER);
        uint256 custodyBefore = token.balanceOf(address(fairbind));
        uint256 paid;
        bool[32] memory accepted;
        for (uint256 i; i < 84; i++) {
            uint256 action = uint256(keccak256(abi.encode(seed, i)));
            vm.roll(block.number + (action % 101));
            uint256 slot = (action >> 8) % 32;
            bytes16 key = bytes16(uint128(1000 + slot));
            bytes32 requestHash = keccak256(abi.encode(slot));
            bytes32 nonce = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, requestHash);
            uint256 value = (action >> 16) % 10_000 + 1;
            token.setFailAuthorization((action >> 32) % 4 == 0);
            uint256 bucketBefore = fairbind.quoteSeller(sellerId).remaining;
            FairBindCore.TransferAuthorization memory a = FairBindCore.TransferAuthorization(
                BUYER, address(fairbind), value, 0, 100, nonce);
            (bool ok,) = address(fairbind).call(abi.encodeWithSelector(
                FairBind.settle.selector, sellerId, uint32(3), CLAIMS, key, requestHash, a, new bytes(65)));
            if (ok) {
                require(!accepted[slot], "duplicate accepted");
                accepted[slot] = true;
                paid += value;
                require(fairbind.getPurchase(nonce).value == value, "record amount");
            } else {
                require(fairbind.quoteSeller(sellerId).remaining == bucketBefore, "failed bucket mutation");
            }
            require(token.used(nonce) == accepted[slot], "nonce divergence");
            require((fairbind.purchaseByKey(fairbind.deriveKeyId(sellerId, BUYER, key)) == nonce)
                == accepted[slot], "key divergence");
            require(token.balanceOf(BUYER) == buyerBefore - paid, "buyer conservation");
            require(token.balanceOf(address(fairbind)) == custodyBefore + paid, "custody conservation");
        }
    }

    function _settle(bytes16 key, bytes32 requestHash, uint256 value)
        internal
        returns (bytes32, bytes32)
    {
        bytes32 nonce = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, requestHash);
        return _submit(key, requestHash, value, nonce);
    }

    function _submit(bytes16 key, bytes32 requestHash, uint256 value, bytes32 nonce)
        internal
        returns (bytes32, bytes32)
    {
        FairBindCore.TransferAuthorization memory authorization = FairBindCore.TransferAuthorization({
            from: BUYER,
            to: address(fairbind),
            value: value,
            validAfter: 0,
            validBefore: 100,
            nonce: nonce
        });
        return fairbind.settle(sellerId, 3, CLAIMS, key, requestHash, authorization, new bytes(65));
    }

    function _deadlines() internal pure returns (FairBindCore.DeadlineConfig memory d) {
        d = FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600);
    }

    function _profile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p.classId = 1;
        p.predicateId = keccak256("predicate");
        p.canonId = keccak256("fairbind/http-canon/v1");
        p.epochOrigin = 1;
        p.epochBlocks = 300;
        p.samplePpm = 100_000;
        p.effectivePpm = 40_000;
        p.recheckPpm = 200_000;
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
        p.freezeOnInitialFail = false;
        p.minJudgedCount = 1;
        p.beaconDelayBlocks = TEST_BEACON_DELAY_BLOCKS;
        p.parameterHash = keccak256("profile");
    }
}
