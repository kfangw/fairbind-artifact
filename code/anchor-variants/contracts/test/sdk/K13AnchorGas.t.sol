// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBase } from "./SdkBase.sol";
import { SdkBaseC1 } from "./variants/c1/SdkBaseC1.sol";
import { SdkBaseC1R } from "./variants/c1r/SdkBaseC1R.sol";
import { SampledSettlement, SettlementModule } from "./SampledSettlement.sol";
import { SampledSettlementC1Core, SettlementModuleC1, SettlementBaseC1, UnitRec, AnchorPre } from "./variants/SampledSettlementC1.sol";
import { Receipt, Leaf, Unit, Opening, UnitHeader } from "./SampledSettlement.sol";

struct K13CallGas {
    uint64 gasLimit;
    uint64 gasTotalUsed;
    uint64 gasMemoryUsed;
    int64 gasRefunded;
    uint64 gasRemaining;
}

interface K13Vm {
    function lastCallGas() external view returns (K13CallGas memory);
    function record() external;
    function accesses(address target) external returns (bytes32[] memory reads, bytes32[] memory writes);
    function load(address target, bytes32 slot) external view returns (bytes32);
    function snapshotState() external returns (uint256);
    function revertToState(uint256 id) external returns (bool);
    function roll(uint256 height) external;
    function prank(address sender) external;
}

/// The calls the three designs share (module calls reach the module through
/// the settlement contract's fallback).
interface IK13 {
    function genesis() external view returns (uint256);
    function EPOCH_BLOCKS() external view returns (uint256);
    function D_INC() external view returns (uint256);
    function T_C() external view returns (uint256);
    function lastBlock(uint256 e) external view returns (uint256);
    function anchorDeadline(uint256 e) external view returns (uint256);
    function valueDeadline(uint256 e) external view returns (uint256);
    function epochOf(uint256 b) external view returns (uint256);
    function sampledBy(uint256 value, bytes32 nonce, uint64 v, uint64 cap) external pure returns (bool);
    function postSampleValue(bytes32 pid, uint256 epoch, uint256 value) external;
    function accountCursor(address acct) external view returns (uint256);
    function passed(bytes32 key) external view returns (bool);
    function openDisputes(bytes32 key) external view returns (uint256);
    function epochComplete(bytes32 pid, uint256 epoch) external view returns (bool);
    function DOMAIN_SEPARATOR() external view returns (bytes32);
    function UNIT_TYPEHASH() external view returns (bytes32);
    function K_NONDELIVERY() external view returns (uint8);
    function rsHash(bytes32 pid, bytes32 codeHash, Receipt calldata r) external pure returns (bytes32);
    function release(address acct) external returns (uint256);
    function account(address acct)
        external
        view
        returns (uint128, uint128, uint64, uint32 episode, uint32 failures, bool, uint32, uint16);
}

/// K13 measurement rows (preregistration K13, sections 3.3 to 3.6) on the
/// SDK reference contract (variant base) and its anchor variants C1 and C1r,
/// with one function per event and variant, test_k13_<event>_<variant>.
/// Each measured call runs as its own transaction under --isolate and is
/// logged as
///   K13 <variant> <event> <P> <m> <sig> <slot> <tx_gas> <eip7623_floor>
/// (tab separated); anchor rows also log the storage slots the call wrote,
///   K13SLOTS <variant> <m> <sig> <slot> <new_slots> <updated_slots>
/// with new = zero before and non-zero after, updated = non-zero before and
/// changed. Each row checks its outcome. The bundle row (anchor_bundle) is
/// not measured: the SDK contract has no bundle path. Measure only on the
/// Base fork after the K13 preregistration is sealed; a local run checks that
/// the rows execute and its numbers are not results.
abstract contract K13GasLogic {
    K13Vm internal constant kvm = K13Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    bytes32 internal constant TAG_K13 = keccak256("p5/response/v1");
    uint256 internal constant M_PROOF = 32; // Merkle depth 5

    event log_string(string);

    struct Ctx {
        address f;
        bytes32 pidP; // tier 1a plaintext (measured profile)
        bytes32 pidC; // second profile of the same account (warm-up anchors)
        address seller;
        address tower;
        address rnd;
        uint256 sellerKey;
        uint64 cap;
    }

    // ---------------------------------------------------------------- hooks
    function _kName() internal pure virtual returns (string memory);
    function _kRing() internal pure virtual returns (uint256); // 0: no slot reuse
    function _kCtx() internal view virtual returns (Ctx memory);
    function _kSale(bytes32 pid, uint256 i, uint64 amount, bool signed) internal virtual returns (Leaf memory, bytes memory);
    function _kUnit(bytes32 pid, uint256 e, Leaf[] memory ls) internal virtual returns (Unit memory);
    function _kOpening(bytes32 pid, uint256 e, Leaf[] memory ls, uint256 i) internal virtual returns (Opening memory);
    function _kSign(uint256 key, bytes32 digest) internal virtual returns (bytes memory);
    function _kAnchorData(Unit memory u) internal view virtual returns (bytes memory);
    function _kProveData(Opening memory o, bytes memory mat) internal view virtual returns (bytes memory);
    function _kDisputeData(Opening memory o, uint8 kind) internal view virtual returns (bytes memory);
    function _kSwapData(Opening memory o, Receipt memory rs, bytes memory sig) internal view virtual returns (bytes memory);
    function _kDoubleData(UnitHeader memory h, bytes memory sig) internal view virtual returns (bytes memory);
    function _kBeforeAnchor() internal virtual;
    function _kAfterAnchor() internal virtual;
    /// The unit's storage holds what was anchored (C1, C1r: the slot equals
    /// the hash of the emitted record).
    function _kCheckStored(bytes32 pid, uint256 e, uint256 unitNo) internal view virtual;

    // -------------------------------------------------------------- helpers

    function _F() internal view returns (IK13) {
        return IK13(_kCtx().f);
    }

    function _rollTo(uint256 b) internal {
        if (block.number < b) kvm.roll(b);
    }

    function _startOf(uint256 e) internal view returns (uint256) {
        return _F().genesis() + e * _F().EPOCH_BLOCKS() + 5;
    }

    function _floor(bytes memory d) internal pure returns (uint256 g) {
        uint256 tokens;
        for (uint256 i; i < d.length; i++) tokens += d[i] == 0 ? 1 : 4;
        g = 21_000 + 10 * tokens;
    }

    function _s(uint256 v) internal pure returns (string memory) {
        if (v == 0) return "0";
        bytes memory b;
        while (v != 0) {
            b = abi.encodePacked(bytes1(uint8(48 + v % 10)), b);
            v /= 10;
        }
        return string(b);
    }

    function _row(string memory ev, string memory p, string memory m, string memory sig, string memory slot, uint256 gas, uint256 fl)
        internal
    {
        string memory a = string.concat("K13\t", _kName(), "\t", ev, "\t", p);
        string memory b = string.concat(a, "\t", m, "\t", sig, "\t", slot);
        emit log_string(string.concat(b, "\t", _s(gas), "\t", _s(fl)));
    }

    /// m sales on pid in epoch e, sorted by nonce with their materials.
    function _sell(bytes32 pid, uint256 e, uint256 m, uint64 amount, bool signed, uint256 tag)
        internal
        returns (Leaf[] memory ls, bytes[] memory mats)
    {
        _rollTo(_startOf(e));
        ls = new Leaf[](m);
        mats = new bytes[](m);
        for (uint256 i; i < m; i++) (ls[i], mats[i]) = _kSale(pid, tag * 1_000_000 + i, amount, signed);
        for (uint256 i = 1; i < m; i++) {
            for (uint256 j = i; j > 0 && ls[j - 1].rs.nonce > ls[j].rs.nonce; j--) {
                (ls[j], ls[j - 1]) = (ls[j - 1], ls[j]);
                (mats[j], mats[j - 1]) = (mats[j - 1], mats[j]);
            }
        }
    }

    function _call(bytes memory data) internal returns (bytes memory ret, uint256 gas) {
        bool ok;
        (ok, ret) = _kCtx().f.call(data);
        gas = kvm.lastCallGas().gasTotalUsed;
        if (!ok) {
            assembly ("memory-safe") {
                revert(add(ret, 0x20), mload(ret))
            }
        }
    }

    /// Anchors u unmeasured (warm-up, earlier epochs).
    function _anchorPlain(Unit memory u) internal {
        _kBeforeAnchor();
        (bytes memory ret,) = _call(_kAnchorData(u));
        require(abi.decode(ret, (uint8)) == 0, "anchor rejected");
        _kAfterAnchor();
    }

    /// Anchors u measured: a first run under a snapshot gives the slots the
    /// call writes, the second (kept) run gives the gas and the values after.
    function _anchorMeasured(Unit memory u) internal returns (uint256[4] memory g) {
        bytes memory data = _kAnchorData(u);
        (bytes32[] memory w, bytes32[] memory pre) = _probeWrites(data);
        _kBeforeAnchor();
        bytes memory ret;
        (ret, g[0]) = _call(data);
        require(abi.decode(ret, (uint8)) == 0, "anchor rejected");
        _kAfterAnchor();
        g[1] = _floor(data);
        (g[2], g[3]) = _countSlots(_kCtx().f, w, pre);
    }

    /// Runs the call under a snapshot to list the slots it writes and their
    /// values before it.
    function _probeWrites(bytes memory data) internal returns (bytes32[] memory w, bytes32[] memory pre) {
        address f = _kCtx().f;
        uint256 id = kvm.snapshotState();
        kvm.record();
        (bool ok,) = f.call(data);
        require(ok, "anchor reverted");
        (, w) = kvm.accesses(f);
        kvm.revertToState(id);
        pre = new bytes32[](w.length);
        for (uint256 i; i < w.length; i++) pre[i] = kvm.load(f, w[i]);
    }

    function _countSlots(address f, bytes32[] memory w, bytes32[] memory pre)
        internal
        view
        returns (uint256 nNew, uint256 nUpd)
    {
        for (uint256 i; i < w.length; i++) {
            if (_seenBefore(w, i)) continue;
            bytes32 post = kvm.load(f, w[i]);
            if (pre[i] == 0 && post != 0) nNew++;
            else if (pre[i] != 0 && post != pre[i]) nUpd++;
        }
    }

    function _seenBefore(bytes32[] memory w, uint256 i) internal pure returns (bool) {
        for (uint256 j; j < i; j++) if (w[j] == w[i]) return true;
        return false;
    }

    /// A non-sampling value for epoch e's sales of pid, then the cursor past e.
    function _pass(bytes32 pid, uint256 e, Leaf[] memory ls) internal {
        Ctx memory c = _kCtx();
        _rollTo(_F().anchorDeadline(e) + 1);
        uint256 v = 1;
        for (;; v++) {
            bool any;
            for (uint256 i; i < ls.length; i++) if (_F().sampledBy(v, ls[i].rs.nonce, ls[i].rs.amount, c.cap)) any = true;
            if (!any) break;
        }
        kvm.prank(c.rnd);
        _F().postSampleValue(pid, e, v);
        _rollTo(_F().anchorDeadline(e) + _F().T_C() + 1);
        while (_F().accountCursor(c.seller) <= e) _F().release(c.seller);
    }

    /// One warm-up anchor on the second profile in epoch e, so that the
    /// contract's counters are non-zero before the measured call.
    function _warm(uint256 e) internal returns (Unit memory) {
        Ctx memory c = _kCtx();
        (Leaf[] memory lw,) = _sell(c.pidC, e, 1, 10_000, true, 9);
        return _kUnit(c.pidC, e, lw);
    }

    // ----------------------------------------------------------------- rows

    function _anchorSelf(bool reuse) internal {
        uint256[7] memory ms = [uint256(1), 2, 4, 8, 16, 32, 64];
        for (uint256 s; s < 2; s++) {
            for (uint256 k; k < ms.length; k++) _anchorRow(ms[k], s == 0, reuse);
        }
    }

    function _anchorRow(uint256 m, bool signed, bool reuse) internal {
        Ctx memory c = _kCtx();
        uint256 id = kvm.snapshotState();
        uint256 e = _F().epochOf(block.number) + 1;
        if (reuse) {
            (Leaf[] memory l0,) = _sell(c.pidP, e, m, 10_000, signed, 1);
            Unit memory u0 = _kUnit(c.pidP, e, l0);
            _rollTo(_F().lastBlock(e) + _F().D_INC() + 1);
            _anchorPlain(u0);
            _pass(c.pidP, e, l0);
            e += _kRing();
        }
        Unit memory uw = _warm(e);
        (Leaf[] memory ls,) = _sell(c.pidP, e, m, 10_000, signed, 2);
        Unit memory u = _kUnit(c.pidP, e, ls);
        _rollTo(_F().lastBlock(e) + _F().D_INC() + 1);
        _anchorPlain(uw);
        uint256[4] memory g = _anchorMeasured(u); // gas, floor, new slots, updated slots
        require(_F().epochComplete(c.pidP, e), "complete");
        _kCheckStored(c.pidP, e, 1);
        _anchorLog(m, signed, reuse, g);
        kvm.revertToState(id);
    }

    function _anchorLog(uint256 m, bool signed, bool reuse, uint256[4] memory g) internal {
        string memory slot = reuse ? "reused" : "fresh";
        string memory sg = signed ? "1" : "0";
        _row("anchor_self", "1", _s(m), sg, slot, g[0], g[1]);
        string memory a = string.concat("K13SLOTS\t", _kName(), "\t", _s(m), "\t", sg);
        emit log_string(string.concat(a, "\t", slot, "\t", _s(g[2]), "\t", _s(g[3])));
    }

    /// An anchored unit of M_PROOF leaves on pidP in the next epoch.
    function _stored(uint64 amount, bool signed) internal returns (uint256 e, Leaf[] memory ls, bytes[] memory mats, Unit memory u) {
        Ctx memory c = _kCtx();
        e = _F().epochOf(block.number) + 1;
        (ls, mats) = _sell(c.pidP, e, M_PROOF, amount, signed, 3);
        u = _kUnit(c.pidP, e, ls);
        _rollTo(_F().lastBlock(e) + _F().D_INC() + 1);
        _anchorPlain(u);
    }

    function _proveRow() internal {
        Ctx memory c = _kCtx();
        uint256 id = kvm.snapshotState();
        (uint256 e, Leaf[] memory ls, bytes[] memory mats,) = _stored(10_000, true);
        _rollTo(_F().valueDeadline(e) + 1); // no value: every sale is sampled
        bytes memory data = _kProveData(_kOpening(c.pidP, e, ls, 0), mats[0]);
        (, uint256 gas) = _call(data);
        require(_F().passed(keccak256(abi.encode(c.pidP, ls[0].rs.nonce))), "proof passed");
        _row("prove", "-", "-", "-", "-", gas, _floor(data));
        kvm.revertToState(id);
    }

    /// Eight sales in one unit, four of them sampled and proved, then one
    /// cursor call that pays all eight.
    function _releaseRow() internal {
        Ctx memory c = _kCtx();
        uint256 id = kvm.snapshotState();
        uint64 amount = c.cap / 2;
        uint256 e = _F().epochOf(block.number) + 1;
        (Leaf[] memory ls, bytes[] memory mats) = _sell(c.pidP, e, 8, amount, true, 4);
        Unit memory u = _kUnit(c.pidP, e, ls);
        _rollTo(_F().lastBlock(e) + _F().D_INC() + 1);
        _anchorPlain(u);
        _rollTo(_F().anchorDeadline(e) + 1);
        uint256 v = 1;
        for (;; v++) {
            uint256 n;
            for (uint256 i; i < 8; i++) if (_F().sampledBy(v, ls[i].rs.nonce, amount, c.cap)) n++;
            if (n == 4) break;
        }
        kvm.prank(c.rnd);
        _F().postSampleValue(c.pidP, e, v);
        for (uint256 i; i < 8; i++) {
            if (_F().sampledBy(v, ls[i].rs.nonce, amount, c.cap)) _call(_kProveData(_kOpening(c.pidP, e, ls, i), mats[i]));
        }
        _rollTo(_F().anchorDeadline(e) + _F().T_C() + 1);
        // epochs before e (no sales) first, unmeasured
        while (_F().accountCursor(c.seller) < e) _F().release(c.seller);
        bytes memory data = abi.encodeCall(IK13.release, (c.seller));
        (bytes memory ret, uint256 gas) = _call(data);
        require(abi.decode(ret, (uint256)) == 8 * uint256(amount), "all eight paid");
        _row("release_one", "-", "8", "1", "-", gas, _floor(data));
        kvm.revertToState(id);
    }

    function _disputeRow() internal {
        Ctx memory c = _kCtx();
        uint256 id = kvm.snapshotState();
        (uint256 e, Leaf[] memory ls,,) = _stored(10_000, false);
        bytes memory data = _kDisputeData(_kOpening(c.pidP, e, ls, 0), _F().K_NONDELIVERY());
        kvm.prank(c.tower);
        (, uint256 gas) = _call(data);
        require(_F().openDisputes(keccak256(abi.encode(c.pidP, ls[0].rs.nonce))) == 1, "dispute open");
        _row("dispute_open", "-", "-", "-", "-", gas, _floor(data));
        kvm.revertToState(id);
    }

    function _hdr(Unit memory u) internal pure returns (UnitHeader memory) {
        return UnitHeader(u.pid, u.epoch, u.count, u.unitNo, u.first, u.last, u.root, u.root0, keccak256(abi.encode(u.snapshot)));
    }

    function _hdrSig(UnitHeader memory h) internal returns (bytes memory) {
        Ctx memory c = _kCtx();
        bytes32 sh = keccak256(
            abi.encode(_F().UNIT_TYPEHASH(), h.pid, h.epoch, h.count, h.unitNo, h.first, h.last, h.root, h.root0, h.snapshotHash)
        );
        return _kSign(c.sellerKey, keccak256(abi.encodePacked(hex"1901", _F().DOMAIN_SEPARATOR(), sh)));
    }

    function _doubleRow() internal {
        Ctx memory c = _kCtx();
        uint256 id = kvm.snapshotState();
        (,,, Unit memory u) = _stored(10_000, true);
        UnitHeader memory h = _hdr(u);
        h.root0 = keccak256("another root0");
        bytes memory data = _kDoubleData(h, _hdrSig(h));
        (, uint256 gas) = _call(data);
        (,,,, uint32 failures,,,) = _F().account(c.seller);
        require(failures == 1, "double signature recorded");
        _row("double_sign", "-", "-", "-", "-", gas, _floor(data));
        kvm.revertToState(id);
    }

    function _swapInputs(uint256 e, Leaf[] memory ls) internal returns (Opening memory o, Receipt memory rs, bytes memory sig) {
        Ctx memory c = _kCtx();
        o = _kOpening(c.pidP, e, ls, 0);
        rs = abi.decode(abi.encode(ls[0].rs), (Receipt)); // a copy: o.rs shares ls[0].rs's memory
        rs.responseHash = keccak256("the response the seller signed");
        bytes32 ch = _codeHash();
        bytes32 h = _F().rsHash(c.pidP, ch, rs);
        sig = _kSign(c.sellerKey, keccak256(abi.encodePacked(hex"1901", _F().DOMAIN_SEPARATOR(), h)));
    }

    function _codeHash() internal view virtual returns (bytes32);

    function _swapRow() internal {
        uint256 id = kvm.snapshotState();
        (uint256 e, Leaf[] memory ls,,) = _stored(10_000, false);
        (Opening memory o, Receipt memory rs, bytes memory sig) = _swapInputs(e, ls);
        bytes memory data = _kSwapData(o, rs, sig);
        (, uint256 gas) = _call(data);
        (,,,, uint32 failures,,,) = _F().account(_kCtx().seller);
        require(failures == 1, "swap proof recorded");
        _row("swap_proof", "-", "-", "-", "-", gas, _floor(data));
        kvm.revertToState(id);
    }
}

// ============================================================ base (reference)

contract K13AnchorGasBase is SdkBase, K13GasLogic {
    function _kName() internal pure override returns (string memory) {
        return "base";
    }

    function _kRing() internal pure override returns (uint256) {
        return 0;
    }

    function _kCtx() internal view override returns (Ctx memory) {
        return Ctx(address(f), pidP, pidC, seller, tower, rnd, sellerKey, CAP);
    }

    function _codeHash() internal view override returns (bytes32) {
        return f.profile(pidP).codeHash;
    }

    function _kSale(bytes32 pid, uint256 i, uint64 amount, bool signed) internal override returns (Leaf memory l, bytes memory mat) {
        uint64 ts = VALID_AFTER * 1e6;
        bytes32 psi = keccak256(abi.encode("psi", pid, i));
        mat = abi.encodePacked(psi, _lazerUpdate(ts, 7, FEED, feedKey));
        Receipt memory r = _rs(pid, i, amount);
        r.responseHash = keccak256(abi.encodePacked(TAG_K13, psi, abi.encode(FEED, int64(7), ts)));
        r.materialCommit = keccak256(mat);
        l.rs = _buy(pid, r, i);
        if (signed) l.sigB = _ack(pid, l.rs, false);
    }

    function _kUnit(bytes32 pid, uint256 e, Leaf[] memory ls) internal override returns (Unit memory) {
        epoch = e;
        return _unit(pid, ls);
    }

    function _kOpening(bytes32 pid, uint256 e, Leaf[] memory ls, uint256 i) internal override returns (Opening memory) {
        epoch = e;
        return _opening(pid, ls, i);
    }

    function _kSign(uint256 key, bytes32 d) internal override returns (bytes memory) {
        return _sig(key, d);
    }

    function _kAnchorData(Unit memory u) internal pure override returns (bytes memory) {
        return abi.encodeCall(SampledSettlement.anchorUnit, (u));
    }

    function _kProveData(Opening memory o, bytes memory mat) internal pure override returns (bytes memory) {
        return abi.encodeCall(SampledSettlement.prove, (o, mat));
    }

    function _kDisputeData(Opening memory o, uint8 kind) internal pure override returns (bytes memory) {
        return abi.encodeCall(SampledSettlement.openDispute, (o, kind, "", 0));
    }

    function _kSwapData(Opening memory o, Receipt memory rs, bytes memory sig) internal pure override returns (bytes memory) {
        return abi.encodeCall(SettlementModule.proveSwap, (o, rs, sig));
    }

    function _kDoubleData(UnitHeader memory h, bytes memory sig) internal pure override returns (bytes memory) {
        return abi.encodeCall(SettlementModule.proveDoubleSign, (h, sig));
    }

    function _kBeforeAnchor() internal override { }

    function _kAfterAnchor() internal override { }

    function _kCheckStored(bytes32 pid, uint256 e, uint256 unitNo) internal view override {
        require(f.unitStoredAt(keccak256(abi.encode(pid, bytes32(e), unitNo))) == block.number, "stored");
    }

    function test_k13_anchor_self_base() public {
        _anchorSelf(false);
    }

    function test_k13_prove_base() public {
        _proveRow();
    }

    function test_k13_release_one_base() public {
        _releaseRow();
    }

    function test_k13_dispute_open_base() public {
        _disputeRow();
    }

    function test_k13_double_sign_base() public {
        _doubleRow();
    }

    function test_k13_swap_proof_base() public {
        _swapRow();
    }
}

// ============================================================== variants

/// Calldata and checks shared by C1 and C1r (both bases expose the same
/// variant helpers; each contract below repeats these few lines).
contract K13AnchorGasC1 is SdkBaseC1, K13GasLogic {
    function _kName() internal pure virtual override returns (string memory) {
        return "c1";
    }

    function _kRing() internal pure virtual override returns (uint256) {
        return 0;
    }

    function _kCtx() internal view override returns (Ctx memory) {
        return Ctx(address(f), pidP, pidC, seller, tower, rnd, sellerKey, CAP);
    }

    function _codeHash() internal view override returns (bytes32) {
        return m.profile(pidP).codeHash;
    }

    function _kSale(bytes32 pid, uint256 i, uint64 amount, bool signed) internal override returns (Leaf memory l, bytes memory mat) {
        uint64 ts = VALID_AFTER * 1e6;
        bytes32 psi = keccak256(abi.encode("psi", pid, i));
        mat = abi.encodePacked(psi, _lazerUpdate(ts, 7, FEED, feedKey));
        Receipt memory r = _rs(pid, i, amount);
        r.responseHash = keccak256(abi.encodePacked(TAG_K13, psi, abi.encode(FEED, int64(7), ts)));
        r.materialCommit = keccak256(mat);
        l.rs = _buy(pid, r, i);
        if (signed) l.sigB = _ack(pid, l.rs, false);
    }

    function _kUnit(bytes32 pid, uint256 e, Leaf[] memory ls) internal override returns (Unit memory) {
        epoch = e;
        return _unit(pid, ls);
    }

    function _kOpening(bytes32 pid, uint256 e, Leaf[] memory ls, uint256 i) internal override returns (Opening memory) {
        epoch = e;
        return _opening(pid, ls, i);
    }

    function _kSign(uint256 key, bytes32 d) internal override returns (bytes memory) {
        return _sig(key, d);
    }

    function _kAnchorData(Unit memory u) internal view override returns (bytes memory) {
        AnchorPre memory pre;
        pre.er = _erecV[_ekV(u.pid, u.epoch)];
        if (u.unitNo > 0) pre.prev = _urecV[_ukV(u.pid, u.epoch, u.unitNo - 1)];
        pre.next = _urecV[_ukV(u.pid, u.epoch, uint256(u.unitNo) + 1)];
        return abi.encodeCall(SampledSettlementC1Core.anchorUnit, (u, pre));
    }

    function _kProveData(Opening memory o, bytes memory mat) internal view override returns (bytes memory) {
        return abi.encodeCall(SampledSettlementC1Core.prove, (o, mat, _recV(o.pid, o.epoch, o.unitNo)));
    }

    function _kDisputeData(Opening memory o, uint8 kind) internal view override returns (bytes memory) {
        return abi.encodeCall(SampledSettlementC1Core.openDispute, (o, kind, "", 0, _recV(o.pid, o.epoch, o.unitNo)));
    }

    function _kSwapData(Opening memory o, Receipt memory rs, bytes memory sig) internal view override returns (bytes memory) {
        return abi.encodeCall(SettlementModuleC1.proveSwap, (o, rs, sig, _recV(o.pid, o.epoch, o.unitNo)));
    }

    function _kDoubleData(UnitHeader memory h, bytes memory sig) internal view override returns (bytes memory) {
        return abi.encodeCall(SettlementModuleC1.proveDoubleSign, (h, sig, _recV(h.pid, h.epoch, h.unitNo)));
    }

    function _kBeforeAnchor() internal override {
        vvm.recordLogs();
    }

    function _kAfterAnchor() internal override {
        _absorbV();
    }

    function _kCheckStored(bytes32 pid, uint256 e, uint256 unitNo) internal view override {
        UnitRec memory r = _recV(pid, e, unitNo);
        require(r.storedAt == block.number, "record emitted");
        bytes32 key = keccak256(abi.encode(pid, bytes32(REUSE_V ? e % _kRing() : e), unitNo));
        uint256 v = f.unitSlot(key);
        uint256 mask = REUSE_V ? ((uint256(1) << 224) - 2) : ~uint256(1);
        require(v & mask == uint256(f.unitRecHash(r)) & mask, "slot is the record's hash");
        if (REUSE_V) require(v >> 224 == e, "slot tagged with its epoch");
    }

    // negative cases (not measured): a wrong record reverts each call

    function _neg() internal returns (uint256 e, Leaf[] memory ls, bytes[] memory mats, Unit memory u, UnitRec memory bad) {
        (e, ls, mats, u) = _stored(10_000, false);
        bad = _recV(pidP, e, 1);
        bad.root = keccak256("another root");
    }

    function test_k13_neg_prove() public {
        (uint256 e, Leaf[] memory ls, bytes[] memory mats,, UnitRec memory bad) = _neg();
        vm.roll(f.valueDeadline(e) + 1);
        Opening memory o = _opening(pidP, ls, 0);
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        f.prove(o, mats[0], bad);
    }

    function test_k13_neg_dispute_open() public {
        (, Leaf[] memory ls,,, UnitRec memory bad) = _neg();
        Opening memory o = _opening(pidP, ls, 0);
        vm.prank(tower);
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        f.openDispute(o, 1, "", 0, bad);
    }

    function test_k13_neg_double_sign() public {
        (,,, Unit memory u, UnitRec memory bad) = _neg();
        UnitHeader memory h = _hdr(u);
        h.root0 = keccak256("another root0");
        bytes memory s = _hdrSig(h);
        bad = _recV(pidP, u.epoch, 1);
        bad.count += 1; // would turn the count branch
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        m.proveDoubleSign(h, s, bad);
    }

    function test_k13_neg_swap_proof() public {
        (uint256 e, Leaf[] memory ls,,, UnitRec memory bad) = _neg();
        (Opening memory o, Receipt memory rs, bytes memory sig) = _swapInputs(e, ls);
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        m.proveSwap(o, rs, sig, bad);
    }

    function test_k13_anchor_self_c1() public virtual {
        _anchorSelf(false);
    }

    function test_k13_prove_c1() public virtual {
        _proveRow();
    }

    function test_k13_release_one_c1() public virtual {
        _releaseRow();
    }

    function test_k13_dispute_open_c1() public virtual {
        _disputeRow();
    }

    function test_k13_double_sign_c1() public virtual {
        _doubleRow();
    }

    function test_k13_swap_proof_c1() public virtual {
        _swapRow();
    }
}

contract K13AnchorGasC1r is SdkBaseC1R, K13GasLogic {
    function _kName() internal pure override returns (string memory) {
        return "c1r";
    }

    /// Ring length k + 3 with k = 1 (the test profiles).
    function _kRing() internal pure override returns (uint256) {
        return 4;
    }

    function _kCtx() internal view override returns (Ctx memory) {
        return Ctx(address(f), pidP, pidC, seller, tower, rnd, sellerKey, CAP);
    }

    function _codeHash() internal view override returns (bytes32) {
        return m.profile(pidP).codeHash;
    }

    function _kSale(bytes32 pid, uint256 i, uint64 amount, bool signed) internal override returns (Leaf memory l, bytes memory mat) {
        uint64 ts = VALID_AFTER * 1e6;
        bytes32 psi = keccak256(abi.encode("psi", pid, i));
        mat = abi.encodePacked(psi, _lazerUpdate(ts, 7, FEED, feedKey));
        Receipt memory r = _rs(pid, i, amount);
        r.responseHash = keccak256(abi.encodePacked(TAG_K13, psi, abi.encode(FEED, int64(7), ts)));
        r.materialCommit = keccak256(mat);
        l.rs = _buy(pid, r, i);
        if (signed) l.sigB = _ack(pid, l.rs, false);
    }

    function _kUnit(bytes32 pid, uint256 e, Leaf[] memory ls) internal override returns (Unit memory) {
        epoch = e;
        return _unit(pid, ls);
    }

    function _kOpening(bytes32 pid, uint256 e, Leaf[] memory ls, uint256 i) internal override returns (Opening memory) {
        epoch = e;
        return _opening(pid, ls, i);
    }

    function _kSign(uint256 key, bytes32 d) internal override returns (bytes memory) {
        return _sig(key, d);
    }

    function _kAnchorData(Unit memory u) internal view override returns (bytes memory) {
        AnchorPre memory pre;
        pre.er = _erecV[_ekV(u.pid, u.epoch)];
        if (u.unitNo > 0) pre.prev = _urecV[_ukV(u.pid, u.epoch, u.unitNo - 1)];
        pre.next = _urecV[_ukV(u.pid, u.epoch, uint256(u.unitNo) + 1)];
        return abi.encodeCall(SampledSettlementC1Core.anchorUnit, (u, pre));
    }

    function _kProveData(Opening memory o, bytes memory mat) internal view override returns (bytes memory) {
        return abi.encodeCall(SampledSettlementC1Core.prove, (o, mat, _recV(o.pid, o.epoch, o.unitNo)));
    }

    function _kDisputeData(Opening memory o, uint8 kind) internal view override returns (bytes memory) {
        return abi.encodeCall(SampledSettlementC1Core.openDispute, (o, kind, "", 0, _recV(o.pid, o.epoch, o.unitNo)));
    }

    function _kSwapData(Opening memory o, Receipt memory rs, bytes memory sig) internal view override returns (bytes memory) {
        return abi.encodeCall(SettlementModuleC1.proveSwap, (o, rs, sig, _recV(o.pid, o.epoch, o.unitNo)));
    }

    function _kDoubleData(UnitHeader memory h, bytes memory sig) internal view override returns (bytes memory) {
        return abi.encodeCall(SettlementModuleC1.proveDoubleSign, (h, sig, _recV(h.pid, h.epoch, h.unitNo)));
    }

    function _kBeforeAnchor() internal override {
        vvm.recordLogs();
    }

    function _kAfterAnchor() internal override {
        _absorbV();
    }

    function _kCheckStored(bytes32 pid, uint256 e, uint256 unitNo) internal view override {
        UnitRec memory r = _recV(pid, e, unitNo);
        require(r.storedAt == block.number, "record emitted");
        bytes32 key = keccak256(abi.encode(pid, bytes32(e % _kRing()), unitNo));
        uint256 v = f.unitSlot(key);
        if (v >> 224 != e) v = f.unitSlot(keccak256(abi.encode(pid, bytes32(e | (1 << 255)), unitNo)));
        uint256 mask = (uint256(1) << 224) - 2;
        require(v >> 224 == e && v & mask == uint256(f.unitRecHash(r)) & mask, "slot is the record's hash");
    }

    function _neg() internal returns (uint256 e, Leaf[] memory ls, bytes[] memory mats, Unit memory u, UnitRec memory bad) {
        (e, ls, mats, u) = _stored(10_000, false);
        bad = _recV(pidP, e, 1);
        bad.root = keccak256("another root");
    }

    function test_k13_neg_prove() public {
        (uint256 e, Leaf[] memory ls, bytes[] memory mats,, UnitRec memory bad) = _neg();
        vm.roll(f.valueDeadline(e) + 1);
        Opening memory o = _opening(pidP, ls, 0);
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        f.prove(o, mats[0], bad);
    }

    function test_k13_neg_dispute_open() public {
        (, Leaf[] memory ls,,, UnitRec memory bad) = _neg();
        Opening memory o = _opening(pidP, ls, 0);
        vm.prank(tower);
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        f.openDispute(o, 1, "", 0, bad);
    }

    function test_k13_neg_double_sign() public {
        (,,, Unit memory u, UnitRec memory bad) = _neg();
        UnitHeader memory h = _hdr(u);
        h.root0 = keccak256("another root0");
        bytes memory s = _hdrSig(h);
        bad = _recV(pidP, u.epoch, 1);
        bad.count += 1;
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        m.proveDoubleSign(h, s, bad);
    }

    function test_k13_neg_swap_proof() public {
        (uint256 e, Leaf[] memory ls,,, UnitRec memory bad) = _neg();
        (Opening memory o, Receipt memory rs, bytes memory sig) = _swapInputs(e, ls);
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        m.proveSwap(o, rs, sig, bad);
    }

    function test_k13_anchor_self_c1r_fresh() public {
        _anchorSelf(false);
    }

    function test_k13_anchor_self_c1r_reused() public {
        _anchorSelf(true);
    }

    function test_k13_prove_c1r() public {
        _proveRow();
    }

    function test_k13_release_one_c1r() public {
        _releaseRow();
    }

    function test_k13_dispute_open_c1r() public {
        _disputeRow();
    }

    function test_k13_double_sign_c1r() public {
        _doubleRow();
    }

    function test_k13_swap_proof_c1r() public {
        _swapRow();
    }
}
