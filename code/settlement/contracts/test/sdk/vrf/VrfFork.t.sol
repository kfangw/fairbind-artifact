// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBase } from "../SdkBase.sol";
import { SampledSettlement, SettlementBase, SettlementModule, Leaf, IAuthToken } from "../SampledSettlement.sol";
import { MockAuthToken } from "../MockAuthToken.sol";
import { P5LazerVerifier } from "../../g10/p5/P5Verifiers.sol";

struct VrfProof {
    uint256[2] pk;
    uint256[2] gamma;
    uint256 c;
    uint256 s;
    uint256 seed;
    address uWitness;
    uint256[2] cGammaWitness;
    uint256[2] sHashWitness;
    uint256 zInv;
}

struct RequestCommitment {
    uint64 blockNum;
    uint256 subId;
    uint32 callbackGasLimit;
    uint32 numWords;
    address sender;
    bytes extraArgs;
}

/// The deployed Base coordinator (VRFCoordinatorV2_5_Optimism).
interface IBaseCoordinator {
    function registerProvingKey(uint256[2] calldata publicProvingKey, uint64 maxGas) external;
    function fundSubscriptionWithNative(uint256 subId) external payable;
    function fulfillRandomWords(VrfProof memory proof, RequestCommitment memory rc, bool onlyPremium)
        external
        returns (uint96);
    function s_requestCommitments(uint256 requestId) external view returns (bytes32);
    function getSubscription(uint256 subId)
        external
        view
        returns (uint96 balance, uint96 nativeBalance, uint64 reqCount, address owner, address[] memory consumers);
    function owner() external view returns (address);
}

struct VmLog {
    bytes32[] topics;
    bytes data;
    address emitter;
}

struct CallGas {
    uint64 gasLimit;
    uint64 gasTotalUsed;
    uint64 gasMemoryUsed;
    int64 gasRefunded;
    uint64 gasRemaining;
}

interface ForkVm {
    function ffi(string[] calldata cmd) external returns (bytes memory);
    function envOr(string calldata name, string calldata defaultValue) external view returns (string memory);
    function recordLogs() external;
    function getRecordedLogs() external returns (VmLog[] memory);
    function setBlockhash(uint256 blockNumber, bytes32 blockHash) external;
    function txGasPrice(uint256 newGasPrice) external;
    function lastCallGas() external view returns (CallGas memory);
    function skip(bool skipTest) external;
    function deal(address who, uint256 amount) external;
    function prank(address sender) external;
    function roll(uint256 height) external;
    function store(address target, bytes32 slot, bytes32 value) external;
    function fee(uint256 newBasefee) external;
}

/// The sample-value path against the deployed Chainlink VRF v2.5
/// coordinator on Base, in a fork. Skipped without a fork. VRF_KEY names a
/// file with a throwaway secret (hex), never committed. Transaction gas:
///   VRF_KEY=... FOUNDRY_PROFILE=sdk forge test --match-contract VrfForkTest
///     --match-test 'test_F[12]' --fork-url <Base RPC>
///     --fork-block-number 52977000 --ffi --isolate --gas-price 5000000 -vvvv
/// and all three without --isolate (and without --gas-price) for the
/// coordinator's billed gas (the isolated transaction runs at gas price 0
/// inside the coordinator, so its payment carries no gas part).
///  - request: the settlement contract's own subscription on the real
///    coordinator, requestSample through it, the coordinator's stored
///    request commitment and its RandomWordsRequested event;
///  - fulfillment: a throwaway proving key registered by impersonating the
///    coordinator owner (the Chainlink oracle keys are not used), an ECVRF
///    proof from the G10d prover over the request's pre-seed and a block
///    hash set with vm.setBlockhash (forge has no real hash for the
///    request block), the real coordinator's fulfillRandomWords verifying
///    it and calling back into the settlement contract;
///  - the callback alone, by impersonating the coordinator.
/// Gas is per call as its own transaction (--isolate).
contract VrfForkTest is SdkBase {
    ForkVm internal constant fv = ForkVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    IBaseCoordinator internal constant COORD = IBaseCoordinator(0xd5D517aBE5cF79B7e95eC98dB0f0277788aFF634);
    bytes32 internal constant T_REQ = keccak256(
        "RandomWordsRequested(bytes32,uint256,uint256,uint256,uint16,uint32,uint32,bytes,address)"
    );
    bytes32 internal constant T_FUL = keccak256("RandomWordsFulfilled(uint256,uint256,uint256,uint96,bool,bool,bool)");
    bytes32 internal constant T_L1 = keccak256("L1GasFee(uint256)");
    uint256 internal constant GAS_PRICE = 5_000_000; // 0.005 gwei, the G10d basis
    address internal constant OWNER_EOA = address(uint160(uint256(keccak256("fork owner eoa"))));
    address internal constant REQUESTER = address(uint160(uint256(keccak256("fork requester eoa")))); // sends the sample request
    address internal constant ORACLE = address(uint160(uint256(keccak256("fork oracle eoa")))); // sends the fulfillment

    bool internal forked;
    string internal keyFile;
    uint256[2] internal pk;

    event log_named_uint(string key, uint256 val);

    function setUp() public override {
        forked = address(COORD).code.length != 0;
        if (!forked) return;
        // under --isolate each call is a transaction: run with
        // --gas-price 5000000 and a base fee of the same 0.005 gwei (the
        // G10d basis, the Base minimum), so the coordinator charges at it
        fv.fee(GAS_PRICE);
        // SdkBase's set-up without its mock coordinator; ETH moves from EOAs,
        // since under --isolate every call is a transaction of its own
        vm.warp(VALID_AFTER + 10);
        buyer = vm.addr(buyerKey);
        seller = vm.addr(sellerKey);
        token = new MockAuthToken();
        lazer = new P5LazerVerifier(vm.addr(feedKey), FEED);
        token.mint(seller, 10_000_000);
        token.mint(buyer, 100_000_000);
        keyFile = fv.envOr("VRF_KEY", string(""));
        require(bytes(keyFile).length != 0, "VRF_KEY not set");
        pk = abi.decode(_prover("pubkey", "", ""), (uint256[2]));
        // the owner is a contract; under --isolate a call is a transaction,
        // which a sender with code cannot send (EIP-3607), so an EOA takes
        // its place in the owner slot (ConfirmedOwner slot 0) on the fork
        fv.store(address(COORD), bytes32(0), bytes32(uint256(uint160(OWNER_EOA))));
        fv.deal(OWNER_EOA, 1 ether);
        fv.deal(REQUESTER, 1 ether);
        fv.deal(seller, 1 ether); // every sender of an isolated transaction holds ETH
        fv.deal(buyer, 1 ether);
        fv.prank(OWNER_EOA);
        COORD.registerProvingKey(pk, 2 gwei);
        // a settlement contract on the real coordinator, with its profile and bond
        f = new SampledSettlement(IAuthToken(address(token)), address(COORD), keccak256(abi.encode(pk)));
        m = SettlementModule(address(f));
        address funder = address(0xF00D);
        fv.deal(funder, 10 ether);
        fv.prank(funder);
        COORD.fundSubscriptionWithNative{ value: 1 ether }(f.vrfSubId());
        vm.roll(f.genesis() + f.EPOCH_BLOCKS() + 5);
        epoch = f.epochOf(block.number);
        pidP = _register(address(lazer), 0, 0, 0, 1);
        vm.prank(seller);
        token.approve(address(f), type(uint256).max);
        vm.prank(seller);
        m.depositBond(seller, CAP);
        vm.prank(buyer);
        token.approve(address(f), type(uint256).max);
    }

    function _prover(string memory cmd, string memory a, string memory b) internal returns (bytes memory) {
        bool args = bytes(a).length != 0;
        string[] memory c = new string[](args ? 7 : 5);
        c[0] = "python3";
        c[1] = "-I";
        c[2] = "contracts/test/sdk/vrf/vrf_prove_abi.py";
        c[3] = cmd;
        c[4] = keyFile;
        if (args) {
            c[5] = a;
            c[6] = b;
        }
        return fv.ffi(c);
    }

    function _hex(uint256 x) internal pure returns (string memory s) {
        bytes memory h = "0123456789abcdef";
        bytes memory o = new bytes(66);
        o[0] = "0";
        o[1] = "x";
        for (uint256 i; i < 64; i++) o[65 - i] = h[(x >> (4 * i)) & 15];
        s = string(o);
    }

    function _anchoredEpoch() internal returns (Leaf[] memory ls) {
        ls = new Leaf[](2);
        ls[0].rs = _buy(pidP, _rs(pidP, 0, PRICE), 0);
        ls[1].rs = _buy(pidP, _rs(pidP, 1, PRICE), 1);
        _anchor(pidP, ls);
        vm.roll(f.anchorDeadline(epoch) + 1);
    }

    struct Req {
        uint256 id;
        uint256 preSeed;
        uint64 blockNum;
        uint256 gas;
    }

    function _request() internal returns (Req memory q) {
        fv.recordLogs();
        fv.prank(REQUESTER);
        q.id = m.requestSample(pidP, epoch);
        q.gas = fv.lastCallGas().gasTotalUsed;
        q.blockNum = uint64(block.number);
        VmLog[] memory lg = fv.getRecordedLogs();
        bool seen;
        for (uint256 i; i < lg.length; i++) {
            if (lg[i].emitter == address(COORD) && lg[i].topics[0] == T_REQ) {
                (uint256 id, uint256 pre, uint16 conf, uint32 cb, uint32 nw,) =
                    abi.decode(lg[i].data, (uint256, uint256, uint16, uint32, uint32, bytes));
                require(id == q.id && conf == f.VRF_CONFIRMATIONS() && cb == f.VRF_CALLBACK_GAS() && nw == 1, "event");
                require(lg[i].topics[1] == f.vrfKeyHash() && uint256(lg[i].topics[2]) == f.vrfSubId(), "key, sub");
                require(address(uint160(uint256(lg[i].topics[3]))) == address(f), "sender");
                q.preSeed = pre;
                seen = true;
            }
        }
        require(seen, "RandomWordsRequested");
    }

    function _commitment(Req memory q) internal view returns (RequestCommitment memory rc) {
        rc = RequestCommitment(
            q.blockNum,
            f.vrfSubId(),
            f.VRF_CALLBACK_GAS(),
            1,
            address(f),
            abi.encodeWithSelector(bytes4(keccak256("VRF ExtraArgsV1")), true)
        );
    }

    /// Request creation on the real coordinator: the stored commitment
    /// matches the request; the subscription is the contract's own.
    function test_F1_requestOnTheBaseCoordinator() public {
        if (!forked) return fv.skip(true);
        _anchoredEpoch();
        (,,, address owner, address[] memory consumers) = COORD.getSubscription(f.vrfSubId());
        require(owner == address(f) && consumers.length == 1 && consumers[0] == address(f), "own subscription");
        Req memory q = _request();
        RequestCommitment memory rc = _commitment(q);
        bytes32 want = keccak256(
            abi.encode(q.id, rc.blockNum, rc.subId, rc.callbackGasLimit, rc.numWords, rc.sender, rc.extraArgs)
        );
        require(COORD.s_requestCommitments(q.id) == want, "request commitment");
        emit log_named_uint("requestSample tx gas (real coordinator)", q.gas);
        // a second request for the profile epoch reverts before the coordinator
        vm.expectRevert(SettlementBase.State.selector);
        m.requestSample(pidP, epoch);
    }

    /// Real fulfillment: the coordinator verifies an ECVRF proof under the
    /// registered throwaway key and calls back; R_e is derived from its word.
    function test_F2_fulfillmentThroughTheBaseCoordinator() public {
        if (!forked) return fv.skip(true);
        Leaf[] memory ls = _anchoredEpoch();
        Req memory q = _request();
        vm.roll(q.blockNum + f.VRF_CONFIRMATIONS());
        bytes32 bh = keccak256(abi.encode("fork request block hash", q.blockNum));
        fv.setBlockhash(q.blockNum, bh);
        (VrfProof memory p, uint256 tries) =
            abi.decode(_prover("prove", _hex(q.preSeed), _hex(uint256(bh))), (VrfProof, uint256));
        fv.deal(ORACLE, 1 ether);
        fv.recordLogs();
        fv.prank(ORACLE);
        COORD.fulfillRandomWords(p, _commitment(q), false);
        uint256 fulfillGas = fv.lastCallGas().gasTotalUsed;
        VmLog[] memory lg = fv.getRecordedLogs();
        uint256 output;
        uint256 payment;
        uint256 l1;
        bool ok;
        for (uint256 i; i < lg.length; i++) {
            if (lg[i].emitter != address(COORD)) continue;
            if (lg[i].topics[0] == T_FUL) {
                bool success;
                (output, payment,, success,) = abi.decode(lg[i].data, (uint256, uint96, bool, bool, bool));
                require(uint256(lg[i].topics[1]) == q.id && success, "fulfilled, callback succeeded");
                ok = true;
            } else if (lg[i].topics[0] == T_L1) {
                l1 = abi.decode(lg[i].data, (uint256));
            }
        }
        require(ok, "RandomWordsFulfilled");
        uint256 word = uint256(keccak256(abi.encode(output, uint256(0))));
        uint256 R = f.sampleValue(_ek(pidP, epoch));
        require(R != 0 && R == m.sampleValueOf(f.sampleInput(_ek(pidP, epoch)), q.id, word), "R_e from the word");
        for (uint256 i; i < ls.length; i++) {
            bool want = f.sampledBy(R, ls[i].rs.nonce, PRICE, CAP);
            require(f.isSampled(pidP, ls[i].rs.nonce) == want, "label");
        }
        // native premium 60 %: payment = (gas price * billed gas + L1 fee) * 1.6
        uint256 gp = tx.gasprice;
        uint256 billed = gp == 0 || payment * 100 / 160 < l1 ? 0 : (payment * 100 / 160 - l1) / gp;
        emit log_named_uint("fulfillment gas price (wei)", gp);
        emit log_named_uint("requestSample tx gas (real coordinator)", q.gas);
        emit log_named_uint("fulfillRandomWords tx gas (real coordinator, callback included)", fulfillGas);
        emit log_named_uint("billed gas of the fulfillment", billed);
        emit log_named_uint("hash-to-curve tries", tries);
        emit log_named_uint("payment (wei)", payment);
        emit log_named_uint("L1 fee in the payment (wei)", l1);
    }

    /// The callback alone, the coordinator impersonated, and a stranger's
    /// callback reverting on the fork. Run without --isolate (the
    /// coordinator has code, so it cannot send a transaction of its own);
    /// the gas is the call's execution gas (gasleft before and after).
    function test_F3_callbackByImpersonation() public {
        if (!forked) return fv.skip(true);
        _anchoredEpoch();
        Req memory q = _request();
        uint256[] memory ws = new uint256[](1);
        ws[0] = uint256(keccak256("impersonated word"));
        vm.prank(address(0xBAD));
        vm.expectRevert(SettlementBase.Unauthorized.selector);
        m.rawFulfillRandomWords(q.id, ws);
        fv.prank(address(COORD));
        uint256 g0 = gasleft();
        m.rawFulfillRandomWords(q.id, ws);
        uint256 g = g0 - gasleft();
        require(f.sampleValue(_ek(pidP, epoch)) == m.sampleValueOf(f.sampleInput(_ek(pidP, epoch)), q.id, ws[0]), "value");
        emit log_named_uint("rawFulfillRandomWords call gas (coordinator impersonated)", g);
    }
}
