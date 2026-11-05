// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// The halmos symbolic value cheatcodes used here (halmos-cheatcodes, inlined).
interface Svm {
    function createUint(uint256 bitSize, string memory name) external pure returns (uint256);
    function createUint256(string memory name) external pure returns (uint256);
    function createBytes(uint256 byteSize, string memory name) external pure returns (bytes memory);
    function createBytes32(string memory name) external pure returns (bytes32);
    function createBool(string memory name) external pure returns (bool);
    function createAddress(string memory name) external pure returns (address);
}

interface G7Vm {
    function roll(uint256 height) external;
    function warp(uint256 timestamp) external;
    function prank(address sender) external;
    function assume(bool condition) external pure;
}

abstract contract SymTest {
    Svm internal constant svm = Svm(0xF3993A62377BCd56AE39D773740A5390411E8BC9);
    G7Vm internal constant hvm = G7Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
}
