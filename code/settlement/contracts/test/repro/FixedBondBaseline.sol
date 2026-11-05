// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { MockEIP3009Token } from "../MockEIP3009Token.sol";

/// Test-only baseline: a fixed seller bond with a judgment window that does
/// not stop sales. Buyers pay the seller directly (immediate release). A fixed
/// deterministic schedule marks every `sampleEvery`-th sale as sampled; a
/// sampled sale can be judged `judgeDelay` blocks after it settled. The first
/// FAIL slashes the whole bond to the treasury and blocks further sales.
/// Buyers receive nothing back in this baseline.
contract FixedBondBaseline {
    MockEIP3009Token public immutable token;
    address public immutable seller;
    address public immutable treasury;
    uint256 public immutable price;
    uint256 public immutable sampleEvery;
    uint256 public immutable judgeDelay;

    uint256 public bond;
    bool public banned;
    uint256 public slashCount;
    uint256 public failCount;
    uint256 public saleCount;
    mapping(uint256 => uint256) public saleBlock;
    mapping(uint256 => address) public saleBuyer;
    mapping(uint256 => bool) public judged;

    error Banned();
    error NotSampled();
    error TooEarly();
    error AlreadyJudged();

    constructor(
        MockEIP3009Token token_,
        address seller_,
        address treasury_,
        uint256 price_,
        uint256 sampleEvery_,
        uint256 judgeDelay_
    ) {
        token = token_;
        seller = seller_;
        treasury = treasury_;
        price = price_;
        sampleEvery = sampleEvery_;
        judgeDelay = judgeDelay_;
    }

    function postBond(uint256 amount) external {
        require(msg.sender == seller, "seller");
        token.transferFrom(seller, address(this), amount);
        bond += amount;
    }

    /// Buyer pays the seller directly; the baseline only records the sale.
    function buy() external returns (uint256 id) {
        if (banned) revert Banned();
        id = ++saleCount;
        saleBlock[id] = block.number;
        saleBuyer[id] = msg.sender;
        token.transferFrom(msg.sender, seller, price);
    }

    function isSampled(uint256 id) public view returns (bool) {
        return id != 0 && id <= saleCount && id % sampleEvery == 0;
    }

    /// Records a verdict for a sampled sale once its judgment delay elapsed.
    function judge(uint256 id, bool fail) external {
        if (!isSampled(id)) revert NotSampled();
        if (block.number < saleBlock[id] + judgeDelay) revert TooEarly();
        if (judged[id]) revert AlreadyJudged();
        judged[id] = true;
        if (!fail) return;
        failCount++;
        if (bond != 0) {
            uint256 amount = bond;
            bond = 0;
            slashCount++;
            token.transfer(treasury, amount);
        }
        banned = true;
    }
}
