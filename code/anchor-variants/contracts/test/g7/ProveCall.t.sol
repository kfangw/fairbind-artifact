// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBase } from "../sdk/SdkBase.sol";
import { Receipt, Leaf, Opening } from "../sdk/SampledSettlement.sol";

/// A verification contract whose answer is set from outside: revert, empty
/// return, one word, or two words. It only reads storage, so it can be
/// called by STATICCALL.
contract ModeVerifier {
    uint256 public mode;
    uint256 public word;

    function set(uint256 m, uint256 w) external {
        mode = m;
        word = w;
    }

    fallback() external {
        uint256 m = mode;
        uint256 w = word;
        assembly {
            switch m
            case 0 { revert(0, 0) }
            case 1 { return(0, 0) }
            case 2 {
                mstore(0, w)
                return(0, 32)
            }
            default {
                mstore(0, w)
                mstore(32, w)
                return(0, 64)
            }
        }
    }
}

/// Symbolic checks of the reference contract's proof call: what a recorded
/// pass implies about the verification contract's answer, no second pass,
/// and where the context fields come from. One sampled sale (no sample
/// value by the deadline, so every sale is sampled) anchored in setUp.
/// Checked with hevm (`prove_` functions; arguments are symbolic): the set-up
/// signs with vm.sign, which halmos turns into a symbolic signature and
/// several set-up paths, while hevm runs the set-up concretely.
contract ProveCallHevmTest is SdkBase {
    bool public IS_TEST = true;

    ModeVerifier internal mv;
    bytes32 internal pidM;
    Leaf[] internal leaves;
    uint256 internal idx;

    function setUp() public override {
        super.setUp();
        mv = new ModeVerifier();
        pidM = _register(address(mv), 0, 0, 7, 1);
        Leaf[] memory ls = new Leaf[](2);
        ls[0].rs = _buy(pidM, _rs(pidM, 0, CAP), 0);
        ls[1].rs = _buy(pidM, _rs(pidM, 1, PRICE), 1);
        bytes32 n0 = ls[0].rs.nonce;
        _anchor(pidM, ls);
        idx = _find(ls, n0);
        for (uint256 i; i < ls.length; i++) leaves.push(ls[i]);
        vm.roll(f.valueDeadline(epoch) + 1);
    }

    function _op() internal view returns (Opening memory) {
        Leaf[] memory ls = leaves;
        return _opening(pidM, ls, idx);
    }

    function _sk(Opening memory o) internal pure returns (bytes32) {
        return keccak256(abi.encode(o.pid, o.rs.nonce));
    }

    function _prove(Opening memory o, bytes memory m) internal returns (bool) {
        try f.prove(o, m) {
            return true;
        } catch {
            return false;
        }
    }

    /// Q1 and Q3: a pass is recorded only when the verification contract
    /// returned exactly one word equal to 1; otherwise the call reverts and
    /// no pass is recorded.
    function prove_Q1Q3_recordOnlyOnOne(uint8 mode8, uint256 word, bytes32 m0, bytes32 m1) public {
        uint256 mode = mode8 % 4;
        mv.set(mode, word);
        Opening memory o = _op();
        bytes memory m = abi.encodePacked(m0, m1);
        bool ok = _prove(o, m);
        bool rec = f.passed(_sk(o));
        assert(ok == rec);
        if (ok) assert(mode == 2 && word == 1);
        if (!(mode == 2 && word == 1)) assert(!ok && !rec);
    }

    /// Q2: after a recorded pass, no further proof call for the sale succeeds,
    /// whatever the material and the verifier's answer.
    function prove_Q2_noSecondPass(uint8 mode8, uint256 word, bytes32 m0, bytes32 m1) public {
        mv.set(2, 1);
        Opening memory o = _op();
        require(_prove(o, hex"01"), "first pass");
        mv.set(mode8 % 4, word);
        bytes memory m2 = abi.encodePacked(m0, m1);
        assert(!_prove(o, m2));
        assert(f.passed(_sk(o)));
    }

    /// Q4: the response hash and material commitment handed to the verifier
    /// come from the anchored leaf: an opening with other values is rejected.
    function prove_Q4_contextFromLeaf(bytes32 rh, bytes32 mc, bytes32 ch, bytes32 qh) public {
        mv.set(2, 1);
        Opening memory o = _op();
        Receipt memory anchored = o.rs;
        o.rs.responseHash = rh;
        o.rs.materialCommit = mc;
        o.rs.claimsHash = ch;
        o.rs.requestHash = qh;
        bool ok = _prove(o, hex"01");
        if (ok) {
            assert(o.rs.responseHash == anchored.responseHash);
            assert(o.rs.materialCommit == anchored.materialCommit);
            assert(o.rs.claimsHash == anchored.claimsHash);
            assert(o.rs.requestHash == anchored.requestHash);
        }
    }

    /// Non-vacuity: the honest opening with a verifier answering 1 passes
    /// and is recorded on every path.
    function prove_honestOpeningPasses() public {
        mv.set(2, 1);
        Opening memory o = _op();
        assert(_prove(o, hex"01"));
        assert(f.passed(_sk(o)));
    }

    /// Set-up check: the unit is stored and the sale is open for a proof.
    function prove_setupState() public view {
        assert(f.epochComplete(pidM, epoch));
        assert(!f.passed(_sk(_op())));
    }

    /// The same as prove_honestOpeningPasses, run concretely by forge.
    function test_honestOpeningPasses() public {
        prove_honestOpeningPasses();
    }
}
