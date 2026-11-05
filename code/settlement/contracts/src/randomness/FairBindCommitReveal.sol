// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { IRandomness } from "./IRandomness.sol";

/// Commit-reveal randomness for the per-epoch sampling value (rule D2-16a).
///
/// Round A (the anchor deadline block of an epoch):
///   commit  : block <= A.          commit(A, H(round, sender, secret)) with a deposit.
///   reveal  : A < block <= A + R.  reveal(A, secret) refunds the deposit.
///   value   : block > A + R.       keccak(domain, A, XOR of revealed secrets, #reveals).
/// A commit not revealed by A + R is dropped from the value and its deposit
/// is forfeited to the treasury by forfeit(), callable by anyone. The XOR makes
/// the value independent of the order of reveals. If no commit is revealed the
/// round falls back to the block hash (see finalize); that case is as weak as
/// the block hash source and is flagged by fallbackUsed.
contract FairBindCommitReveal is IRandomness {
    bytes32 public constant DOMAIN = keccak256("fairbind/commit-reveal/v1");
    uint8 internal constant COMMITTED = 1;
    uint8 internal constant REVEALED = 2;
    uint8 internal constant FORFEITED = 3;

    /// Length R of the reveal window in blocks.
    uint32 public immutable revealBlocks;
    /// Deposit per commit, forfeited on non-reveal (wei).
    uint256 public immutable penalty;
    address public immutable treasury;

    struct Round {
        uint32 commits;
        uint32 reveals;
        bool fallbackSet;
        bool fallbackUsed;
        bytes32 mix;
        bytes32 fallbackValue;
    }
    struct Commit {
        bytes32 hash;
        uint8 status;
    }
    mapping(uint64 => Round) public rounds;
    mapping(uint64 => mapping(address => Commit)) public commits;

    event Committed(uint64 indexed round, address indexed who, bytes32 hash);
    event Revealed(uint64 indexed round, address indexed who);
    event Forfeited(uint64 indexed round, address indexed who, uint256 amount);
    event FallbackSet(uint64 indexed round, bytes32 value, bool fromFixedBlock);

    error CommitClosed();
    error RevealNotOpen();
    error RevealClosed();
    error WrongDeposit();
    error AlreadyCommitted();
    error NotCommitted();
    error BadSecret();
    error WindowOpen();
    error NothingToFinalize();
    error TransferFailed();

    constructor(uint32 revealWindow, uint256 depositPenalty, address penaltyTreasury) {
        require(revealWindow != 0 && depositPenalty != 0 && penaltyTreasury != address(0));
        revealBlocks = revealWindow;
        penalty = depositPenalty;
        treasury = penaltyTreasury;
    }

    function delayBlocks() external view override returns (uint32) {
        return revealBlocks;
    }

    /// The hash a participant commits to for a secret.
    function commitmentOf(uint64 round, address who, bytes32 secret) public view returns (bytes32) {
        return keccak256(abi.encode(DOMAIN, block.chainid, address(this), round, who, secret));
    }

    function commit(uint64 round, bytes32 hash) external payable {
        if (block.number > round) revert CommitClosed();
        if (msg.value != penalty) revert WrongDeposit();
        Commit storage c = commits[round][msg.sender];
        if (c.status != 0) revert AlreadyCommitted();
        c.hash = hash;
        c.status = COMMITTED;
        rounds[round].commits++;
        emit Committed(round, msg.sender, hash);
    }

    function reveal(uint64 round, bytes32 secret) external {
        if (block.number <= round) revert RevealNotOpen();
        if (block.number > uint256(round) + revealBlocks) revert RevealClosed();
        Commit storage c = commits[round][msg.sender];
        if (c.status != COMMITTED) revert NotCommitted();
        if (commitmentOf(round, msg.sender, secret) != c.hash) revert BadSecret();
        c.status = REVEALED;
        Round storage r = rounds[round];
        r.reveals++;
        r.mix ^= secret;
        emit Revealed(round, msg.sender);
        _send(msg.sender, penalty);
    }

    /// Drops the commit of a participant who did not reveal in time and sends
    /// its deposit to the treasury. Anyone may call it after the window.
    function forfeit(uint64 round, address who) external {
        if (block.number <= uint256(round) + revealBlocks) revert WindowOpen();
        Commit storage c = commits[round][who];
        if (c.status != COMMITTED) revert NotCommitted();
        c.status = FORFEITED;
        emit Forfeited(round, who, penalty);
        _send(treasury, penalty);
    }

    /// Fixes the fallback value of a round without any reveal. The value is
    /// the hash of block A + R + 1 while the chain still serves it; after that
    /// it is the hash of the previous block, so the caller can pick among the
    /// calls it can make, which is why the case is flagged (fallbackUsed) and
    /// why a keeper should call finalize in the first block it can.
    function finalize(uint64 round) external {
        Round storage r = rounds[round];
        if (block.number <= uint256(round) + revealBlocks + 1) revert WindowOpen();
        if (r.reveals != 0 || r.fallbackSet) revert NothingToFinalize();
        uint256 fixedBlock = uint256(round) + revealBlocks + 1;
        bytes32 h = block.number <= fixedBlock + 256 ? blockhash(fixedBlock) : bytes32(0);
        bool fromFixed = h != bytes32(0);
        if (!fromFixed) h = blockhash(block.number - 1);
        r.fallbackValue = keccak256(abi.encode(DOMAIN, round, h));
        r.fallbackSet = true;
        r.fallbackUsed = true;
        emit FallbackSet(round, r.fallbackValue, fromFixed);
    }

    function valueOf(uint64 round) external view override returns (bool ready, bytes32 value) {
        if (block.number <= uint256(round) + revealBlocks) return (false, bytes32(0));
        Round storage r = rounds[round];
        if (r.reveals != 0) {
            return (true, keccak256(abi.encode(DOMAIN, round, r.mix, r.reveals)));
        }
        if (r.fallbackSet) return (true, r.fallbackValue);
        return (false, bytes32(0));
    }

    function _send(address to, uint256 amount) internal {
        (bool ok,) = to.call{ value: amount }("");
        if (!ok) revert TransferFailed();
    }
}
