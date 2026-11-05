// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { G10Base } from "./G10Base.sol";
import { RLPReader } from "./vendor/optimism/rlp/RLPReader.sol";
import { SecureMerkleTrie } from "./vendor/optimism/trie/SecureMerkleTrie.sol";
import { StorageProofFixture as F } from "./fixtures/StorageProofFixture.sol";

/// Sketch of the tier 0 reference block check of rule 10 v0.3, 0-1 (b): the
/// anchor transaction stored the hash of block B; a proof gives B's header,
/// the account proof of the EIP-2935 history contract against B's state root
/// and the storage proof of slot (ref mod 8191), whose value is the hash of
/// the reference block. Merkle-Patricia verification uses the Optimism
/// libraries vendored under vendor/optimism (MIT, tag op-contracts/v1.8.0).
contract StorageProofVerifier {
    address internal constant HISTORY = 0x0000F90827F1C53a10cb7A02335B175320002935;
    uint256 internal constant WINDOW = 8191;
    mapping(uint64 => bytes32) public anchoredBlockHash;
    mapping(uint64 => uint256) public anchoredBlockNumber;

    function setAnchor(uint64 epoch, bytes32 h, uint256 n) external {
        anchoredBlockHash[epoch] = h;
        anchoredBlockNumber[epoch] = n;
    }

    function _stateRoot(uint64 epoch, bytes memory header) internal view returns (bytes32) {
        require(keccak256(header) == anchoredBlockHash[epoch], "header");
        RLPReader.RLPItem[] memory f = RLPReader.readList(header);
        return bytes32(RLPReader.readBytes(f[3]));
    }

    function _storageRoot(bytes32 stateRoot, bytes[] memory accountProof) internal pure returns (bytes32) {
        bytes memory acct = SecureMerkleTrie.get(abi.encodePacked(HISTORY), accountProof, stateRoot);
        RLPReader.RLPItem[] memory a = RLPReader.readList(acct);
        return bytes32(RLPReader.readBytes(a[2]));
    }

    /// Header only: hash against the stored hash, read the state root.
    function headerOnly(uint64 epoch, bytes memory header) external returns (bytes32) {
        return _stateRoot(epoch, header);
    }

    /// Header and the history contract's account proof.
    function headerAndAccount(uint64 epoch, bytes memory header, bytes[] memory accountProof) external returns (bytes32) {
        return _storageRoot(_stateRoot(epoch, header), accountProof);
    }

    /// The full check: the reference block's hash from the history contract.
    function referenceHash(
        uint64 epoch,
        bytes memory header,
        bytes[] memory accountProof,
        bytes[] memory storageProof,
        uint256 refBlock
    ) external returns (bytes32) {
        uint256 b = anchoredBlockNumber[epoch];
        require(refBlock < b && refBlock + WINDOW >= b, "outside the window");
        bytes32 sr = _storageRoot(_stateRoot(epoch, header), accountProof);
        bytes memory v = SecureMerkleTrie.get(abi.encodePacked(bytes32(refBlock % WINDOW)), storageProof, sr);
        return bytes32(RLPReader.readBytes(v));
    }

    /// One account proof against a given state root (the depth slope).
    function accountOnly(bytes32 stateRoot, address a, bytes[] memory accountProof) external returns (bytes32) {
        bytes memory acct = SecureMerkleTrie.get(abi.encodePacked(a), accountProof, stateRoot);
        return keccak256(acct);
    }

    /// Storage proof only, against a given storage root (the marginal part).
    function storageOnly(bytes32 storageRoot, bytes[] memory storageProof, uint256 slot) external returns (bytes32) {
        bytes memory v = SecureMerkleTrie.get(abi.encodePacked(bytes32(slot)), storageProof, storageRoot);
        return bytes32(RLPReader.readBytes(v));
    }
}

/// Run with --isolate. Every number is logged; nothing is asserted about gas.
contract StorageProofGasTest is G10Base {
    StorageProofVerifier internal v;

    function setUp() public {
        v = new StorageProofVerifier();
        v.setAnchor(1, F.BLOCK_HASH, F.BLOCK_NUMBER);
        hv.roll(F.BLOCK_NUMBER + 10);
    }

    function _bytesOf(bytes[] memory p) internal pure returns (uint256 n) {
        for (uint256 i; i < p.length; i++) n += p[i].length;
    }

    function test_gas_storageProof() public {
        bytes memory h = F.header();
        bytes[] memory ap = F.accountProof();
        bytes[] memory sp = F.storageProof();
        _log("G10-4 header bytes", h.length);
        _log("G10-4 account proof nodes", ap.length);
        _log("G10-4 account proof bytes", _bytesOf(ap));
        _log("G10-4 storage proof nodes", sp.length);
        _log("G10-4 storage proof bytes", _bytesOf(sp));

        uint256 g = gasleft();
        bytes32 sr = v.headerOnly(1, h);
        g -= gasleft();
        _rec(address(v), abi.encodeCall(v.headerOnly, (1, h)));
        require(sr == F.STATE_ROOT, "state root");
        _log("G10-4 header only, tx gas", g);
        _log("G10-4 header only, calldata gas", _cdGas(abi.encodeCall(v.headerOnly, (1, h))));

        g = gasleft();
        bytes32 st = v.headerAndAccount(1, h, ap);
        g -= gasleft();
        _rec(address(v), abi.encodeCall(v.headerAndAccount, (1, h, ap)));
        require(st == F.STORAGE_ROOT, "storage root");
        _log("G10-4 header and account proof, tx gas", g);
        _log("G10-4 header and account proof, calldata gas", _cdGas(abi.encodeCall(v.headerAndAccount, (1, h, ap))));

        g = gasleft();
        bytes32 rh = v.referenceHash(1, h, ap, sp, F.REF_BLOCK);
        g -= gasleft();
        _rec(address(v), abi.encodeCall(v.referenceHash, (1, h, ap, sp, F.REF_BLOCK)));
        require(rh == F.REF_HASH, "reference hash");
        _log("G10-4 full: header, account and storage proof, tx gas", g);
        _log(
            "G10-4 full, calldata gas", _cdGas(abi.encodeCall(v.referenceHash, (1, h, ap, sp, F.REF_BLOCK)))
        );

        g = gasleft();
        rh = v.storageOnly(F.STORAGE_ROOT, sp, F.SLOT);
        g -= gasleft();
        _rec(address(v), abi.encodeCall(v.storageOnly, (F.STORAGE_ROOT, sp, F.SLOT)));
        require(rh == F.REF_HASH, "reference hash (storage only)");
        _log("G10-4 storage proof only, tx gas", g);
        _log("G10-4 storage proof only, calldata gas", _cdGas(abi.encodeCall(v.storageOnly, (F.STORAGE_ROOT, sp, F.SLOT))));
    }

    /// Account proofs of plain accounts of different depths, for the gas per
    /// trie node.
    function test_gas_accountDepth() public {
        for (uint256 i; i < F.PLAIN_COUNT; i++) {
            (address a, bytes[] memory p) = F.plain(i);
            uint256 g = gasleft();
            v.accountOnly(F.STATE_ROOT, a, p);
            g -= gasleft();
            _rec(address(v), abi.encodeCall(v.accountOnly, (F.STATE_ROOT, a, p)));
            string memory tag = string.concat("G10-4 account proof of ", _u(p.length), " nodes (", _u(_bytesOf(p)), " bytes)");
            _log(string.concat(tag, ", tx gas"), g);
            _log(string.concat(tag, ", calldata gas"), _cdGas(abi.encodeCall(v.accountOnly, (F.STATE_ROOT, a, p))));
        }
    }
}
