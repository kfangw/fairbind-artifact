// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { G10Base, G10Sig } from "./G10Base.sol";

/// Sketch of a rule 10 tier 1a verification contract that checks a signed
/// price payload itself, without calling the provider's contract and without
/// its freshness check: the signature, the signer in the epoch's snapshot,
/// the feed id, and the time window against the validAfter recorded at
/// settlement (rule 10 v0.3, 1-1 (c)).
///
/// Formats are written from the providers' public sources, not copied:
/// - Pyth Lazer (Pyth Pro) EVM update: 4-byte magic 706910618, r (32), s
///   (32), v (1, 0 or 1), payload length (2), payload; the signature is over
///   keccak256(payload). Payload: 4-byte magic 2479346549, timestamp in
///   microseconds (8), channel (1), feed count (1), then per feed: feed id
///   (4), property count (1), and per property its id (1) and value (here
///   only the price, id 0, int64).
/// - RedStone data package: data points of (feed id 32, value 32), timestamp
///   in milliseconds (6), value byte size (4), data point count (3),
///   signature (65) over keccak256 of everything before it. Packages are
///   concatenated and followed by a 2-byte package count. Here the payload
///   is an argument, not the tail of msg.data, and without the unsigned
///   metadata and marker; each package must come from a distinct
///   authorised signer, and the value is the median.
/// The canonical-input rule (first update after validAfter, with proof that
/// no earlier one exists) is not part of this sketch.
contract SignedOracleVerifier {
    uint32 internal constant LAZER_EVM_MAGIC = 706910618;
    uint32 internal constant LAZER_PAYLOAD_MAGIC = 2479346549;
    uint64 internal constant WINDOW_S = 60;

    mapping(uint64 => mapping(address => bool)) public lazerSnapshot;
    mapping(uint64 => mapping(address => uint8)) public redstoneIndex; // index + 1

    function setLazer(uint64 epoch, address signer) external {
        lazerSnapshot[epoch][signer] = true;
    }

    function setRedstone(uint64 epoch, address[] calldata signers) external {
        for (uint256 i; i < signers.length; i++) redstoneIndex[epoch][signers[i]] = uint8(i + 1);
    }

    function verifyLazer(uint64 epoch, bytes calldata update, uint32 feedId, uint64 validAfter)
        external
        returns (int64 price)
    {
        require(update.length >= 71, "short");
        require(uint32(bytes4(update[0:4])) == LAZER_EVM_MAGIC, "magic");
        uint256 len = uint16(bytes2(update[69:71]));
        require(update.length >= 71 + len, "short");
        bytes calldata payload = update[71:71 + len];
        address s = G10Sig.recoverRsv(
            keccak256(payload), bytes32(update[4:36]), bytes32(update[36:68]), uint8(update[68]) + 27
        );
        require(s != address(0) && lazerSnapshot[epoch][s], "signer");
        require(uint32(bytes4(payload[0:4])) == LAZER_PAYLOAD_MAGIC, "payload magic");
        uint64 ts = uint64(bytes8(payload[4:12]));
        require(ts >= uint64(validAfter) * 1e6 && ts <= (uint64(validAfter) + WINDOW_S) * 1e6, "window");
        require(uint8(payload[13]) >= 1, "feeds");
        require(uint32(bytes4(payload[14:18])) == feedId, "feed");
        require(uint8(payload[18]) >= 1 && uint8(payload[19]) == 0, "price property");
        price = int64(uint64(bytes8(payload[20:28])));
    }

    function verifyRedstone(uint64 epoch, bytes calldata payload, bytes32 feedId, uint64 validAfter, uint256 threshold)
        external
        returns (uint256 value)
    {
        uint256 end = payload.length;
        uint256 count = uint16(bytes2(payload[end - 2:end]));
        end -= 2;
        require(count >= threshold, "threshold");
        uint256[] memory values = new uint256[](count);
        uint256 seen;
        uint256 ts0;
        for (uint256 p; p < count; p++) {
            bytes calldata sig = payload[end - 65:end];
            uint256 points = uint24(bytes3(payload[end - 68:end - 65]));
            uint256 size = uint32(bytes4(payload[end - 72:end - 68]));
            uint256 ts = uint48(bytes6(payload[end - 78:end - 72]));
            uint256 signedLen = points * (32 + size) + 13;
            uint256 start = end - 65 - signedLen;
            address s = G10Sig.recover(keccak256(payload[start:end - 65]), sig);
            uint8 idx = redstoneIndex[epoch][s];
            require(s != address(0) && idx != 0, "signer");
            require(seen & (1 << idx) == 0, "duplicate signer");
            seen |= 1 << idx;
            if (p == 0) ts0 = ts;
            else require(ts == ts0, "timestamps differ");
            bool found;
            for (uint256 q; q < points; q++) {
                uint256 o = start + q * (32 + size);
                if (bytes32(payload[o:o + 32]) == feedId) {
                    values[p] = uint256(bytes32(payload[o + 32:o + 64]));
                    found = true;
                    break;
                }
            }
            require(found, "feed");
            end = start;
        }
        require(ts0 >= uint256(validAfter) * 1000 && ts0 <= (uint256(validAfter) + WINDOW_S) * 1000, "window");
        // Median by insertion sort (count is small).
        for (uint256 i = 1; i < count; i++) {
            uint256 x = values[i];
            uint256 j = i;
            while (j > 0 && values[j - 1] > x) {
                values[j] = values[j - 1];
                j--;
            }
            values[j] = x;
        }
        value = values[count / 2];
    }
}

/// Run with --isolate. Every number is logged; nothing is asserted about gas.
contract SignedOracleGasTest is G10Base {
    SignedOracleVerifier internal v;
    uint64 internal constant EPOCH = 7;
    uint256 internal constant LAZER_KEY = 0x1A2E;
    uint64 internal constant VALID_AFTER = 1_800_000_000;
    uint32 internal constant LAZER_FEED = 1;
    bytes32 internal constant RS_FEED = bytes32("ETH");

    function setUp() public {
        v = new SignedOracleVerifier();
        v.setLazer(EPOCH, hv.addr(LAZER_KEY));
        address[] memory rs = new address[](5);
        for (uint256 i; i < 5; i++) rs[i] = hv.addr(0x2000 + i);
        v.setRedstone(EPOCH, rs);
        hv.roll(1000);
    }

    function _lazerUpdate(uint256 feeds) internal returns (bytes memory upd) {
        bytes memory payload = abi.encodePacked(
            uint32(2479346549), uint64((VALID_AFTER + 2) * 1e6), uint8(1), uint8(feeds)
        );
        for (uint256 f; f < feeds; f++) {
            payload = abi.encodePacked(payload, uint32(LAZER_FEED + f), uint8(1), uint8(0), int64(int256(189_000_000_000 + f)));
        }
        (uint8 vv, bytes32 r, bytes32 s) = hv.sign(LAZER_KEY, keccak256(payload));
        upd = abi.encodePacked(uint32(706910618), r, s, uint8(vv - 27), uint16(payload.length), payload);
    }

    function test_gas_pythLazer() public {
        uint256[3] memory feedCounts = [uint256(1), 4, 16];
        for (uint256 k; k < 3; k++) {
            bytes memory upd = _lazerUpdate(feedCounts[k]);
            uint256 g = gasleft();
            int64 price = v.verifyLazer(EPOCH, upd, LAZER_FEED, VALID_AFTER);
            g -= gasleft();
            _rec(address(v), abi.encodeCall(v.verifyLazer, (EPOCH, upd, LAZER_FEED, VALID_AFTER)));
            require(price == 189_000_000_000, "price");
            _log(string.concat("G10-3 Pyth Lazer-shaped update, ", _u(feedCounts[k]), " feed(s), tx gas"), g);
            _log(
                string.concat("G10-3 Pyth Lazer-shaped update, ", _u(feedCounts[k]), " feed(s), bytes"), upd.length
            );
            _log(
                string.concat("G10-3 Pyth Lazer-shaped update, ", _u(feedCounts[k]), " feed(s), calldata gas"),
                _cdGas(abi.encodeCall(v.verifyLazer, (EPOCH, upd, LAZER_FEED, VALID_AFTER)))
            );
        }
    }

    function _rsPackage(uint256 signerKey, uint256 points, uint256 value) internal returns (bytes memory pkg) {
        bytes memory signed;
        for (uint256 q; q < points; q++) {
            bytes32 id = q == points - 1 ? RS_FEED : bytes32(abi.encodePacked("FEED", uint8(q)));
            signed = abi.encodePacked(signed, id, value + q);
        }
        signed = abi.encodePacked(signed, uint48((VALID_AFTER + 2) * 1000), uint32(32), uint24(points));
        pkg = abi.encodePacked(signed, _sig(signerKey, keccak256(signed)));
    }

    function test_gas_redstone() public {
        uint256[3] memory thresholds = [uint256(1), 3, 5];
        for (uint256 k; k < 3; k++) {
            uint256 t = thresholds[k];
            bytes memory payload;
            for (uint256 p; p < t; p++) payload = abi.encodePacked(payload, _rsPackage(0x2000 + p, 1, 1890e8 + p));
            payload = abi.encodePacked(payload, uint16(t));
            uint256 g = gasleft();
            uint256 val = v.verifyRedstone(EPOCH, payload, RS_FEED, VALID_AFTER, t);
            g -= gasleft();
            _rec(address(v), abi.encodeCall(v.verifyRedstone, (EPOCH, payload, RS_FEED, VALID_AFTER, t)));
            require(val == 1890e8 + t / 2, "median");
            _log(string.concat("G10-3 RedStone-shaped, ", _u(t), " package(s) of 1 point, tx gas"), g);
            _log(string.concat("G10-3 RedStone-shaped, ", _u(t), " package(s), bytes"), payload.length);
            _log(
                string.concat("G10-3 RedStone-shaped, ", _u(t), " package(s), calldata gas"),
                _cdGas(abi.encodeCall(v.verifyRedstone, (EPOCH, payload, RS_FEED, VALID_AFTER, t)))
            );
        }
        // One package carrying 8 data points (the feed is the last one).
        bytes memory pl = abi.encodePacked(_rsPackage(0x2000, 8, 1890e8 - 7), uint16(1));
        uint256 g2 = gasleft();
        v.verifyRedstone(EPOCH, pl, RS_FEED, VALID_AFTER, 1);
        g2 -= gasleft();
        _rec(address(v), abi.encodeCall(v.verifyRedstone, (EPOCH, pl, RS_FEED, VALID_AFTER, 1)));
        _log("G10-3 RedStone-shaped, 1 package of 8 points, tx gas", g2);
    }
}
