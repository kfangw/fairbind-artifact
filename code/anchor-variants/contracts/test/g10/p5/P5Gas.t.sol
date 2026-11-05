// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { G10Base, G10Sig } from "../G10Base.sol";
import { EcVrf, EcVrfProver } from "../g10c/EcVrf.sol";
import { SyntheticHistoryFixture as F } from "../../g7/SyntheticHistoryFixture.sol";
import {
    P5Ref, IUsdcP5, P5Rs, P5Leaf, P5Unit, P5Item, P5Rel, P5Open
} from "./P5Ref.sol";
import { P5LazerVerifier, P5StorageVerifier } from "./P5Verifiers.sol";

interface P5Vm {
    function store(address target, bytes32 slot, bytes32 value) external;
    function addr(uint256 key) external returns (address);
    function sign(uint256 key, bytes32 digest) external returns (uint8, bytes32, bytes32);
    function roll(uint256 height) external;
    function prank(address sender) external;
    function deal(address who, uint256 amount) external;
    function snapshotState() external returns (uint256);
    function revertToState(uint256 id) external returns (bool);
}

interface IVrfSubscriptions {
    function createSubscription() external returns (uint256 subId);
    function addConsumer(uint256 subId, address consumer) external;
    function fundSubscriptionWithNative(uint256 subId) external payable;
}

/// Gas of the rule's per-event transactions on a Base fork (run with
/// --fork-url, --fork-block-number 52977000 and --isolate). Every measured
/// call is logged with its transaction gas and recorded for the L1 fee.
contract P5GasTest is G10Base {
    IUsdcP5 internal constant USDC = IUsdcP5(0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913);
    address internal constant COORD = 0xd5D517aBE5cF79B7e95eC98dB0f0277788aFF634;
    bytes32 internal constant LANE_2GWEI = 0x00b81b5a830cb0a4009fbd8904de511e28631e62ce5ad231373d3cdad373ccab;
    P5Vm internal constant pv = P5Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 internal constant BALANCE_SLOT = 9; // FiatTokenV2_2 balanceAndBlacklistStates

    bytes32 internal constant ACK_TYPEHASH = keccak256(
        "BuyerAck(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 profileId,bytes32 codeHash,bytes32 receiptHash,bool accepted)"
    );
    bytes32 internal constant UNIT_TYPEHASH = keccak256(
        "AnchorUnit(bytes32 profileId,uint32 epoch,uint32 count,uint32 unitNo,bytes32 firstNonce,bytes32 lastNonce,bytes32 root,bytes32 root0,bytes32 snapshotHash)"
    );
    bytes32 internal constant TAG = keccak256("p5/response/v1");
    uint64 internal constant PRICE = 10_000; // 0.01 USDC
    uint64 internal constant CAP = 1_000_000; // V = 1 USDC
    uint64 internal constant VALID_AFTER = 1_792_743_000;
    uint32 internal constant SET = 1;
    uint32 internal constant LAZER_FEED = 1;
    uint256 internal constant NP = 8; // profiles in the set

    P5Ref internal f;
    P5LazerVerifier internal lazer;
    P5StorageVerifier internal stor;
    uint256 internal buyerKey;
    address internal buyer;
    address internal fac;
    uint256 internal lazerKey;
    uint256 internal vrfKey;
    uint256[2] internal vrfPk;
    address internal snapKey;
    bytes32[] internal setPids;
    uint256[] internal setKeys;
    bytes32 internal pidD; // direct, ciphertext profile, tier 1a verifier
    uint256 internal keyD;
    bytes32 internal pidT0; // direct, tier 0 verifier
    uint256 internal keyT0;
    uint256 internal epoch;

    function _setUsdc(address who, uint256 amount) internal {
        pv.store(address(USDC), keccak256(abi.encode(who, BALANCE_SLOT)), bytes32(amount));
        require(USDC.balanceOf(who) == amount, "USDC balance slot");
    }

    function _account(bytes32 pid) internal pure returns (address) {
        return address(uint160(uint256(keccak256(abi.encode("p5 account", pid)))));
    }

    function setUp() public {
        require(address(USDC).code.length > 0, "run on a Base fork");
        buyerKey = uint256(keccak256("p5 throwaway buyer key, fork only"));
        buyer = pv.addr(buyerKey);
        fac = address(uint160(uint256(keccak256("p5 facilitator"))));
        lazerKey = uint256(keccak256("p5 throwaway feed key, fork only"));
        vrfKey = uint256(keccak256("p5 throwaway vrf key, fork only")) % EcVrf.N;
        vrfPk = EcVrfProver.publicKey(vrfKey);
        require(vrfPk[0] < EcVrf.N, "vrf key");
        f = new P5Ref(USDC, vrfPk[0], vrfPk[1], COORD, LANE_2GWEI);
        lazer = new P5LazerVerifier(pv.addr(lazerKey), LAZER_FEED);
        stor = new P5StorageVerifier();
        pv.roll(f.genesis() + f.EPOCH_BLOCKS() + 5); // epoch 1
        epoch = f.epochOf(block.number);
        f.registerSet(SET, fac);
        snapKey = pv.addr(uint256(keccak256("p5 snapshot signer")));
        f.registerKey(snapKey);
        for (uint256 i; i < NP; i++) {
            bytes32 pid = keccak256(abi.encode("p5 set profile", i));
            uint256 k = uint256(keccak256(abi.encode("p5 throwaway unit key", i)));
            setPids.push(pid);
            setKeys.push(k);
            f.registerProfile(pid, _account(pid), pv.addr(k), CAP, SET, address(lazer), 200_000, 0);
            _setUsdc(_account(pid), 50_000_000); // payout address paid before
        }
        pidD = keccak256("p5 direct profile");
        keyD = uint256(keccak256("p5 throwaway unit key D"));
        f.registerProfile(pidD, _account(pidD), pv.addr(keyD), CAP, 0, address(lazer), 200_000, 2);
        _setUsdc(_account(pidD), 50_000_000);
        pidT0 = keccak256("p5 tier-0 profile");
        keyT0 = uint256(keccak256("p5 throwaway unit key T0"));
        f.registerProfile(pidT0, _account(pidT0), pv.addr(keyT0), CAP, 0, address(stor), 2_000_000, 1);
        _setUsdc(_account(pidT0), 50_000_000);
        _setUsdc(address(f), 500_000_000); // the pool already holds proceeds
        _setUsdc(buyer, 1_000_000_000);
        pv.prank(buyer);
        USDC.approve(address(f), type(uint256).max);
        pv.roll(block.number + 5);
    }

    // ------------------------------------------------------------ leaves

    function _nonce(bytes32 pid, uint256 i) internal pure returns (bytes32) {
        return bytes32((uint256(keccak256(abi.encode(pid, "n"))) >> 64 << 64) | (i + 1));
    }

    function _rs(bytes32 pid, uint256 i, uint64 amount) internal pure returns (P5Rs memory r) {
        r.nonce = _nonce(pid, i);
        r.amount = amount;
        r.requestHash = keccak256(abi.encode("req", pid, i));
        r.responseHash = keccak256(abi.encode("resp", pid, i));
        r.ctHash = keccak256(abi.encode("ct", pid, i));
        r.keyHash = keccak256(abi.encode("k", pid, i));
        r.claimsHash = keccak256("claims: host and model");
        r.materialCommit = keccak256(abi.encode("material", pid, i));
    }

    /// Settles every leaf (signed leaves carry a binding hash, as a signing
    /// client's sales do) and signs sigB for the signed ones.
    function _settle(bytes32 pid, P5Leaf[] memory ls, bool[] memory signed) internal {
        for (uint256 i; i < ls.length; i++) {
            P5Rs memory r = ls[i].rs;
            bytes32 bh = signed[i] ? keccak256(abi.encode(r.requestHash, r.claimsHash)) : bytes32(0);
            f.settleFixture(pid, r.nonce, buyer, r.amount, VALID_AFTER, bh);
        }
    }

    function _signLeaves(bytes32 pid, P5Leaf[] memory ls, bool[] memory signed) internal {
        bytes32 ch = f.profCodeHash(pid);
        bytes32 dom = f.DOMAIN_SEPARATOR();
        for (uint256 i; i < ls.length; i++) {
            if (!signed[i]) continue;
            P5Rs memory r = ls[i].rs;
            bytes32 hRS = f.rsHash(pid, ch, r);
            bytes32 d = G10Sig.typed(
                dom,
                keccak256(
                    abi.encode(
                        ACK_TYPEHASH, r.nonce, uint256(r.amount), r.requestHash, r.responseHash, r.ctHash, pid, ch, hRS, ls[i].accept
                    )
                )
            );
            ls[i].sigB = _sig(buyerKey, d);
        }
    }

    function _plainLeaves(bytes32 pid, uint256 m, bool signed) internal returns (P5Leaf[] memory ls) {
        ls = new P5Leaf[](m);
        bool[] memory sg = new bool[](m);
        for (uint256 i; i < m; i++) {
            ls[i].rs = _rs(pid, i, PRICE);
            sg[i] = signed;
        }
        _settle(pid, ls, sg);
        _signLeaves(pid, ls, sg);
    }

    function _leafHashes(bytes32 pid, P5Leaf[] memory ls) internal view returns (bytes32[] memory lv, bytes32[] memory lv0) {
        bytes32 ch = f.profCodeHash(pid);
        lv = new bytes32[](ls.length);
        lv0 = new bytes32[](ls.length);
        for (uint256 i; i < ls.length; i++) {
            bytes32 hRS = ls[i].unanswered == 0 ? f.rsHash(pid, ch, ls[i].rs) : bytes32(0);
            bytes32 l0 = f.leaf0Of(ls[i].rs.nonce, hRS, ls[i].unanswered);
            bool beta = ls[i].sigB.length != 0 && ls[i].unanswered == 0;
            lv0[i] = l0;
            lv[i] = f.leafOf(l0, ls[i].sigB.length != 0 ? keccak256(ls[i].sigB) : bytes32(0), beta, beta && ls[i].accept);
        }
    }

    function _rootOf(bytes32[] memory level) internal pure returns (bytes32) {
        bytes32[] memory l = new bytes32[](level.length);
        for (uint256 i; i < level.length; i++) l[i] = level[i];
        bytes32[][] memory lv = _levels(l);
        return lv[lv.length - 1][0];
    }

    function _unit(bytes32 pid, uint256 key, P5Leaf[] memory ls) internal returns (P5Unit memory u) {
        u.pid = pid;
        u.epoch = uint32(epoch);
        u.count = uint32(ls.length);
        u.unitNo = 1;
        u.first = ls[0].rs.nonce;
        u.last = ls[ls.length - 1].rs.nonce;
        (bytes32[] memory lv, bytes32[] memory lv0) = _leafHashes(pid, ls);
        u.root = _rootOf(lv);
        u.root0 = _rootOf(lv0);
        u.snapshot = new address[](1);
        u.snapshot[0] = snapKey;
        u.leaves = ls;
        bytes32 d = G10Sig.typed(
            f.DOMAIN_SEPARATOR(),
            keccak256(
                abi.encode(
                    UNIT_TYPEHASH, pid, u.epoch, u.count, u.unitNo, u.first, u.last, u.root, u.root0, keccak256(abi.encode(u.snapshot))
                )
            )
        );
        u.sellerSig = _sig(key, d);
    }

    function _open(bytes32 pid, P5Leaf[] memory ls, uint256 idx) internal view returns (P5Open memory o) {
        (bytes32[] memory lv,) = _leafHashes(pid, ls);
        bytes32[][] memory levels = _levels(lv);
        o.pid = pid;
        o.epoch = uint32(epoch);
        o.unitNo = 1;
        o.index = idx;
        o.rs = ls[idx].rs;
        o.unanswered = ls[idx].unanswered;
        o.sigHash = ls[idx].sigB.length != 0 ? keccak256(ls[idx].sigB) : bytes32(0);
        o.beta = ls[idx].sigB.length != 0;
        o.accept = o.beta && ls[idx].accept;
        o.path = _path(levels, idx);
    }

    function _toAnchorTime() internal {
        pv.roll(f.lastBlock(epoch) + f.D_INC() + 1);
    }

    // ------------------------------------------------- anchor: direct, bundle

    function _selfSubmit(uint256 m, bool signed) internal {
        uint256 id = pv.snapshotState();
        P5Leaf[] memory ls = _plainLeaves(pidD, m, signed);
        P5Unit memory u = _unit(pidD, keyD, ls);
        pv.roll(f.facilitatorDeadline(epoch) + 1); // the seller's own path after A^F_e
        uint256 g = gasleft();
        uint8 r = f.anchorUnit(u);
        g -= gasleft();
        _rec(address(f), abi.encodeCall(f.anchorUnit, (u)));
        require(r == 0, "unit stored");
        _log(string.concat("P5 self-submission, one unit, m=", _u(m), signed ? " all signed" : " none signed", ", tx gas"), g);
        pv.revertToState(id);
    }

    function test_gas_selfSubmission() public {
        _selfSubmit(8, true);
        _selfSubmit(8, false);
        _selfSubmit(32, true);
        _selfSubmit(32, false);
        _selfSubmit(128, true);
    }

    function _bundleUnits(uint256 np, uint256 m, bool signed) internal returns (P5Unit[] memory us) {
        us = new P5Unit[](np);
        for (uint256 p; p < np; p++) {
            P5Leaf[] memory ls = _plainLeaves(setPids[p], m, signed);
            us[p] = _unit(setPids[p], setKeys[p], ls);
        }
    }

    function _bundle(uint256 np, uint256 m, bool signed, bool oneBad) internal {
        uint256 id = pv.snapshotState();
        P5Unit[] memory us = _bundleUnits(np, m, signed);
        if (oneBad) us[np - 1].sellerSig = _sig(setKeys[0], keccak256("not the unit"));
        _toAnchorTime();
        pv.prank(fac);
        uint256 g = gasleft();
        uint256 stored = f.anchorBundle(SET, us);
        g -= gasleft();
        _rec(address(f), abi.encodeCall(f.anchorBundle, (SET, us)));
        require(stored == (oneBad ? np - 1 : np), "units stored");
        _log(
            string.concat(
                "P5 bundled anchor, P=", _u(np), " profiles, m=", _u(m), signed ? " all signed" : " none signed",
                oneBad ? ", last unit rejected (bad seller signature)" : "", ", tx gas"
            ),
            g
        );
        pv.revertToState(id);
    }

    function test_gas_bundleAnchor() public {
        uint256[4] memory ps = [uint256(1), 2, 4, 8];
        for (uint256 i; i < 4; i++) {
            _bundle(ps[i], 8, true, false);
            _bundle(ps[i], 32, true, false);
            _bundle(ps[i], 32, false, false);
        }
        _bundle(8, 32, true, true);
    }

    // ------------------------------------------------------ sample values

    function _tries(bytes32 alpha) internal view returns (uint256 t) {
        uint256 P = EcVrf.P;
        uint256 x = uint256(keccak256(abi.encodePacked(uint256(1), vrfPk[0], vrfPk[1], alpha))) % P;
        for (t = 1;; t++) {
            uint256 y2 = addmod(mulmod(mulmod(x, x, P), x, P), 7, P);
            uint256 y = EcVrf.modexp(y2, EcVrf.SQRT_EXP, P);
            if (mulmod(y, y, P) == y2) return t;
            x = uint256(keccak256(abi.encodePacked(x))) % P;
        }
    }

    function _fulfill(bytes32 key, string memory tag) internal {
        bytes32 alpha = f.alphaOf(key, epoch);
        uint256 m = uint256(keccak256(abi.encode(vrfKey, alpha, "p5 vrf nonce"))) % EcVrf.N;
        EcVrf.Proof memory pr = EcVrfProver.prove(vrfKey, vrfPk, alpha, m, pv.addr(m));
        pv.roll(block.number + 2);
        uint256 g = gasleft();
        f.fulfillSample(key, epoch, pr);
        g -= gasleft();
        _rec(address(f), abi.encodeCall(f.fulfillSample, (key, epoch, pr)));
        require(f.sampleValue(keccak256(abi.encode(key, epoch))) != 0, "value stored");
        _log(string.concat("P5 ", tag, " value acceptance (ECVRF), tries ", _u(_tries(alpha)), ", tx gas"), g);
    }

    function test_gas_sharedVrf() public {
        uint256 id0 = pv.snapshotState();
        // the set: settlements in two profiles; the request needs no anchor
        _plainLeaves(setPids[0], 8, true);
        _plainLeaves(setPids[1], 8, true);
        pv.roll(f.anchorDeadline(epoch) + 1);
        uint256 id = pv.snapshotState();
        uint256 g = gasleft();
        f.requestSampleSet(SET, epoch);
        g -= gasleft();
        _rec(address(f), abi.encodeCall(f.requestSampleSet, (SET, epoch)));
        _log("P5 shared SAMPLE request (set), tx gas", g);
        _fulfill(bytes32(uint256(SET)), "shared");
        // the same value acceptance at other set ids, for the spread of tries
        for (uint32 s = 2; s < 10; s++) {
            pv.revertToState(id0);
            f.registerSet(s, fac);
            bytes32 pe = keccak256(abi.encode("p5 extra", s));
            f.registerProfile(pe, _account(pe), fac, CAP, s, address(lazer), 1, 0);
            f.settleFixture(pe, bytes32(uint256(1)), buyer, PRICE, VALID_AFTER, 0);
            pv.roll(f.anchorDeadline(epoch) + 1);
            f.requestSampleSet(s, epoch);
            _fulfill(bytes32(uint256(s)), string.concat("shared (set ", _u(s), ")"));
        }
        pv.revertToState(id);
        // Chainlink VRF v2.5 through the deployed coordinator, native payment
        {
            address owner = address(uint160(uint256(keccak256("p5 subscription owner"))));
            pv.deal(owner, 2 ether);
            pv.prank(owner);
            uint256 sub = IVrfSubscriptions(COORD).createSubscription();
            pv.prank(owner);
            IVrfSubscriptions(COORD).addConsumer(sub, address(f));
            pv.prank(owner);
            IVrfSubscriptions(COORD).fundSubscriptionWithNative{ value: 1 ether }(sub);
            f.setSubscription(sub);
            pv.roll(block.number + 1);
            g = gasleft();
            f.requestSampleSetChainlink(SET, epoch);
            g -= gasleft();
            _rec(address(f), abi.encodeCall(f.requestSampleSetChainlink, (SET, epoch)));
            _log("P5 shared SAMPLE request through Chainlink VRF v2.5 (set, native), tx gas", g);
        }
    }

    function test_gas_directSample() public {
        P5Leaf[] memory ls = _plainLeaves(pidD, 8, true);
        P5Unit memory u = _unit(pidD, keyD, ls);
        _toAnchorTime();
        require(f.anchorUnit(u) == 0, "anchored");
        pv.roll(f.anchorDeadline(epoch) + 1);
        uint256 g = gasleft();
        f.requestSample(pidD, epoch);
        g -= gasleft();
        _rec(address(f), abi.encodeCall(f.requestSample, (pidD, epoch)));
        _log("P5 direct SAMPLE request (profile), tx gas", g);
        _fulfill(pidD, "direct");
    }

    // ----------------------------------------------------------- release

    /// Profiles 0..np-1 of the set: m sales each, the first k at v = V
    /// (sampled with probability 1) with passing proofs, anchored by one
    /// bundle; a shared value under which no other sale is sampled.
    function _releaseSetUp(uint256 np, uint256 m, uint256 k) internal returns (P5Rel[] memory rs) {
        rs = new P5Rel[](np);
        P5Unit[] memory us = new P5Unit[](np);
        for (uint256 p; p < np; p++) {
            bytes32 pid = setPids[p];
            P5Leaf[] memory ls = new P5Leaf[](m);
            bool[] memory sg = new bool[](m);
            rs[p].pid = pid;
            rs[p].items = new P5Item[](m);
            for (uint256 i; i < m; i++) {
                ls[i].rs = _rs(pid, i, i < k ? CAP : PRICE);
                sg[i] = true;
                rs[p].items[i] = P5Item(
                    ls[i].rs.nonce, buyer, ls[i].rs.amount, CAP, keccak256(abi.encode(ls[i].rs.requestHash, ls[i].rs.claimsHash))
                );
            }
            _settle(pid, ls, sg);
            _signLeaves(pid, ls, sg);
            us[p] = _unit(pid, setKeys[p], ls);
            bytes32[] memory pass = new bytes32[](k);
            for (uint256 i; i < k; i++) pass[i] = ls[i].rs.nonce;
            f.passFixture(pid, pass);
        }
        _toAnchorTime();
        pv.prank(fac);
        require(f.anchorBundle(SET, us) == np, "anchored");
        uint256 value;
        for (uint256 t = 1;; t++) {
            value = uint256(keccak256(abi.encode("p5 sample value", t)));
            bool ok = true;
            for (uint256 p; p < np && ok; p++) {
                for (uint256 i = k; i < m; i++) {
                    if (f.sampledBy(value, rs[p].pid, true, rs[p].items[i].nonce, PRICE, CAP)) {
                        ok = false;
                        break;
                    }
                }
            }
            if (ok) break;
        }
        pv.roll(f.anchorDeadline(epoch) + 20);
        f.valueFixture(bytes32(uint256(SET)), epoch, value);
        pv.roll(f.anchorDeadline(epoch) + f.T_C() + 1);
    }

    function _releaseBundle(uint256 np) internal {
        uint256 id = pv.snapshotState();
        P5Rel[] memory rs = _releaseSetUp(np, 8, 4);
        pv.prank(fac);
        uint256 g = gasleft();
        uint256 paid = f.releaseBundle(SET, rs);
        g -= gasleft();
        _rec(address(f), abi.encodeCall(f.releaseBundle, (SET, rs)));
        require(paid == np, "all paid");
        _log(string.concat("P5 bundled release, N=", _u(np), " accounts, m=8 sales, k=4 cases each, tx gas"), g);
        pv.revertToState(id);
    }

    function test_gas_release() public {
        // direct release of one account of the set (same path, no bundle)
        uint256 id = pv.snapshotState();
        P5Rel[] memory rs = _releaseSetUp(1, 8, 4);
        uint256 g = gasleft();
        f.release(rs[0].pid, rs[0].items);
        g -= gasleft();
        _rec(address(f), abi.encodeCall(f.release, (rs[0].pid, rs[0].items)));
        _log("P5 release one account, m=8 sales, k=4 cases, tx gas", g);
        pv.revertToState(id);
        _releaseBundle(1);
        _releaseBundle(2);
        _releaseBundle(4);
        _releaseBundle(8);
    }

    // ------------------------------------------------------------- proofs

    function _lazerUpdate(uint64 ts, int64 price) internal returns (bytes memory upd) {
        bytes memory payload =
            abi.encodePacked(uint32(2479346549), ts, uint8(3), uint8(1), uint32(LAZER_FEED), uint8(1), uint8(0), price);
        (uint8 vv, bytes32 r, bytes32 s) = pv.sign(lazerKey, keccak256(payload));
        upd = abi.encodePacked(uint32(706910618), r, s, uint8(vv - 27), uint16(payload.length), payload);
    }

    function _proofUnit(bytes32 pid, uint256 key, P5Rs memory r0) internal returns (P5Leaf[] memory ls) {
        ls = new P5Leaf[](32);
        bool[] memory sg = new bool[](32);
        ls[0].rs = r0;
        for (uint256 i = 1; i < 32; i++) ls[i].rs = _rs(pid, i, PRICE);
        _settle(pid, ls, sg);
        P5Unit memory u = _unit(pid, key, ls);
        _toAnchorTime();
        require(f.anchorUnit(u) == 0, "anchored");
        pv.roll(f.anchorDeadline(epoch) + 20);
        f.valueFixture(pid, epoch, uint256(keccak256("p5 value")));
        pv.roll(block.number + 5);
    }

    function test_gas_proveTier1a() public {
        bytes32 psi = keccak256("p5 psi");
        uint64 ts = VALID_AFTER * 1e6; // the fixed-rate channel's first grid time
        int64 price = 189_000_000_000;
        bytes memory material = abi.encodePacked(psi, _lazerUpdate(ts, price));
        P5Rs memory r0 = _rs(pidD, 0, CAP); // v = V: sampled with probability 1
        r0.responseHash = keccak256(abi.encodePacked(TAG, psi, abi.encode(LAZER_FEED, price, ts)));
        r0.materialCommit = keccak256(material);
        P5Leaf[] memory ls = _proofUnit(pidD, keyD, r0);
        P5Open memory o = _open(pidD, ls, 0);
        uint256 g = gasleft();
        f.prove(o, material);
        g -= gasleft();
        _rec(address(f), abi.encodeCall(f.prove, (o, material)));
        require(f.passed(keccak256(abi.encode(pidD, o.rs.nonce))) == 1, "passed");
        _log("P5 proof call, tier 1a Pyth Pro one feed, depth 5, tx gas", g);
    }

    function test_gas_proveTier0() public {
        bytes32 psi = keccak256("p5 psi t0");
        // synthetic fixture (G7 2nd ed.): block N_REF has timestamp VALID_AFTER
        bytes memory material = abi.encode(
            F.header(), F.accountProof(), F.nStorageProof(), F.N_REF, psi, F.nRefHeader(), F.nNextHeader()
        );
        P5Rs memory r0 = _rs(pidT0, 0, CAP);
        r0.responseHash = keccak256(abi.encodePacked(TAG, psi, abi.encode(F.N_REF, F.N_REF_HASH)));
        r0.materialCommit = keccak256(material);
        P5Leaf[] memory ls = _proofUnit(pidT0, keyT0, r0);
        // the fixture's header stands for the block the anchor stored
        f.hashFixture(pidT0, epoch, F.BLOCK_HASH);
        P5Open memory o = _open(pidT0, ls, 0);
        uint256 g = gasleft();
        f.prove(o, material);
        g -= gasleft();
        _rec(address(f), abi.encodeCall(f.prove, (o, material)));
        require(f.passed(keccak256(abi.encode(pidT0, o.rs.nonce))) == 1, "passed");
        _log("P5 proof call, tier 0 storage proof (synthetic fixture), depth 5, tx gas", g);
    }

    // ----------------------------------------------------------- disputes

    function _pt(uint256 size, bytes32 psi) internal pure returns (bytes memory pt) {
        pt = new bytes(size);
        for (uint256 i; i < 32; i++) pt[i] = psi[i];
        for (uint256 i = 32; i < size; i++) pt[i] = bytes1(uint8(0x20 + (i * 31) % 90));
    }

    function _encrypt(bytes32 k, bytes32 nonce, bytes memory pt) internal pure returns (bytes memory ct) {
        ct = new bytes(pt.length);
        for (uint256 j; j < pt.length / 32; j++) {
            bytes32 ks = keccak256(abi.encode(k, nonce, j));
            bytes32 w;
            assembly {
                w := mload(add(add(pt, 0x20), shl(5, j)))
            }
            w ^= ks;
            assembly {
                mstore(add(add(ct, 0x20), shl(5, j)), w)
            }
        }
    }

    struct DCase {
        bytes32 k;
        bytes ct;
    }

    /// Leaves 0..3 of a 32-leaf unit: non-delivery honest, non-delivery
    /// misbehaving, key dispute honest (signed), key dispute misbehaving
    /// (signed), all with responses of `size` bytes.
    function test_gas_disputes() public {
        _disputes(1024);
        _disputes(4096);
    }

    function _disputes(uint256 size) internal {
        uint256 id = pv.snapshotState();
        P5Leaf[] memory ls = new P5Leaf[](32);
        bool[] memory sg = new bool[](32);
        DCase[4] memory dc;
        for (uint256 i; i < 32; i++) ls[i].rs = _rs(pidD, i, PRICE);
        for (uint256 i; i < 4; i++) {
            bytes32 psi = keccak256(abi.encode("p5 psi d", i, size));
            dc[i].k = keccak256(abi.encode("p5 key", i, size));
            bytes memory pt = _pt(size, psi);
            dc[i].ct = _encrypt(dc[i].k, ls[i].rs.nonce, pt);
            ls[i].rs.ctHash = keccak256(dc[i].ct);
            ls[i].rs.keyHash = keccak256(abi.encode(dc[i].k));
            ls[i].rs.responseHash = i % 2 == 0 ? keccak256(abi.encodePacked(TAG, pt)) : keccak256("another response");
            sg[i] = i >= 2;
        }
        _settle(pidD, ls, sg);
        _signLeaves(pidD, ls, sg);
        P5Unit memory u = _unit(pidD, keyD, ls);
        _toAnchorTime();
        require(f.anchorUnit(u) == 0, "anchored");
        pv.roll(f.anchorDeadline(epoch) + 10);
        string memory z = string.concat(", ", _u(size / 1024), " KB");
        for (uint256 i; i < 4; i++) {
            uint8 kind = i < 2 ? 1 : 2;
            string memory tag = string.concat(
                kind == 1 ? "P5 non-delivery dispute" : "P5 key dispute", i % 2 == 0 ? " (honest seller)" : " (misbehaving seller)"
            );
            P5Open memory o = _open(pidD, ls, i);
            pv.prank(buyer);
            uint256 g = gasleft();
            f.openDispute(o, kind);
            g -= gasleft();
            _rec(address(f), abi.encodeCall(f.openDispute, (o, kind)));
            _log(string.concat(tag, ", open, depth 5", z, ", tx gas"), g);
            pv.roll(block.number + 3);
            bytes32 nonce = ls[i].rs.nonce;
            if (kind == 1) {
                g = gasleft();
                f.answerDeliver(pidD, nonce, dc[i].ct, dc[i].k);
                g -= gasleft();
                _rec(address(f), abi.encodeCall(f.answerDeliver, (pidD, nonce, dc[i].ct, dc[i].k)));
                _log(string.concat(tag, ", seller posts ct and k", z, ", tx gas"), g);
            } else {
                g = gasleft();
                f.answerKey(pidD, nonce, dc[i].k);
                g -= gasleft();
                _rec(address(f), abi.encodeCall(f.answerKey, (pidD, nonce, dc[i].k)));
                _log(string.concat(tag, ", seller reveals k", z, ", tx gas"), g);
            }
            pv.roll(block.number + 3);
            pv.prank(buyer);
            g = gasleft();
            bool refunded = f.challengeDecrypt(pidD, nonce, dc[i].ct);
            g -= gasleft();
            _rec(address(f), abi.encodeCall(f.challengeDecrypt, (pidD, nonce, dc[i].ct)));
            require(refunded == (i % 2 == 1), "decryption outcome");
            _log(string.concat(tag, refunded ? ", decryption challenge, refund" : ", decryption challenge, deposit to seller", z, ", tx gas"), g);
        }
        pv.revertToState(id);
    }
}
