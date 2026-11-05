// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// Integer rules of value-proportional sampling (ADR 0024). The replay engine
/// (experiments/replay/design2.py) computes the same values.
library FairBindDesign2 {
    uint256 internal constant PPM = 1_000_000;

    /// s_ppm(v) = min(PPM, ceil(v * PPM / cap)) for a cap above zero (rule D2-2).
    function samplePpm(uint256 value, uint256 cap) internal pure returns (uint32) {
        uint256 ppm = (value * PPM + cap - 1) / cap;
        return uint32(ppm < PPM ? ppm : PPM);
    }

    /// ceil(ppm * 2^256 / PPM) for 0 < ppm < PPM (rule D2-3). A sample value
    /// below it selects the purchase; ppm = PPM selects without a comparison.
    function threshold(uint32 ppm) internal pure returns (uint256) {
        uint256 quotient = type(uint256).max / PPM;
        uint256 remainder = type(uint256).max % PPM + 1;
        return quotient * ppm + (remainder * ppm + PPM - 1) / PPM;
    }

    /// b = ceil(40 * cap * PPM / (27 * detectFloorPpm)), the deduction of one
    /// confirmed failure (rule D2-5).
    function deduction(uint256 cap, uint32 detectFloorPpm) internal pure returns (uint256) {
        uint256 denominator = 27 * uint256(detectFloorPpm);
        return (40 * cap * PPM + denominator - 1) / denominator;
    }
}
