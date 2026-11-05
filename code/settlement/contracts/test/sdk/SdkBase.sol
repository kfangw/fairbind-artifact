// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SampledSettlement, SettlementModule, Profile, Receipt, Leaf, Unit, Opening, Auth, IAuthToken } from "./SampledSettlement.sol";
import { MockAuthToken } from "./MockAuthToken.sol";
import { P5LazerVerifier, P5StorageVerifier } from "../g10/p5/P5Verifiers.sol";
import { VRFCoordinatorV2_5Mock } from "./vrf/chainlink/v0.8/vrf/mocks/VRFCoordinatorV2_5Mock.sol";

interface SdkVm {
    function addr(uint256 key) external returns (address);
    function sign(uint256 key, bytes32 digest) external returns (uint8, bytes32, bytes32);
    function roll(uint256 height) external;
    function warp(uint256 timestamp) external;
    function prank(address sender) external;
    function expectRevert(bytes4 selector) external;
    function expectRevert() external;
    function snapshotState() external returns (uint256);
    function revertToState(uint256 id) external returns (bool);
    function deal(address who, uint256 amount) external;
}

/// Shared set-up and builders for the reference settlement contract tests.
abstract contract SdkBase {
    SdkVm internal constant vm = SdkVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    bytes32 internal constant TWA_TYPEHASH = keccak256(
        "TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );
    uint64 internal constant PRICE = 10_000;
    uint64 internal constant CAP = 1_000_000;
    uint64 internal constant DEPOSIT = 50_000;
    uint64 internal constant VALID_AFTER = 1_792_743_000;
    uint32 internal constant FEED = 1;

    MockAuthToken internal token;
    SampledSettlement internal f;
    SettlementModule internal m; // the module's calls, made on f
    P5LazerVerifier internal lazer;
    P5StorageVerifier internal stor;

    uint256 internal buyerKey = uint256(keccak256("sdk test buyer key"));
    uint256 internal sellerKey = uint256(keccak256("sdk test seller key"));
    uint256 internal feedKey = uint256(keccak256("sdk test feed key"));
    address internal buyer;
    address internal seller;
    address internal tower = address(0x70E7);
    VRFCoordinatorV2_5Mock internal vrf; // Chainlink's VRF v2.5 coordinator mock
    bytes32 internal constant KEY_HASH = keccak256("sdk test vrf key hash");

    bytes32 internal pidP; // plaintext, tier 1a
    bytes32 internal pidC; // ciphertext delivery, tier 1a
    bytes32 internal pidL; // plaintext, tier 1a, response deadline
    bytes32 internal pidT0; // tier 0, block hash stored by the anchor
    uint256 internal epoch;

    function setUp() public virtual {
        vm.warp(VALID_AFTER + 10);
        buyer = vm.addr(buyerKey);
        seller = vm.addr(sellerKey);
        token = new MockAuthToken();
        vrf = new VRFCoordinatorV2_5Mock(1e14, 1e9, 4e15);
        f = _newSettlement();
        m = SettlementModule(address(f));
        lazer = new P5LazerVerifier(vm.addr(feedKey), FEED);
        stor = new P5StorageVerifier();
        vm.roll(f.genesis() + f.EPOCH_BLOCKS() + 5);
        epoch = f.epochOf(block.number);
        pidP = _register(address(lazer), 0, 0, 0, 1);
        pidC = _register(address(lazer), f.F_CT(), 0, 0, 1);
        pidL = _register(address(lazer), 0, 20, 0, 1);
        pidT0 = _register(address(stor), f.F_BLOCKHASH(), 0, 0, 0);
        token.mint(seller, 10_000_000);
        vm.prank(seller);
        token.approve(address(f), type(uint256).max);
        vm.prank(seller);
        m.depositBond(seller, CAP); // b(V*_p) = V with s-hat = 1
        token.mint(buyer, 100_000_000);
        token.mint(tower, 100_000_000);
        vm.prank(buyer);
        token.approve(address(f), type(uint256).max);
        vm.prank(tower);
        token.approve(address(f), type(uint256).max);
    }

    // ------------------------------------------------------- VRF value

    /// A settlement contract on the mock coordinator, its own subscription
    /// funded with native ETH.
    function _newSettlement() internal returns (SampledSettlement s) {
        s = new SampledSettlement(IAuthToken(address(token)), address(vrf), KEY_HASH);
        vm.deal(address(this), 100 ether);
        vrf.fundSubscriptionWithNative{ value: 100 ether }(s.vrfSubId());
    }

    function _ek(bytes32 pid, uint256 ep) internal pure returns (bytes32) {
        return keccak256(abi.encode(pid, bytes32(ep)));
    }

    /// The profile epoch's VRF request, at A_e + 1 if the head is earlier.
    function _requestSample(bytes32 pid, uint256 ep) internal returns (uint256 id) {
        if (block.number <= f.anchorDeadline(ep)) vm.roll(f.anchorDeadline(ep) + 1);
        id = m.requestSample(pid, ep);
    }

    /// The sample value R_e that the word w gives for the request.
    function _valueOf(bytes32 pid, uint256 ep, uint256 id, uint256 w) internal view returns (uint256) {
        return m.sampleValueOf(f.sampleInput(_ek(pid, ep)), id, w);
    }

    /// The coordinator fulfills the request with the word w.
    function _fulfill(uint256 id, uint256 w) internal {
        uint256[] memory ws = new uint256[](1);
        ws[0] = w;
        vrf.fulfillRandomWordsWithOverride(id, address(f), ws);
    }

    function _profile(address verifier, uint8 flags, uint32 rdl, uint8 tier) internal view returns (Profile memory p) {
        p.account = seller;
        p.receiptKey = seller;
        p.unitKey = seller;
        p.verifier = verifier;
        p.codeHash = verifier.codehash;
        p.tier = tier;
        p.flags = flags;
        p.cap = CAP;
        p.minAmount = 1;
        p.responseDeadline = rdl;
        p.deposit = DEPOSIT;
        p.maxFeePerGas = 1 gwei;
        p.epochMultiple = 1;
        p.inputRule = keccak256("input rule");
    }

    function _register(address verifier, uint8 flags, uint32 rdl, uint256 salt, uint8 tier) internal returns (bytes32) {
        Profile memory p = _profile(verifier, flags, rdl, tier);
        p.inputRule = keccak256(abi.encode("input rule", salt, flags, rdl, verifier));
        vm.prank(seller);
        return f.register(p, 2_000_000);
    }

    function _sig(uint256 key, bytes32 d) internal returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, d);
        return abi.encodePacked(r, s, v);
    }

    function _typed(bytes32 dom, bytes32 sh) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked(hex"1901", dom, sh));
    }

    // ------------------------------------------------------------- settle

    function _rs(bytes32 pid, uint256 i, uint64 amount) internal pure returns (Receipt memory r) {
        r.amount = amount;
        r.requestHash = keccak256(abi.encode("req", pid, i));
        r.responseHash = keccak256(abi.encode("resp", pid, i));
        r.ctHash = keccak256(abi.encode("ct", pid, i));
        r.keyHash = keccak256(abi.encode("k", pid, i));
        r.claimsHash = keccak256("claims");
        r.materialCommit = keccak256(abi.encode("material", pid, i));
    }

    function _auth(bytes32 pid, uint256 value, bytes32 nonce) internal view returns (Auth memory a) {
        a = Auth(buyer, f.vaultOf(pid), value, VALID_AFTER, VALID_AFTER + 3600, nonce);
    }

    function _authSig(Auth memory a) internal returns (bytes memory) {
        return _sig(
            buyerKey,
            _typed(
                token.DOMAIN_SEPARATOR(),
                keccak256(abi.encode(TWA_TYPEHASH, a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce))
            )
        );
    }

    /// Settles with the bound nonce; returns the receipt with its nonce set.
    function _buy(bytes32 pid, Receipt memory r, uint256 i) internal returns (Receipt memory) {
        bytes32 salt = keccak256(abi.encode("salt", pid, i));
        r.nonce = f.boundNonce(pid, r.requestHash, r.claimsHash, salt);
        Auth memory a = _auth(pid, r.amount, r.nonce);
        f.settle(a, _authSig(a), r.requestHash, r.claimsHash, salt);
        return r;
    }

    function _ack(bytes32 pid, Receipt memory r, bool accept) internal returns (bytes memory) {
        bytes32 ch = f.profile(pid).codeHash;
        bytes32 hRS = _rsHash(pid, ch, r);
        return _sig(
            buyerKey, f.ackDigest(pid, ch, r.nonce, r.amount, r.requestHash, r.responseHash, r.ctHash, hRS, accept)
        );
    }

    function _rsHash(bytes32 pid, bytes32 ch, Receipt memory r) internal view returns (bytes32) {
        return keccak256(
            abi.encode(
                f.RS_TYPEHASH(),
                r.nonce,
                uint256(r.amount),
                r.requestHash,
                r.responseHash,
                r.ctHash,
                r.keyHash,
                pid,
                ch,
                r.claimsHash,
                r.materialCommit
            )
        );
    }

    // ------------------------------------------------------------- anchor

    function _sort(Leaf[] memory ls) internal pure {
        for (uint256 i = 1; i < ls.length; i++) {
            for (uint256 j = i; j > 0 && ls[j - 1].rs.nonce > ls[j].rs.nonce; j--) {
                Leaf memory t = ls[j];
                ls[j] = ls[j - 1];
                ls[j - 1] = t;
            }
        }
    }

    function _hashes(bytes32 pid, Leaf[] memory ls) internal view returns (bytes32[] memory lv, bytes32[] memory lv0) {
        bytes32 ch = f.profile(pid).codeHash;
        lv = new bytes32[](ls.length);
        lv0 = new bytes32[](ls.length);
        for (uint256 i; i < ls.length; i++) {
            bytes32 hRS = ls[i].unanswered == 0 ? _rsHash(pid, ch, ls[i].rs) : bytes32(0);
            bytes32 l0 = f.leaf0Of(ls[i].rs.nonce, hRS, ls[i].unanswered);
            bool beta = ls[i].sigB.length != 0 && ls[i].unanswered == 0;
            lv0[i] = l0;
            lv[i] = f.leafOf(l0, ls[i].sigB.length != 0 ? keccak256(ls[i].sigB) : bytes32(0), beta, beta && ls[i].accept);
        }
    }

    function _levels(bytes32[] memory leaves) internal view returns (bytes32[][] memory lv) {
        uint256 depth;
        for (uint256 w = leaves.length; w > 1; w = (w + 1) >> 1) depth++;
        lv = new bytes32[][](depth + 1);
        lv[0] = leaves;
        for (uint256 d = 0; d < depth; d++) {
            uint256 w = lv[d].length;
            uint256 next = (w + 1) >> 1;
            lv[d + 1] = new bytes32[](next);
            for (uint256 i; i < next; i++) {
                bytes32 a = lv[d][2 * i];
                bytes32 b = 2 * i + 1 < w ? lv[d][2 * i + 1] : a;
                lv[d + 1][i] = f.node(a, b);
            }
        }
    }

    function _path(bytes32[][] memory lv, uint256 index) internal pure returns (bytes32[] memory p) {
        p = new bytes32[](lv.length - 1);
        for (uint256 d = 0; d + 1 < lv.length; d++) {
            uint256 sib = index ^ 1;
            p[d] = sib < lv[d].length ? lv[d][sib] : lv[d][index];
            index >>= 1;
        }
    }

    function _unit(bytes32 pid, Leaf[] memory ls) internal returns (Unit memory u) {
        u.pid = pid;
        u.epoch = uint32(epoch);
        u.count = uint32(ls.length);
        u.unitNo = 1;
        u.first = ls[0].rs.nonce;
        u.last = ls[ls.length - 1].rs.nonce;
        (bytes32[] memory lv, bytes32[] memory lv0) = _hashes(pid, ls);
        bytes32[][] memory a = _levels(lv);
        bytes32[][] memory b = _levels(lv0);
        u.root = a[a.length - 1][0];
        u.root0 = b[b.length - 1][0];
        u.snapshot = new address[](0);
        u.leaves = ls;
        u.sellerSig = _sig(
            sellerKey,
            _typed(
                f.DOMAIN_SEPARATOR(),
                keccak256(
                    abi.encode(
                        f.UNIT_TYPEHASH(),
                        pid,
                        u.epoch,
                        u.count,
                        u.unitNo,
                        u.first,
                        u.last,
                        u.root,
                        u.root0,
                        keccak256(abi.encode(u.snapshot))
                    )
                )
            )
        );
    }

    function _opening(bytes32 pid, Leaf[] memory ls, uint256 idx) internal view returns (Opening memory o) {
        (bytes32[] memory lv,) = _hashes(pid, ls);
        bytes32[][] memory levels = _levels(lv);
        o.pid = pid;
        o.epoch = uint32(epoch);
        o.unitNo = 1;
        o.index = idx;
        o.rs = ls[idx].rs;
        o.unanswered = ls[idx].unanswered;
        o.sigHash = ls[idx].sigB.length != 0 ? keccak256(ls[idx].sigB) : bytes32(0);
        o.beta = ls[idx].sigB.length != 0 && ls[idx].unanswered == 0;
        o.accept = o.beta && ls[idx].accept;
        o.path = _path(levels, idx);
    }

    function _find(Leaf[] memory ls, bytes32 nonce) internal pure returns (uint256) {
        for (uint256 i; i < ls.length; i++) if (ls[i].rs.nonce == nonce) return i;
        revert("leaf");
    }

    function _toAnchor() internal {
        vm.roll(f.lastBlock(epoch) + f.D_INC() + 1);
    }

    function _anchor(bytes32 pid, Leaf[] memory ls) internal {
        _sort(ls);
        Unit memory u = _unit(pid, ls);
        _toAnchor();
        require(f.anchorUnit(u) == 0, "anchor rejected");
        require(f.epochComplete(pid, epoch), "complete");
    }

    // ---------------------------------------------------------- encryption

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
            assembly ("memory-safe") {
                w := mload(add(add(pt, 0x20), shl(5, j)))
            }
            w ^= ks;
            assembly ("memory-safe") {
                mstore(add(add(ct, 0x20), shl(5, j)), w)
            }
        }
    }

    function _lazerUpdate(uint64 ts, int64 price, uint32 feed, uint256 key) internal returns (bytes memory upd) {
        bytes memory payload = abi.encodePacked(uint32(2479346549), ts, uint8(3), uint8(1), feed, uint8(1), uint8(0), price);
        (uint8 vv, bytes32 r, bytes32 s) = vm.sign(key, keccak256(payload));
        upd = abi.encodePacked(uint32(706910618), r, s, uint8(vv - 27), uint16(payload.length), payload);
    }
}
