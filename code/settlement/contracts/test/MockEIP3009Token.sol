// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

contract MockEIP3009Token {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    mapping(bytes32 => bool) public used;
    address public callbackTarget;
    bytes public callbackData;
    bool public callbackSuccess;
    bytes4 public callbackError;
    function setCallback(address target, bytes calldata data) external {
        callbackTarget = target;
        callbackData = data;
    }
    bool public failAuthorization;
    bool public verifySignatures;

    function setVerifySignatures(bool enabled) external {
        verifySignatures = enabled;
    }

    bytes32 public constant TRANSFER_WITH_AUTHORIZATION_TYPEHASH = keccak256(
        "TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );
    bytes32 public constant RECEIVE_WITH_AUTHORIZATION_TYPEHASH = keccak256(
        "ReceiveWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    );

    /// Digest of a TransferWithAuthorization message: the type a stock x402
    /// client signs for a direct payment to the seller.
    function authorizationDigest(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce
    ) public view returns (bytes32) {
        return _digest(TRANSFER_WITH_AUTHORIZATION_TYPEHASH, from, to, value, validAfter, validBefore, nonce);
    }

    /// Digest of a ReceiveWithAuthorization message: the type a FairBind buyer
    /// signs, spendable only by a call from the recipient.
    function receiveAuthorizationDigest(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce
    ) public view returns (bytes32) {
        return _digest(RECEIVE_WITH_AUTHORIZATION_TYPEHASH, from, to, value, validAfter, validBefore, nonce);
    }

    function _digest(
        bytes32 typeHash,
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce
    ) internal view returns (bytes32) {
        bytes32 domain = keccak256(
            abi.encode(
                keccak256(
                    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
                ),
                keccak256("MockUSDC"),
                keccak256("2"),
                block.chainid,
                address(this)
            )
        );
        bytes32 message =
            keccak256(abi.encode(typeHash, from, to, value, validAfter, validBefore, nonce));
        return keccak256(abi.encodePacked(hex"1901", domain, message));
    }

    function mint(address to, uint256 value) external {
        balanceOf[to] += value;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        return true;
    }

    function setFailAuthorization(bool value) external {
        failAuthorization = value;
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _move(msg.sender, to, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        require(allowed >= value, "allowance");
        allowance[from][msg.sender] = allowed - value;
        _move(from, to, value);
        return true;
    }

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
    ) external {
        _authorizedMove(
            TRANSFER_WITH_AUTHORIZATION_TYPEHASH, from, to, value, validAfter, validBefore, nonce, v, r, s
        );
    }

    /// EIP-3009 receiveWithAuthorization: only the payee may submit it, so an
    /// authorization naming a contract as payee is spendable only through that
    /// contract.
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
    ) external {
        require(to == msg.sender, "caller must be the payee");
        _authorizedMove(
            RECEIVE_WITH_AUTHORIZATION_TYPEHASH, from, to, value, validAfter, validBefore, nonce, v, r, s
        );
    }

    function _authorizedMove(
        bytes32 typeHash,
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) internal {
        require(!failAuthorization, "forced failure");
        require(block.timestamp > validAfter && block.timestamp < validBefore, "time");
        require(!used[nonce], "used");
        if (verifySignatures) {
            require(v == 27 || v == 28, "v");
            require(
                uint256(s) <= 0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0,
                "s"
            );
            require(
                from != address(0)
                    && ecrecover(
                        _digest(typeHash, from, to, value, validAfter, validBefore, nonce), v, r, s
                    ) == from,
                "signature"
            );
        }
        if (callbackTarget != address(0)) {
            address target = callbackTarget;
            callbackTarget = address(0);
            bytes memory result;
            (callbackSuccess, result) = target.call(callbackData);
            if (result.length >= 4) callbackError = bytes4(result);
        }
        used[nonce] = true;
        _move(from, to, value);
    }

    function _move(address from, address to, uint256 value) internal {
        require(balanceOf[from] >= value, "balance");
        balanceOf[from] -= value;
        balanceOf[to] += value;
    }
}
