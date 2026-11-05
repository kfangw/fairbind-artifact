// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { G10Base } from "./G10Base.sol";
import { MockEIP3009Token } from "../MockEIP3009Token.sol";
import { SlotCount, G10bSlotVm } from "./G10bSlots.sol";

/// EIP-3009 surface of FiatTokenV2_2 (the USDC on Base) used here.
interface IEIP3009 {
    function transferWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external;

    function receiveWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external;

    function balanceOf(address account) external view returns (uint256);
    function DOMAIN_SEPARATOR() external view returns (bytes32);
    function authorizationState(address authorizer, bytes32 nonce) external view returns (bool);
    function version() external view returns (string memory);
}

interface G10bStoreVm {
    function store(address target, bytes32 slot, bytes32 value) external;
    function load(address target, bytes32 slot) external view returns (bytes32);
    function addr(uint256 key) external returns (address);
    function sign(uint256 key, bytes32 digest) external returns (uint8, bytes32, bytes32);
    function roll(uint256 height) external;
}

/// The EIP-3009 authorization a stock x402 client signs.
struct Auth {
    address from;
    address to;
    uint256 value;
    uint256 validAfter;
    uint256 validBefore;
    bytes32 nonce;
}

/// Sketch of the rule 10 settle (v0.5 R2 (a), R1 (a), R6 (b)). Not the
/// FairBind implementation. The payment's `to` is the profile receiving
/// address (a CREATE2 address derived from the profile identifier; the vault
/// code itself, its one-time deployment and moving its USDC into the hold
/// ledger are outside this sketch). settle looks up the profile by `to`,
/// checks the account (bond at least b(V*), not suspended, not exiting),
/// handles v > V (accepted only by an s = 1 profile and then flagged), calls
/// USDC transferWithAuthorization with the client's signature, writes the sale
/// record (payer, v, settled block, validAfter, V, profile) and adds the sale
/// to the epoch's settlement accumulator. Two record layouts are measured:
/// two slots keyed by (payer, nonce) with the payer stored, and one slot keyed
/// by (payer, nonce) with the payer implied by the key (the anchor leaf would
/// then carry the payer).
contract Rule10Settle {
    IEIP3009 public immutable token;

    /// receiving address => account (160) | V (64) | s = 1 flag (8) | epoch blocks (24)
    mapping(address => uint256) public profileOf;
    /// receiving address => profile index (32) | epoch origin (32)
    mapping(address => uint256) public profileAux;
    /// account => balance (128) | required bond b(V*) (120) | flags (8: suspended 1, exiting 2)
    mapping(address => uint256) public accountOf;
    /// two-slot record
    mapping(bytes32 => uint256) public saleA; // payer (160) | v (64) | settled block (32)
    mapping(bytes32 => uint256) public saleB; // receiving address (160) | V (64) | validAfter (32)
    /// one-slot record: v (64) | settled block (32) | validAfter (40) | V (64) | profile index (32) | flags (8)
    mapping(bytes32 => uint256) public saleC;
    /// (receiving address, epoch) => sales (64) | amount (128) | over-cap sales (64)
    mapping(bytes32 => uint256) public acc;

    event Settled(address indexed receiving, address indexed payer, bytes32 nonce, uint256 value);

    error NotProfile();
    error AccountClosed();
    error BondShort();
    error OverCap();

    constructor(IEIP3009 token_) {
        token = token_;
    }

    function receivingAddress(bytes32 profileId) public view returns (address) {
        // CREATE2 address of a vault deployed by this contract with salt = profile id
        // (init code hash fixed for the sketch).
        return address(
            uint160(uint256(keccak256(abi.encodePacked(bytes1(0xff), address(this), profileId, keccak256("fairbind/vault/v1")))))
        );
    }

    function registerFixture(bytes32 profileId, address account, uint64 cap, bool sOne, uint24 epochBlocks, uint32 index)
        external
        returns (address receiving)
    {
        receiving = receivingAddress(profileId);
        profileOf[receiving] =
            uint256(uint160(account)) | (uint256(cap) << 160) | (sOne ? uint256(1) << 224 : 0) | (uint256(epochBlocks) << 232);
        profileAux[receiving] = uint256(index) | (uint256(uint32(block.number)) << 32);
        accountOf[account] = uint256(5_000_000) | (uint256(1_480_000) << 128);
    }

    function _check(Auth calldata a) internal view returns (uint64 cap, bool over, uint256 epoch, uint32 index) {
        uint256 p = profileOf[a.to];
        if (p == 0) revert NotProfile();
        uint256 acct = accountOf[address(uint160(p))];
        if ((acct >> 248) != 0) revert AccountClosed();
        if (uint128(acct) < uint120(acct >> 128)) revert BondShort();
        cap = uint64(p >> 160);
        over = a.value > cap;
        if (over && ((p >> 224) & 0xff) == 0) revert OverCap();
        uint256 aux = profileAux[a.to];
        index = uint32(aux);
        epoch = (block.number - uint32(aux >> 32)) / uint24(p >> 232);
    }

    function _accumulate(address receiving, uint256 epoch, uint256 value, bool over) internal {
        acc[keccak256(abi.encode(receiving, epoch))] += 1 | (value << 64) | (over ? uint256(1) << 192 : 0);
    }

    /// settle with the two-slot record.
    function settle(Auth calldata a, uint8 v, bytes32 r, bytes32 s) external {
        (uint64 cap, bool over, uint256 epoch,) = _check(a);
        token.transferWithAuthorization(a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce, v, r, s);
        bytes32 k = keccak256(abi.encode(a.from, a.nonce));
        saleA[k] = uint256(uint160(a.from)) | (uint256(uint64(a.value)) << 160) | (uint256(uint32(block.number)) << 224);
        saleB[k] = uint256(uint160(a.to)) | (uint256(cap) << 160) | (uint256(uint32(a.validAfter)) << 224);
        _accumulate(a.to, epoch, a.value, over);
        emit Settled(a.to, a.from, a.nonce, a.value);
    }

    /// settle with the one-slot record.
    function settleOneSlot(Auth calldata a, uint8 v, bytes32 r, bytes32 s) external {
        (uint64 cap, bool over, uint256 epoch, uint32 index) = _check(a);
        token.transferWithAuthorization(a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce, v, r, s);
        saleC[keccak256(abi.encode(a.from, a.nonce))] = uint256(uint64(a.value)) | (uint256(uint32(block.number)) << 64)
            | (uint256(uint40(a.validAfter)) << 96) | (uint256(cap) << 136) | (uint256(index) << 200)
            | (over ? uint256(1) << 232 : 0);
        _accumulate(a.to, epoch, a.value, over);
        emit Settled(a.to, a.from, a.nonce, a.value);
    }

    /// The two-slot settle without the token call: FairBind's own share.
    function settleNoToken(Auth calldata a, uint8 v, bytes32 r, bytes32 s) external {
        (uint64 cap, bool over, uint256 epoch,) = _check(a);
        (v, r, s);
        bytes32 k = keccak256(abi.encode(a.from, a.nonce));
        saleA[k] = uint256(uint160(a.from)) | (uint256(uint64(a.value)) << 160) | (uint256(uint32(block.number)) << 224);
        saleB[k] = uint256(uint160(a.to)) | (uint256(cap) << 160) | (uint256(uint32(a.validAfter)) << 224);
        _accumulate(a.to, epoch, a.value, over);
        emit Settled(a.to, a.from, a.nonce, a.value);
    }
}

/// The earlier build pulls the payment with receiveWithAuthorization (to =
/// the FairBind contract). This puller does only that call, so that the token's
/// share can be measured with the mock token of the earlier measurement and
/// with the real USDC.
contract ReceivePuller {
    function pull(IEIP3009 token, Auth calldata a, uint8 v, bytes32 r, bytes32 s) external {
        token.receiveWithAuthorization(a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce, v, r, s);
    }
}

/// G10b-7: facilitator settlement on the Base fork against the real USDC.
/// Run only with --fork-url (Base mainnet) and --isolate.
contract SettleUsdcGasTest is G10Base, SlotCount {
    IEIP3009 internal constant USDC = IEIP3009(0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913);
    G10bStoreVm internal constant sv = G10bStoreVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    /// FiatTokenV2_2 keeps balanceAndBlacklistStates at slot 9 (checked in setUp).
    uint256 internal constant BALANCE_SLOT = 9;
    bytes32 internal constant TWA_TYPEHASH = keccak256(
        "TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );
    bytes32 internal constant RWA_TYPEHASH = keccak256(
        "ReceiveWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );
    uint256 internal constant PRICE = 10_000; // 0.01 USDC

    uint256 internal buyerKey;
    address internal buyer;
    address internal seller;
    Rule10Settle internal fb;
    address internal receiving;
    uint256 internal nonceSeq;

    function _setUsdc(address who, uint256 amount) internal {
        sv.store(address(USDC), keccak256(abi.encode(who, BALANCE_SLOT)), bytes32(amount));
        require(USDC.balanceOf(who) == amount, "USDC balance slot");
    }

    function setUp() public {
        require(address(USDC).code.length > 0, "run on a Base fork");
        buyerKey = uint256(keccak256("g10b throwaway buyer key, fork only"));
        buyer = sv.addr(buyerKey);
        seller = address(uint160(uint256(keccak256("g10b seller payTo"))));
        _setUsdc(buyer, 1_000_000_000); // 1,000 USDC on the fork only
        _setUsdc(seller, 50_000_000); // a seller that has been paid before
        fb = new Rule10Settle(USDC);
        receiving = fb.registerFixture(keccak256("g10b profile"), address(0xA11CE), 1_000_000, true, 300, 1);
        _setUsdc(receiving, 50_000_000); // the receiving address has been paid before
    }

    function _auth(address to) internal returns (Auth memory a) {
        nonceSeq++;
        a = Auth(buyer, to, PRICE, 0, block.timestamp + 3600, keccak256(abi.encode("g10b nonce", nonceSeq)));
    }

    function _signWith(bytes32 domain, bytes32 typeHash, Auth memory a)
        internal
        returns (uint8 v, bytes32 r, bytes32 s)
    {
        bytes32 sh = keccak256(abi.encode(typeHash, a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce));
        (v, r, s) = sv.sign(buyerKey, keccak256(abi.encodePacked(hex"1901", domain, sh)));
    }

    function _sign(Auth memory a) internal returns (uint8, bytes32, bytes32) {
        return _signWith(USDC.DOMAIN_SEPARATOR(), TWA_TYPEHASH, a);
    }

    function _plain(string memory tag, address to) internal {
        Auth memory a = _auth(to);
        (uint8 v, bytes32 r, bytes32 s) = _sign(a);
        uint256 g = gasleft();
        USDC.transferWithAuthorization(a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce, v, r, s);
        g -= gasleft();
        _rec(address(USDC), abi.encodeCall(USDC.transferWithAuthorization, (a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce, v, r, s)));
        require(USDC.authorizationState(buyer, a.nonce), "authorization used");
        _log(string.concat("G10b-7 plain x402 transferWithAuthorization, ", tag, ", tx gas"), g);
    }

    function _settle(string memory tag, uint8 form) internal {
        Auth memory a = _auth(receiving);
        (uint8 v, bytes32 r, bytes32 s) = _sign(a);
        uint256 before = USDC.balanceOf(receiving);
        uint256 g;
        if (form == 2) {
            g = gasleft();
            fb.settle(a, v, r, s);
            g -= gasleft();
            _rec(address(fb), abi.encodeCall(fb.settle, (a, v, r, s)));
        } else if (form == 1) {
            g = gasleft();
            fb.settleOneSlot(a, v, r, s);
            g -= gasleft();
            _rec(address(fb), abi.encodeCall(fb.settleOneSlot, (a, v, r, s)));
        } else {
            g = gasleft();
            fb.settleNoToken(a, v, r, s);
            g -= gasleft();
            _rec(address(fb), abi.encodeCall(fb.settleNoToken, (a, v, r, s)));
        }
        if (form != 0) require(USDC.balanceOf(receiving) == before + PRICE, "paid into the receiving address");
        _log(string.concat("G10b-7 rule 10 settle sketch, ", tag, ", tx gas"), g);
    }

    function test_gas_plainX402() public {
        _log(string.concat("G10b-7 USDC version ", USDC.version(), " (1 = yes)"), 1);
        // A seller paid before, buyer keeps a balance: the common case.
        _plain("payTo paid before", seller);
        // A payTo that has never held USDC.
        _plain("fresh payTo", address(uint160(uint256(keccak256("g10b fresh payTo")))));
        // The buyer's balance goes to zero (storage refund).
        _setUsdc(buyer, PRICE);
        _plain("payTo paid before, buyer emptied", seller);
    }

    function test_gas_rule10Settle() public {
        // First sale of the epoch: the accumulator slot is new.
        _settle("two-slot record, first sale of the epoch", 2);
        // Later sales of the same epoch: the steady state.
        _settle("two-slot record, later sale of the epoch", 2);
        _settle("one-slot record, later sale of the epoch", 1);
        _settle("two-slot record without the token call, later sale of the epoch", 0);
        // A fresh receiving address (its first payment ever).
        receiving = fb.registerFixture(keccak256("g10b profile 2"), address(0xA11CE), 1_000_000, true, 300, 2);
        _settle("two-slot record, first sale of the epoch, receiving address never paid", 2);
    }

    /// The token's share of the earlier build's settle: receiveWithAuthorization
    /// called by the payee contract, with the earlier measurement's mock token
    /// (signature checks on) and with the real USDC.
    function test_gas_receiveWithAuthorizationShare() public {
        ReceivePuller p = new ReceivePuller();
        MockEIP3009Token mock = new MockEIP3009Token();
        mock.setVerifySignatures(true);
        mock.mint(buyer, 1_000_000_000);
        mock.mint(address(p), 50_000_000);
        _setUsdc(address(p), 50_000_000);
        for (uint256 i; i < 2; i++) {
            // i = 0 warms nothing across transactions (each runs isolated); two rounds show repeatability.
            Auth memory a = _auth(address(p));
            (uint8 v, bytes32 r, bytes32 s) =
                sv.sign(buyerKey, mock.receiveAuthorizationDigest(a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce));
            uint256 g = gasleft();
            p.pull(IEIP3009(address(mock)), a, v, r, s);
            g -= gasleft();
            _rec(address(p), abi.encodeCall(p.pull, (IEIP3009(address(mock)), a, v, r, s)));
            _log(string.concat("G10b-7 receiveWithAuthorization via payee contract, mock token, round ", _u(i + 1), ", tx gas"), g);

            a = _auth(address(p));
            (v, r, s) = _signWith(USDC.DOMAIN_SEPARATOR(), RWA_TYPEHASH, a);
            g = gasleft();
            p.pull(USDC, a, v, r, s);
            g -= gasleft();
            _rec(address(p), abi.encodeCall(p.pull, (USDC, a, v, r, s)));
            require(USDC.authorizationState(buyer, a.nonce), "authorization used");
            _log(string.concat("G10b-7 receiveWithAuthorization via payee contract, real USDC, round ", _u(i + 1), ", tx gas"), g);
        }
    }

    function _logSlots(string memory what, string memory who, Slots memory r) internal {
        string memory p = string.concat("G10b-7 slots, ", what, ", ", who);
        _console(string.concat(p, ": touched"), r.touched);
        _console(string.concat(p, ": written"), r.written);
        _console(string.concat(p, ": created (zero to nonzero)"), r.created);
        _console(string.concat(p, ": changed (nonzero to nonzero)"), r.changed);
        _console(string.concat(p, ": cleared"), r.cleared);
        _console(string.concat(p, ": written back unchanged"), r.same);
    }

    /// Storage breakdown of the steady-state calls (later sale, payTo paid before).
    function test_slots() public {
        G10bSlotVm sl = G10bSlotVm(address(uint160(uint256(keccak256("hevm cheat code")))));
        // plain x402
        Auth memory a = _auth(seller);
        (uint8 v, bytes32 r, bytes32 s) = _sign(a);
        uint256 snap = sl.snapshotState();
        sl.record();
        USDC.transferWithAuthorization(a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce, v, r, s);
        Slots memory u = _slotsOf(address(USDC), snap);
        _logSlots("plain x402", "USDC", u);
        // rule 10 settle sketch, later sale of the epoch (one settle first)
        a = _auth(receiving);
        (v, r, s) = _sign(a);
        fb.settle(a, v, r, s);
        a = _auth(receiving);
        (v, r, s) = _sign(a);
        snap = sl.snapshotState();
        sl.record();
        fb.settle(a, v, r, s);
        Slots memory f = _slotsOf(address(fb), snap);
        snap = sl.snapshotState();
        sl.record();
        fb.settle(a, v, r, s);
        u = _slotsOf(address(USDC), snap);
        _logSlots("rule 10 settle sketch two-slot, later sale", "sketch", f);
        _logSlots("rule 10 settle sketch two-slot, later sale", "USDC", u);
    }
}
