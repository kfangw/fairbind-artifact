// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBase } from "../SdkBase.sol";
import { MockAuthToken } from "../MockAuthToken.sol";
import { SettlementModule } from "../SampledSettlement.sol";

interface IFiatTokenAdmin {
    function masterMinter() external view returns (address);
    function configureMinter(address minter, uint256 minterAllowedAmount) external returns (bool);
}

interface UsdcForkVm {
    function skip(bool skipTest) external;
}

/// The reference settlement tests on a Base fork with the real USDC
/// (FiatTokenProxy at its Base address, FiatTokenV2_2 implementation) in
/// place of MockAuthToken. The tests keep calling the token through the
/// MockAuthToken type: approve, balanceOf, DOMAIN_SEPARATOR and
/// transferWithAuthorization (bytes signature form) have the same selectors
/// on USDC, and mint(address,uint256) is USDC's own minter call, which works
/// because the fork's master minter (impersonated) configures the test
/// contract as a minter. No contract or client code changes; the settlement
/// contract is deployed against USDC. Without a Base fork the tests skip.
abstract contract UsdcFork is SdkBase {
    address internal constant USDC = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;

    /// Switches the test from the mock token to USDC (after SdkBase.setUp);
    /// returns false (and skips) without the fork.
    function _useUsdc() internal returns (bool) {
        if (!_onFork()) {
            UsdcForkVm(address(vm)).skip(true);
            return false;
        }
        token = MockAuthToken(USDC);
        address mm = IFiatTokenAdmin(USDC).masterMinter();
        vm.prank(mm);
        IFiatTokenAdmin(USDC).configureMinter(address(this), type(uint256).max);
        // the balances SdkBase.setUp gave on the mock token, now in USDC
        token.mint(seller, 10_000_000);
        token.mint(buyer, 100_000_000);
        token.mint(tower, 100_000_000);
        // the default settlement contract again, on USDC
        f = _newSettlement();
        m = SettlementModule(address(f));
        return true;
    }

    /// Whether the fork holds Base's USDC. The runs fork Base state through
    /// a local anvil node with chain id 31337 (logs/usdc-fork/commands.txt):
    /// forge treats chain id 8453 as an OP-stack chain and charges each
    /// --isolate transaction an L1 data fee, which the 100 ETH transfer of
    /// SdkBase._newSettlement cannot cover; gas used does not depend on it.
    /// FiatTokenV2_2 derives its EIP-712 domain from block.chainid, and the
    /// tests sign against token.DOMAIN_SEPARATOR().
    function _onFork() internal view returns (bool) {
        return USDC.code.length != 0;
    }
}
