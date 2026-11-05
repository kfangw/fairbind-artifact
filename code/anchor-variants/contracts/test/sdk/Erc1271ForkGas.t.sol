// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SampledSettlement, SettlementModule, Profile, Receipt, Leaf, Unit, Opening, Auth, IAuthToken } from "./SampledSettlement.sol";
import { P5LazerVerifier } from "../g10/p5/P5Verifiers.sol";

interface ForkVm {
    function addr(uint256 key) external returns (address);
    function sign(uint256 key, bytes32 digest) external returns (uint8, bytes32, bytes32);
    function roll(uint256 height) external;
    function warp(uint256 timestamp) external;
    function prank(address sender) external;
    function store(address target, bytes32 slot, bytes32 value) external;
    function skip(bool skipTest) external;
}

interface ICswFactory {
    function createAccount(bytes[] calldata owners, uint256 nonce) external payable returns (address);
}

interface ICsw {
    function replaySafeHash(bytes32 hash) external view returns (bytes32);
    function isValidSignature(bytes32 hash, bytes calldata signature) external view returns (bytes4);
}

interface IUsdc {
    function DOMAIN_SEPARATOR() external view returns (bytes32);
    function approve(address spender, uint256 value) external returns (bool);
    function balanceOf(address a) external view returns (uint256);
}

/// Gas of the ERC-1271 isValidSignature check on a Base fork, with the
/// Coinbase Smart Wallet (factory and implementation as deployed on Base) as
/// the contract payer: the bare check (cold, as the settlement contract's
/// gas-capped staticcall meets it), the settlement of a payment the wallet
/// signed (USDC FiatTokenV2_2 checks it through isValidSignature), and the
/// payer-side dispute opening by a delegate whose mandate the wallet signed,
/// against the same opening with an EOA payer. Run with
/// --fork-url <Base RPC> --fork-block-number 52977000 --isolate; skipped
/// without the fork.
contract Erc1271ForkGasTest {
    ForkVm internal constant vm = ForkVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    address internal constant CONSOLE = 0x000000000000000000636F6e736F6c652e6c6f67;
    address internal constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    ICswFactory internal constant FACTORY = ICswFactory(0x0BA5ED0c6AA8c49038F819E587E2633c4A9F428a);
    bytes32 internal constant TWA_TYPEHASH = keccak256(
        "TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );
    uint256 internal constant BALANCE_SLOT = 9;

    struct SignatureWrapper {
        uint256 ownerIndex;
        bytes signatureData;
    }

    uint256 internal ownerKey = uint256(keccak256("1271 fork owner, fork only"));
    uint256 internal sellerKey = uint256(keccak256("1271 fork seller, fork only"));
    uint256 internal feedKey = uint256(keccak256("1271 fork feed, fork only"));
    address internal owner;
    address internal seller;
    address internal tower = address(0x70E7);
    ICsw internal wallet;
    SampledSettlement internal f;
    SettlementModule internal m;
    bytes32 internal pid;
    uint256 internal epoch;
    bool internal onFork;

    function _log(string memory s, uint256 v) internal view {
        (bool ok,) = CONSOLE.staticcall(abi.encodeWithSignature("log(string,uint256)", s, v));
        ok;
    }

    function _setUsdc(address who, uint256 amount) internal {
        vm.store(USDC, keccak256(abi.encode(who, BALANCE_SLOT)), bytes32(amount));
    }

    function _sig(uint256 key, bytes32 d) internal returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(key, d);
        return abi.encodePacked(r, s, v);
    }

    /// The wallet's signature over `h`: the owner signs the wallet's
    /// replay-safe hash, wrapped with the owner index.
    function _walletSig(bytes32 h) internal returns (bytes memory) {
        return abi.encode(SignatureWrapper(0, _sig(ownerKey, wallet.replaySafeHash(h))));
    }

    function setUp() public {
        onFork = block.chainid == 8453 && address(FACTORY).code.length != 0;
        if (!onFork) {
            vm.skip(true);
            return;
        }
        owner = vm.addr(ownerKey);
        seller = vm.addr(sellerKey);
        bytes[] memory owners = new bytes[](1);
        owners[0] = abi.encode(owner);
        wallet = ICsw(FACTORY.createAccount(owners, 0));
        f = new SampledSettlement(IAuthToken(USDC), address(0x5A5A));
        m = SettlementModule(address(f));
        P5LazerVerifier lazer = new P5LazerVerifier(vm.addr(feedKey), 1);
        Profile memory p;
        p.account = seller;
        p.receiptKey = seller;
        p.unitKey = seller;
        p.verifier = address(lazer);
        p.codeHash = address(lazer).codehash;
        p.tier = 1;
        p.cap = 1_000_000;
        p.deposit = 50_000;
        p.inputRule = keccak256("1271 fork input rule");
        p.epochMultiple = 1;
        vm.prank(seller);
        pid = f.register(p, 200_000);
        _setUsdc(seller, 1_000_000);
        _setUsdc(address(wallet), 1_000_000);
        _setUsdc(owner, 1_000_000);
        _setUsdc(tower, 1_000_000);
        vm.prank(seller);
        IUsdc(USDC).approve(address(f), type(uint256).max);
        vm.prank(seller);
        m.depositBond(seller, 1_000_000);
        vm.prank(tower);
        IUsdc(USDC).approve(address(f), type(uint256).max);
        epoch = f.epochOf(block.number);
    }

    function test_isValidSignatureGas() public {
        bytes32 h = keccak256("a digest");
        bytes memory sig = _walletSig(h);
        uint256 g0 = gasleft();
        (bool ok, bytes memory ret) = address(wallet).staticcall{ gas: 50_000 }(abi.encodeCall(ICsw.isValidSignature, (h, sig)));
        uint256 used = g0 - gasleft();
        require(ok && bytes4(ret) == bytes4(0x1626ba7e), "valid");
        _log("isValidSignature (Coinbase Smart Wallet, cold, staticcall incl.)", used);
        uint256 g1 = gasleft();
        (ok,) = address(wallet).staticcall{ gas: 50_000 }(abi.encodeCall(ICsw.isValidSignature, (h, sig)));
        _log("isValidSignature (same, warm)", g1 - gasleft());
        bytes memory bad = _walletSig(keccak256("another digest"));
        uint256 g2 = gasleft();
        (ok, ret) = address(wallet).staticcall{ gas: 50_000 }(abi.encodeCall(ICsw.isValidSignature, (h, bad)));
        _log("isValidSignature, wrong signature (warm)", g2 - gasleft());
        require(!ok || bytes4(ret) != bytes4(0x1626ba7e), "invalid");
    }

    function _settle(address from, bytes32 nonce, bool walletPayer) internal {
        Auth memory a = Auth(from, f.vaultOf(pid), 10_000, block.timestamp - 5, block.timestamp + 600, nonce);
        bytes32 d = keccak256(
            abi.encodePacked(
                hex"1901",
                IUsdc(USDC).DOMAIN_SEPARATOR(),
                keccak256(abi.encode(TWA_TYPEHASH, a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce))
            )
        );
        bytes memory sig = walletPayer ? _walletSig(d) : _sig(ownerKey, d);
        uint256 g0 = gasleft();
        f.settle(a, sig, 0, 0, 0);
        _log(walletPayer ? "settle, contract payer (exec)" : "settle, EOA payer (exec)", g0 - gasleft());
    }

    function _leaf(bytes32 nonce) internal pure returns (Leaf memory l) {
        l.rs.nonce = nonce;
        l.rs.amount = 10_000;
        l.rs.requestHash = keccak256(abi.encode("rq", nonce));
        l.rs.responseHash = keccak256(abi.encode("r", nonce));
        l.rs.ctHash = keccak256(abi.encode("ct", nonce));
        l.rs.keyHash = keccak256(abi.encode("k", nonce));
        l.rs.claimsHash = keccak256("claims");
        l.rs.materialCommit = keccak256(abi.encode("m", nonce));
    }

    function test_contractPayerSettleAndMandateGas() public {
        bytes32 n1 = keccak256("eoa payer nonce");
        bytes32 n2 = keccak256("wallet payer nonce");
        if (n2 < n1) (n1, n2) = (n2, n1);
        bool walletFirst = n1 == keccak256("wallet payer nonce");
        _settle(walletFirst ? address(wallet) : owner, n1, walletFirst);
        _settle(walletFirst ? owner : address(wallet), n2, !walletFirst);
        // one unit with both leaves, unsigned
        Leaf[] memory ls = new Leaf[](2);
        ls[0] = _leaf(n1);
        ls[1] = _leaf(n2);
        bytes32 codeHash = f.profile(pid).codeHash;
        bytes32[] memory lv = new bytes32[](2);
        bytes32[] memory lv0 = new bytes32[](2);
        for (uint256 i; i < 2; i++) {
            bytes32 hRS = f.rsHash(pid, codeHash, ls[i].rs);
            lv0[i] = f.leaf0Of(ls[i].rs.nonce, hRS, 0);
            lv[i] = f.leafOf(lv0[i], bytes32(0), false, false);
        }
        Unit memory u;
        u.pid = pid;
        u.epoch = uint32(epoch);
        u.count = 2;
        u.unitNo = 1;
        u.first = n1;
        u.last = n2;
        u.root = f.node(lv[0], lv[1]);
        u.root0 = f.node(lv0[0], lv0[1]);
        u.snapshot = new address[](0);
        u.leaves = ls;
        u.sellerSig = _sig(
            sellerKey,
            keccak256(
                abi.encodePacked(
                    hex"1901",
                    f.DOMAIN_SEPARATOR(),
                    keccak256(
                        abi.encode(
                            f.UNIT_TYPEHASH(), pid, u.epoch, u.count, u.unitNo, u.first, u.last, u.root, u.root0, keccak256(abi.encode(u.snapshot))
                        )
                    )
                )
            )
        );
        vm.roll(f.lastBlock(epoch) + f.D_INC() + 1);
        require(f.anchorUnit(u) == 0, "anchor");
        for (uint256 i; i < 2; i++) {
            bool isWallet = (i == 0) == walletFirst;
            Opening memory o;
            o.pid = pid;
            o.epoch = uint32(epoch);
            o.unitNo = 1;
            o.index = i;
            o.rs = ls[i].rs;
            o.path = new bytes32[](1);
            o.path[0] = lv[1 - i];
            bytes32 md = f.mandateDigest(pid, ls[i].rs.nonce, tower, 7);
            bytes memory mandate = isWallet ? _walletSig(md) : _sig(ownerKey, md);
            vm.prank(tower);
            uint256 g0 = gasleft();
            f.openDispute(o, 1, mandate, 7);
            _log(isWallet ? "openDispute by delegate, contract payer (exec)" : "openDispute by delegate, EOA payer (exec)", g0 - gasleft());
            require(m.dispute(pid, ls[i].rs.nonce, 1, 1).authorized, "payer side");
        }
    }
}
