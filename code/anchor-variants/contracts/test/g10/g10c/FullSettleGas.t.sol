// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { G10Base } from "../G10Base.sol";
import { EcVrf, EcVrfProver } from "./EcVrf.sol";

/// EIP-3009 and ERC-20 surface of FiatTokenV2_2 (the USDC on Base) used here.
interface IUsdc {
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
    function transfer(address to, uint256 value) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
    function DOMAIN_SEPARATOR() external view returns (bytes32);
    function authorizationState(address authorizer, bytes32 nonce) external view returns (bool);
}

interface G10cVm {
    function store(address target, bytes32 slot, bytes32 value) external;
    function addr(uint256 key) external returns (address);
    function sign(uint256 key, bytes32 digest) external returns (uint8, bytes32, bytes32);
    function roll(uint256 height) external;
    function snapshotState() external returns (uint256);
    function revertToState(uint256 id) external returns (bool);
}

/// The EIP-3009 authorization a stock x402 client signs (to = the profile's receiving address).
struct Auth {
    address from;
    address to;
    uint256 value;
    uint256 validAfter;
    uint256 validBefore;
    bytes32 nonce;
}

/// One settled sale as carried by the release call (R6 (b)): the fields the
/// settlement accumulator hashed.
struct Item {
    bytes32 nonce;
    address payer;
    uint64 v;
    uint64 cap;
    bytes32 requestHash;
}

/// Per-profile receiving vault (R1 (a)): deployed by FairBind with CREATE2,
/// salt = profile id, so its address follows from the profile id. It holds
/// USDC and pays only on FairBind's instruction.
contract ProfileVault {
    address private immutable fairbind;
    IUsdc private immutable token;

    constructor(IUsdc token_) {
        fairbind = msg.sender;
        token = token_;
    }

    function pay(address to, uint256 amount) external {
        require(msg.sender == fairbind);
        require(token.transfer(to, amount));
    }

    function pay2(address to1, uint256 a1, address to2, uint256 a2) external {
        require(msg.sender == fairbind);
        require(token.transfer(to1, a1));
        if (a2 != 0) require(token.transfer(to2, a2));
    }
}

/// A fuller sketch of the rule 10 settle path (v0.5 R1 (a), R2 (a), R3 (a),
/// R4 (a), R6). Not the FairBind implementation.
///
/// settle: the payment's `to` is a profile's receiving vault; the profile is
/// looked up by it; the account must hold at least b(V*_p) and be neither
/// suspended nor exiting; v > V only on an s = 1 profile; a nonce already
/// settled on the profile reverts (whatever the payer); settle calls USDC
/// transferWithAuthorization with the client's signature (to = vault). Two
/// hold layouts: LEDGER keeps the USDC in the vault and the hold ledger is the
/// settlement record and accumulator; POOL moves the amount from the vault to
/// FairBind in the same call. Then the sale record (two slots keyed by
/// (receiving, nonce): payer, v, block; validAfter, V, epoch, flags), the
/// optional binding's request hash, the epoch accumulator
/// A <- H(A, nonce, payer, v, cap, request hash) with the count, and an event.
///
/// requestSample: the per-profile-epoch SAMPLE request after A_e (R4 (a)).
/// fulfillSample: verifies an ECVRF proof against the key fixed at
/// deployment, alpha = (chain id, FairBind, profile id, epoch start block),
/// first valid value until M_e.
/// release: the cursor passes one epoch (R6 (a)(c)): the carried items must
/// rebuild the accumulator and count; every sampled item (value, or all items
/// when no value came by M_e) must have a passing proof recorded; the sum less
/// the amounts withheld at the anchor (accepted, disputed) is paid to the
/// seller less a 1% levy, in one token transfer (POOL) or by the vault
/// (LEDGER, seller and levy).
contract FairBindRef {
    IUsdc public immutable token;
    bool public immutable pool; // POOL if true, LEDGER if false
    bool public immutable packedAcc; // accumulator: 224-bit hash | 32-bit count in one slot, else two slots
    uint256 public immutable genesis;
    uint256 public immutable pkX;
    uint256 public immutable pkY;
    bytes32 public immutable vaultInitHash;

    uint256 public constant EPOCH_BLOCKS = 300;
    uint256 public constant A_DELAY = 150; // A_e = epoch end + A_DELAY
    uint256 public constant TAU_V = 10;
    uint256 public constant T_V = 100; // M_e = A_e + TAU_V + 1 + T_V
    uint256 public constant W_B = 50; // W_e = M_e + W_B
    uint256 public constant T_C = 600; // dispute windows end by A_e + T_C here
    uint256 public constant UNIT = 1024; // release unit size (accumulator unit)
    bytes32 public constant NONCE_DOMAIN = keccak256("fairbind/nonce/v1");

    /// receiving => account (160) | V (64) | flags (8: 1 = s = 1)
    mapping(address => uint256) public profileOf;
    /// receiving => profile id
    mapping(address => bytes32) public profileIdOf;
    /// account => balance (128) | b(V*) (96) | flags (8: 1 suspended, 2 exiting)
    mapping(address => uint256) public accountOf;
    /// (receiving, nonce) => payer (160) | v (64) | settled block (32)
    mapping(bytes32 => uint256) public saleA;
    /// (receiving, nonce) => validAfter (64) | V (64) | epoch (32) | over cap (8) | status (8)
    mapping(bytes32 => uint256) public saleB;
    /// (receiving, nonce) => request hash (optional binding)
    mapping(bytes32 => bytes32) public saleReq;
    /// (receiving, epoch, unit) => hash (224) | count (32)   [packed]
    mapping(bytes32 => uint256) public accPacked;
    /// (receiving, epoch, unit) => hash; (receiving, epoch) => count (32) | amount (128)   [two slots]
    mapping(bytes32 => bytes32) public accHash;
    mapping(bytes32 => uint256) public accStat;
    /// (receiving, epoch) => anchored block (64) | count (32) | withheld amount (128)
    mapping(bytes32 => uint256) public anchorOf;
    /// (receiving, epoch) => request block
    mapping(bytes32 => uint256) public sampleReq;
    /// (receiving, epoch) => VRF output
    mapping(bytes32 => uint256) public sampleValue;
    /// (receiving, nonce) => passing proof recorded
    mapping(bytes32 => uint256) public passed;
    /// receiving => next epoch to release
    mapping(address => uint256) public cursor;
    uint256 public levyPool;

    event Settled(address indexed receiving, address indexed payer, bytes32 nonce, uint256 value, uint256 epoch);
    event SampleRequested(address indexed receiving, uint256 indexed epoch, bytes32 alpha);
    event SampleValue(address indexed receiving, uint256 indexed epoch, uint256 value);
    event Released(address indexed receiving, uint256 indexed epoch, uint256 paid, uint256 levy);

    error NotProfile();
    error AccountClosed();
    error BondShort();
    error OverCap();
    error NonceUsed();
    error Binding();
    error Timing();
    error Accumulator();
    error CaseNotPassed();

    constructor(IUsdc token_, bool pool_, bool packed_, uint256 pkX_, uint256 pkY_) {
        token = token_;
        pool = pool_;
        packedAcc = packed_;
        genesis = block.number;
        require(EcVrf.onCurve([pkX_, pkY_]) && pkX_ < EcVrf.N, "vrf key");
        pkX = pkX_;
        pkY = pkY_;
        vaultInitHash = keccak256(abi.encodePacked(type(ProfileVault).creationCode, abi.encode(token_)));
    }

    // ------------------------------------------------------------ profiles

    function receivingAddress(bytes32 profileId) public view returns (address) {
        return address(uint160(uint256(keccak256(abi.encodePacked(bytes1(0xff), address(this), profileId, vaultInitHash)))));
    }

    /// Registration with the vault deployment (R1 (a)); bond and fields are
    /// reduced to what settle reads.
    function register(bytes32 profileId, address account, uint64 cap, bool sOne, uint128 balance, uint96 bondReq)
        external
        returns (address receiving)
    {
        receiving = address(new ProfileVault{ salt: profileId }(token));
        require(receiving == receivingAddress(profileId), "create2");
        profileOf[receiving] = uint256(uint160(account)) | (uint256(cap) << 160) | (sOne ? uint256(1) << 224 : 0);
        profileIdOf[receiving] = profileId;
        accountOf[account] = uint256(balance) | (uint256(bondReq) << 128);
        cursor[receiving] = epochOf(block.number);
    }

    function epochOf(uint256 b) public view returns (uint256) {
        return (b - genesis) / EPOCH_BLOCKS;
    }

    function anchorDeadline(uint256 epoch) public view returns (uint256) {
        return genesis + (epoch + 1) * EPOCH_BLOCKS + A_DELAY;
    }

    // -------------------------------------------------------------- settle

    function settle(Auth calldata a, uint8 v, bytes32 r, bytes32 s) external {
        _settle(a, v, r, s, bytes32(0));
    }

    /// Optional binding: the nonce must be H(domain, profile id, request hash, salt).
    function settleBound(Auth calldata a, uint8 v, bytes32 r, bytes32 s, bytes32 requestHash, bytes32 salt) external {
        if (a.nonce != keccak256(abi.encode(NONCE_DOMAIN, profileIdOf[a.to], requestHash, salt))) revert Binding();
        _settle(a, v, r, s, requestHash);
    }

    function _settle(Auth calldata a, uint8 v, bytes32 r, bytes32 s, bytes32 req) internal {
        uint256 p = profileOf[a.to];
        if (p == 0) revert NotProfile();
        uint256 ac = accountOf[address(uint160(p))];
        if ((ac >> 248) != 0) revert AccountClosed();
        if (uint128(ac) < uint96(ac >> 128)) revert BondShort();
        uint64 cap = uint64(p >> 160);
        bool over = a.value > cap;
        if (over && ((p >> 224) & 1) == 0) revert OverCap();
        bytes32 k = keccak256(abi.encode(a.to, a.nonce));
        if (saleA[k] != 0) revert NonceUsed();
        token.transferWithAuthorization(a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce, v, r, s);
        if (pool) ProfileVault(a.to).pay(address(this), a.value);
        uint256 epoch = epochOf(block.number);
        saleA[k] = uint256(uint160(a.from)) | (uint256(uint64(a.value)) << 160) | (uint256(uint32(block.number)) << 224);
        saleB[k] = uint256(uint64(a.validAfter)) | (uint256(cap) << 64) | (uint256(uint32(epoch)) << 128)
            | (over ? uint256(1) << 160 : 0);
        if (req != 0) saleReq[k] = req;
        _accumulate(a.to, epoch, a.nonce, a.from, uint64(a.value), cap, req);
        emit Settled(a.to, a.from, a.nonce, a.value, epoch);
    }

    function _step(bytes32 prev, bytes32 nonce, address payer, uint64 v, uint64 cap, bytes32 req)
        internal
        pure
        returns (bytes32 h)
    {
        assembly ("memory-safe") {
            let q := mload(0x40)
            mstore(q, prev)
            mstore(add(q, 0x20), nonce)
            mstore(add(q, 0x40), payer)
            mstore(add(q, 0x60), v)
            mstore(add(q, 0x80), cap)
            mstore(add(q, 0xa0), req)
            h := keccak256(q, 0xc0)
        }
    }

    function _accumulate(address receiving, uint256 epoch, bytes32 nonce, address payer, uint64 v, uint64 cap, bytes32 req)
        internal
    {
        if (packedAcc) {
            // unit index from the count is only known after reading; units of 1024 sales
            bytes32 ek = keccak256(abi.encode(receiving, epoch));
            uint256 w0 = accPacked[ek];
            uint256 cnt = uint32(w0);
            if (cnt != 0 && cnt % UNIT == 0) {
                // a new unit starts; the unit's hash goes to its own slot (not reached in these runs)
                bytes32 uk = keccak256(abi.encode(receiving, epoch, cnt / UNIT));
                accPacked[uk] = w0;
                w0 = cnt;
            }
            bytes32 h = _step(bytes32(w0 >> 32 << 32), nonce, payer, v, cap, req);
            accPacked[ek] = (uint256(h) >> 32 << 32) | (cnt + 1);
        } else {
            bytes32 ek = keccak256(abi.encode(receiving, epoch));
            uint256 st = accStat[ek];
            uint256 cnt = uint32(st);
            bytes32 uk = keccak256(abi.encode(receiving, epoch, cnt / UNIT));
            accHash[uk] = _step(accHash[uk], nonce, payer, v, cap, req);
            accStat[ek] = (cnt + 1) | ((uint256(uint128(st >> 32)) + v) << 32);
        }
    }

    // ------------------------------------------------- sample request, VRF

    function alphaOf(address receiving, uint256 epoch) public view returns (bytes32) {
        return keccak256(abi.encode(block.chainid, address(this), profileIdOf[receiving], genesis + epoch * EPOCH_BLOCKS));
    }

    function requestSample(address receiving, uint256 epoch) external {
        bytes32 ek = keccak256(abi.encode(receiving, epoch));
        if (block.number <= anchorDeadline(epoch)) revert Timing();
        if (anchorOf[ek] == 0 || sampleReq[ek] != 0) revert Timing();
        sampleReq[ek] = block.number;
        emit SampleRequested(receiving, epoch, alphaOf(receiving, epoch));
    }

    function fulfillSample(address receiving, uint256 epoch, EcVrf.Proof calldata pr) external {
        bytes32 ek = keccak256(abi.encode(receiving, epoch));
        if (sampleReq[ek] == 0 || sampleValue[ek] != 0) revert Timing();
        if (block.number > anchorDeadline(epoch) + TAU_V + 1 + T_V) revert Timing();
        uint256 beta = EcVrf.verify([pkX, pkY], alphaOf(receiving, epoch), pr);
        sampleValue[ek] = beta;
        emit SampleValue(receiving, epoch, beta);
    }

    /// The proof check alone (no storage), for the breakdown. Not declared view so
    /// that the test calls it with CALL and --isolate runs it as a transaction.
    function verifyOnly(bytes32 alpha, EcVrf.Proof calldata pr) external returns (uint256) {
        return EcVrf.verify([pkX, pkY], alpha, pr);
    }

    // ------------------------------------------------------------- release

    function sampled(uint256 value, bytes32 nonce, uint64 v, uint64 cap) public pure returns (bool) {
        if (value == 0 || v >= cap) return true;
        // U_n < thr(v): threshold ceil(v * 2^64 / cap) on the top 64 bits of U_n
        uint256 u = uint256(keccak256(abi.encode(value, nonce))) >> 192;
        uint256 thr = (uint256(v) * (1 << 64) + cap - 1) / cap;
        return u < thr;
    }

    function release(address receiving, Item[] calldata items) external {
        uint256 epoch = cursor[receiving];
        bytes32 ek = keccak256(abi.encode(receiving, epoch));
        uint256 an = anchorOf[ek];
        uint256 ae = anchorDeadline(epoch);
        uint256 me = ae + TAU_V + 1 + T_V;
        uint256 value = sampleValue[ek];
        // (0) value came or M_e passed; (1) anchored; (3) windows
        if (an == 0 || (value == 0 && block.number <= me)) revert Timing();
        if (block.number <= me + W_B || block.number <= ae + T_C) revert Timing();
        // (b) rebuild the accumulator and count from the carried items (one unit)
        uint256 n = items.length;
        bytes32 h;
        if (!packedAcc) h = bytes32(0);
        uint256 sum;
        for (uint256 i; i < n; i++) {
            Item calldata it = items[i];
            h = _step(packedAcc ? bytes32(uint256(h) >> 32 << 32) : h, it.nonce, it.payer, it.v, it.cap, it.requestHash);
            sum += it.v;
            // (2) every sampled case closed by a passing proof
            if (sampled(value, it.nonce, it.v, it.cap)) {
                if (passed[keccak256(abi.encode(receiving, it.nonce))] == 0) revert CaseNotPassed();
            }
        }
        if (packedAcc) {
            if (accPacked[ek] != ((uint256(h) >> 32 << 32) | n)) revert Accumulator();
        } else {
            if (accHash[keccak256(abi.encode(receiving, epoch, uint256(0)))] != h || uint32(accStat[ek]) != n) {
                revert Accumulator();
            }
        }
        if (uint32(an >> 64) != n) revert Accumulator();
        // (c) pay the sum less what the anchor withheld (accepted, disputed), less the levy
        uint256 pay = sum - uint128(an >> 96);
        uint256 levy = pay / 100;
        cursor[receiving] = epoch + 1;
        address seller = address(uint160(profileOf[receiving]));
        if (pool) {
            levyPool += levy;
            require(token.transfer(seller, pay - levy));
        } else {
            ProfileVault(receiving).pay2(seller, pay - levy, address(this), levy);
        }
        emit Released(receiving, epoch, pay - levy, levy);
    }

    // ------------------------------------------------------- set-up only

    function anchorFixture(address receiving, uint256 epoch, uint32 count, uint128 withheld) external {
        anchorOf[keccak256(abi.encode(receiving, epoch))] =
            uint256(uint64(block.number)) | (uint256(count) << 64) | (uint256(withheld) << 96);
    }

    function sampleFixture(address receiving, uint256 epoch, uint256 value) external {
        bytes32 ek = keccak256(abi.encode(receiving, epoch));
        sampleReq[ek] = block.number;
        sampleValue[ek] = value;
    }

    function passFixture(address receiving, bytes32[] calldata nonces) external {
        for (uint256 i; i < nonces.length; i++) passed[keccak256(abi.encode(receiving, nonces[i]))] = 1;
    }
}

/// G10c-1, G10c-2: the fuller settle path, the sample request, the VRF value
/// acceptance and the cursor release, on the Base fork against the real USDC.
/// Run only with --fork-url (Base mainnet) and --isolate.
contract FullSettleGasTest is G10Base {
    IUsdc internal constant USDC = IUsdc(0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913);
    G10cVm internal constant sv = G10cVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 internal constant BALANCE_SLOT = 9; // FiatTokenV2_2 balanceAndBlacklistStates
    bytes32 internal constant TWA_TYPEHASH = keccak256(
        "TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );
    uint256 internal constant PRICE = 10_000; // 0.01 USDC
    uint64 internal constant CAP = 1_000_000; // V = 1 USDC

    uint256 internal buyerKey;
    address internal buyer;
    address internal seller;
    uint256 internal vrfKey;
    uint256[2] internal vrfPk;
    FairBindRef internal fbL; // LEDGER, packed accumulator
    FairBindRef internal fbP; // POOL, packed accumulator
    FairBindRef internal fbU; // LEDGER, two-slot accumulator
    address internal recvL;
    address internal recvP;
    address internal recvU;
    uint256 internal nonceSeq;
    uint256 internal profileSeq;

    function _setUsdc(address who, uint256 amount) internal {
        sv.store(address(USDC), keccak256(abi.encode(who, BALANCE_SLOT)), bytes32(amount));
        require(USDC.balanceOf(who) == amount, "USDC balance slot");
    }

    function _profile(FairBindRef f, bool paidBefore, string memory tag) internal returns (address recv) {
        profileSeq++;
        bytes32 pid = keccak256(abi.encode("g10c profile", profileSeq));
        uint256 g = gasleft();
        recv = f.register(pid, seller, CAP, true, 5_000_000, 1_480_000);
        g -= gasleft();
        _rec(address(f), abi.encodeCall(f.register, (pid, seller, CAP, true, 5_000_000, 1_480_000)));
        _log(string.concat("G10c-1 register with vault deployment, ", tag, ", tx gas"), g);
        if (paidBefore && !f.pool()) _setUsdc(recv, 50_000_000);
    }

    function setUp() public {
        require(address(USDC).code.length > 0, "run on a Base fork");
        buyerKey = uint256(keccak256("g10c throwaway buyer key, fork only"));
        buyer = sv.addr(buyerKey);
        seller = address(uint160(uint256(keccak256("g10c seller account"))));
        _setUsdc(buyer, 1_000_000_000); // 1,000 USDC on the fork only
        _setUsdc(seller, 50_000_000); // the seller's payout address has been paid before
        vrfKey = uint256(keccak256("g10c throwaway vrf key, fork only")) % EcVrf.N;
        vrfPk = EcVrfProver.publicKey(vrfKey);
        require(vrfPk[0] < EcVrf.N && EcVrf.addrOf(vrfPk) == sv.addr(vrfKey), "vrf key");
        fbL = new FairBindRef(USDC, false, true, vrfPk[0], vrfPk[1]);
        fbP = new FairBindRef(USDC, true, true, vrfPk[0], vrfPk[1]);
        fbU = new FairBindRef(USDC, false, false, vrfPk[0], vrfPk[1]);
        _setUsdc(address(fbP), 50_000_000); // the pool already holds proceeds
        recvL = _profile(fbL, true, "ledger");
        recvP = _profile(fbP, true, "pool");
        recvU = _profile(fbU, true, "ledger, two-slot accumulator");
    }

    function _auth(address to, uint256 value) internal returns (Auth memory a) {
        nonceSeq++;
        a = Auth(buyer, to, value, 0, block.timestamp + 3600, keccak256(abi.encode("g10c nonce", nonceSeq)));
    }

    function _sign(Auth memory a) internal returns (uint8 v, bytes32 r, bytes32 s) {
        bytes32 sh = keccak256(abi.encode(TWA_TYPEHASH, a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce));
        (v, r, s) = sv.sign(buyerKey, keccak256(abi.encodePacked(hex"1901", USDC.DOMAIN_SEPARATOR(), sh)));
    }

    function _settle(FairBindRef f, address recv, uint256 value, string memory tag) internal returns (Auth memory a) {
        a = _auth(recv, value);
        (uint8 v, bytes32 r, bytes32 s) = _sign(a);
        uint256 vb = USDC.balanceOf(recv);
        uint256 pb = USDC.balanceOf(address(f));
        uint256 g = gasleft();
        f.settle(a, v, r, s);
        g -= gasleft();
        _rec(address(f), abi.encodeCall(f.settle, (a, v, r, s)));
        if (f.pool()) {
            require(USDC.balanceOf(recv) == vb && USDC.balanceOf(address(f)) == pb + value, "pooled");
        } else {
            require(USDC.balanceOf(recv) == vb + value, "held in the vault");
        }
        if (bytes(tag).length != 0) _log(string.concat("G10c-1 settle, ", tag, ", tx gas"), g);
    }

    /// G10c-1: the settle cases.
    function test_gas_settle() public {
        // LEDGER, packed accumulator
        _settle(fbL, recvL, PRICE, "ledger, first sale of the epoch");
        _settle(fbL, recvL, PRICE, "ledger, later sale of the epoch");
        _settle(fbL, recvL, PRICE, "ledger, later sale of the epoch (again)");
        _settle(fbL, recvL, 2 * CAP, "ledger, later sale, v > V on an s = 1 profile");
        // optional binding (FairBind-aware client)
        {
            bytes32 req = keccak256("g10c request");
            bytes32 salt = keccak256(abi.encode("g10c salt", nonceSeq));
            Auth memory a = _auth(recvL, PRICE);
            a.nonce = keccak256(abi.encode(fbL.NONCE_DOMAIN(), fbL.profileIdOf(recvL), req, salt));
            (uint8 v, bytes32 r, bytes32 s) = _sign(a);
            uint256 g = gasleft();
            fbL.settleBound(a, v, r, s, req, salt);
            g -= gasleft();
            _rec(address(fbL), abi.encodeCall(fbL.settleBound, (a, v, r, s, req, salt)));
            _log("G10c-1 settle, ledger, later sale, optional binding (request hash stored), tx gas", g);
        }
        // a vault that has never received USDC (first sale of the profile, so also of the epoch)
        address fresh = _profile(fbL, false, "ledger, fresh vault");
        _settle(fbL, fresh, PRICE, "ledger, first-time vault (first sale ever)");
        _settle(fbL, fresh, PRICE, "ledger, second sale into that vault");

        // POOL: the vault is empty in the steady state (0 -> v -> 0 within the call)
        _settle(fbP, recvP, PRICE, "pool, first sale of the epoch");
        _settle(fbP, recvP, PRICE, "pool, later sale of the epoch");
        address freshP = _profile(fbP, false, "pool, fresh vault");
        _settle(fbP, freshP, PRICE, "pool, first-time vault (first sale ever)");

        // LEDGER, two-slot accumulator (256-bit hash and count | amount)
        _settle(fbU, recvU, PRICE, "ledger two-slot accumulator, first sale of the epoch");
        _settle(fbU, recvU, PRICE, "ledger two-slot accumulator, later sale of the epoch");

        // the next epoch's first sale on the warmed profile
        sv.roll(block.number + fbL.EPOCH_BLOCKS());
        _settle(fbL, recvL, PRICE, "ledger, first sale of the next epoch");
        _settle(fbP, recvP, PRICE, "pool, first sale of the next epoch");
    }

    // ------------------------------------------------- seal, VRF, release

    function _items(FairBindRef f, address recv, uint256 m, uint256 k) internal returns (Item[] memory it, uint256 epoch) {
        it = new Item[](m);
        epoch = f.epochOf(block.number);
        for (uint256 i; i < m; i++) {
            uint256 value = i < k ? CAP : PRICE; // the first k are sampled with probability 1
            Auth memory a = _settle(f, recv, value, "");
            it[i] = Item(a.nonce, buyer, uint64(value), CAP, bytes32(0));
        }
    }

    /// A sample value under which exactly the first k items are sampled.
    function _valueFor(FairBindRef f, Item[] memory it, uint256 k) internal pure returns (uint256 value) {
        for (uint256 t = 1;; t++) {
            value = uint256(keccak256(abi.encode("g10c sample value", t)));
            uint256 c;
            bool ok = true;
            for (uint256 i; i < it.length; i++) {
                bool sm = f.sampled(value, it[i].nonce, it[i].v, it[i].cap);
                if (sm) c++;
                if (i < k && !sm) ok = false;
            }
            if (ok && c == k) return value;
        }
    }

    function _release(FairBindRef f, address recv, uint256 m, uint256 k, string memory tag) internal {
        uint256 id = sv.snapshotState();
        (Item[] memory it, uint256 epoch) = _items(f, recv, m, k);
        uint256 sum;
        for (uint256 i; i < m; i++) sum += it[i].v;
        f.anchorFixture(recv, epoch, uint32(m), 0);
        f.sampleFixture(recv, epoch, _valueFor(f, it, k));
        bytes32[] memory pass = new bytes32[](k);
        for (uint256 i; i < k; i++) pass[i] = it[i].nonce;
        f.passFixture(recv, pass);
        sv.roll(f.anchorDeadline(epoch) + f.T_C() + 1);
        uint256 sb = USDC.balanceOf(seller);
        uint256 g = gasleft();
        f.release(recv, it);
        g -= gasleft();
        _rec(address(f), abi.encodeCall(f.release, (recv, it)));
        require(USDC.balanceOf(seller) == sb + sum - sum / 100, "seller paid");
        _log(string.concat("G10c-2 release epoch, ", tag, ", m=", _u(m), " sales, k=", _u(k), " closed cases, tx gas"), g);
        sv.revertToState(id);
    }

    function test_gas_release() public {
        _release(fbP, recvP, 1, 0, "pool");
        _release(fbP, recvP, 8, 0, "pool");
        _release(fbP, recvP, 8, 1, "pool");
        _release(fbP, recvP, 8, 4, "pool");
        _release(fbP, recvP, 32, 4, "pool");
        _release(fbP, recvP, 128, 4, "pool");
        _release(fbL, recvL, 1, 0, "ledger");
        _release(fbL, recvL, 8, 0, "ledger");
        _release(fbL, recvL, 8, 1, "ledger");
        _release(fbL, recvL, 8, 4, "ledger");
        _release(fbL, recvL, 32, 4, "ledger");
        _release(fbL, recvL, 128, 4, "ledger");
        _release(fbU, recvU, 8, 4, "ledger two-slot accumulator");
        _release(fbU, recvU, 32, 4, "ledger two-slot accumulator");
    }

    function test_gas_sealAndVrf() public {
        (, uint256 epoch) = _items(fbL, recvL, 8, 0);
        fbL.anchorFixture(recvL, epoch, 8, 0);
        sv.roll(fbL.anchorDeadline(epoch) + 1);
        uint256 g = gasleft();
        fbL.requestSample(recvL, epoch);
        g -= gasleft();
        _rec(address(fbL), abi.encodeCall(fbL.requestSample, (recvL, epoch)));
        _log("G10c-2 sample request (per profile epoch, after A_e), tx gas", g);

        bytes32 alpha = fbL.alphaOf(recvL, epoch);
        uint256 m = uint256(keccak256(abi.encode(vrfKey, alpha, "g10c vrf nonce"))) % EcVrf.N;
        EcVrf.Proof memory pr = EcVrfProver.prove(vrfKey, vrfPk, alpha, m, sv.addr(m));
        // hash-to-curve tries for this alpha, for the record
        _console("G10c-2 VRF hash-to-curve tries (logged, not gas)", _tries(alpha));
        sv.roll(block.number + 5);

        g = gasleft();
        uint256 beta = fbL.verifyOnly(alpha, pr);
        g -= gasleft();
        _rec(address(fbL), abi.encodeCall(fbL.verifyOnly, (alpha, pr)));
        _log("G10c-2 ECVRF proof verification alone (no storage), tx gas", g);

        g = gasleft();
        fbL.fulfillSample(recvL, epoch, pr);
        g -= gasleft();
        _rec(address(fbL), abi.encodeCall(fbL.fulfillSample, (recvL, epoch, pr)));
        require(fbL.sampleValue(keccak256(abi.encode(recvL, epoch))) == beta && beta != 0, "value stored");
        _log("G10c-2 VRF value acceptance (verify, store, event), tx gas", g);

        // verification cost over other inputs (hash-to-curve tries vary)
        for (uint256 i; i < 8; i++) {
            bytes32 al = keccak256(abi.encode("g10c other alpha", i));
            uint256 mm = uint256(keccak256(abi.encode(vrfKey, al, "g10c vrf nonce"))) % EcVrf.N;
            EcVrf.Proof memory pp = EcVrfProver.prove(vrfKey, vrfPk, al, mm, sv.addr(mm));
            g = gasleft();
            fbL.verifyOnly(al, pp);
            g -= gasleft();
            _rec(address(fbL), abi.encodeCall(fbL.verifyOnly, (al, pp)));
            _log(string.concat("G10c-2 ECVRF verification alone, other input ", _u(i), ", tries ", _u(_tries(al)), ", tx gas"), g);
        }

        // a wrong proof is rejected
        pr.s = addmod(pr.s, 1, EcVrf.N);
        try fbL.verifyOnly(alpha, pr) returns (uint256) {
            revert("bad proof accepted");
        } catch { }
    }

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
}
