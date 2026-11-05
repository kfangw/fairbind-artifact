#!/usr/bin/env python3

import base64
import json
import math
from fractions import Fraction
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASK64 = (1 << 64) - 1
SECP256K1_HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0
PPM = 1_000_000
# 128 L1 blocks of twelve seconds on a two-second settlement chain.
MIN_BEACON_DELAY_BLOCKS = 768
# Verifiers beyond 3 * maxAssignments (ADR 0023, experiments/verifier_count.py).
VERIFIER_COUNT_MARGIN = 5

ROUND_CONSTANTS = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

ROTATION = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]


def fail(message):
    raise SystemExit(f"spec check failed: {message}")


def expect(actual, expected, label):
    if actual != expected:
        fail(f"{label}: expected {expected!r}, got {actual!r}")


def load(relative):
    with (ROOT / relative).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def rol64(value, shift):
    if shift == 0:
        return value & MASK64
    return ((value << shift) | (value >> (64 - shift))) & MASK64


def keccak_f1600(state):
    for constant in ROUND_CONSTANTS:
        columns = [
            state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
            for x in range(5)
        ]
        delta = [columns[(x - 1) % 5] ^ rol64(columns[(x + 1) % 5], 1) for x in range(5)]
        for y in range(5):
            for x in range(5):
                state[x + 5 * y] ^= delta[x]

        moved = [0] * 25
        for y in range(5):
            for x in range(5):
                moved[y + 5 * ((2 * x + 3 * y) % 5)] = rol64(
                    state[x + 5 * y], ROTATION[x][y]
                )

        for y in range(5):
            row = [moved[x + 5 * y] for x in range(5)]
            for x in range(5):
                state[x + 5 * y] = row[x] ^ ((~row[(x + 1) % 5]) & row[(x + 2) % 5])

        state[0] ^= constant


def keccak256(data):
    rate = 136
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != 0:
        padded.append(0)
    padded[-1] |= 0x80

    state = [0] * 25
    for offset in range(0, len(padded), rate):
        block = padded[offset:offset + rate]
        for lane in range(rate // 8):
            start = lane * 8
            state[lane] ^= int.from_bytes(block[start:start + 8], "little")
        keccak_f1600(state)

    output = bytearray()
    for lane in range(rate // 8):
        output.extend(state[lane].to_bytes(8, "little"))
    return bytes(output[:32])


def hex_bytes(value, size=None):
    if not isinstance(value, str) or not value.startswith("0x"):
        fail(f"invalid hex value {value!r}")
    try:
        result = bytes.fromhex(value[2:])
    except ValueError as error:
        fail(str(error))
    if size is not None and len(result) != size:
        fail(f"{value!r} is not {size} bytes")
    return result


def hash_hex(data):
    return "0x" + keccak256(data).hex()


def word_uint(value):
    return int(value).to_bytes(32, "big")


def word_address(value):
    return b"\x00" * 12 + hex_bytes(value, 20)


def word_bytes16(value):
    return hex_bytes(value, 16) + b"\x00" * 16


def word_bytes32(value):
    return hex_bytes(value, 32)


def digest_typed(domain_separator, struct_hash):
    return hash_hex(b"\x19\x01" + hex_bytes(domain_separator, 32) + hex_bytes(struct_hash, 32))


def check_signature_shape(signature, label):
    raw = hex_bytes(signature, 65)
    s = int.from_bytes(raw[32:64], "big")
    if s == 0 or s > SECP256K1_HALF_N:
        fail(f"{label} does not use low-s form")
    if raw[64] not in (27, 28):
        fail(f"{label} v is not 27 or 28")


def check_keccak_padding_boundaries():
    # Cross-checked against pycryptodome (Crypto.Hash.keccak,
    # digest_bits=256) and foundry's `cast keccak`, for input of the
    # given length where byte i of the input is i % 256. These lengths
    # straddle the rate-136 block boundary (one byte short of a block,
    # and exactly a block) to pin down pad10*1 behavior.
    vectors = {
        0: "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470",
        1: "bc36789e7a1e281436464229828f817d6612f7b477d66591ff96a9e064bcc98a",
        135: "cbdfd9dee5faad3818d6b06f95a219fd290b0e1706f6a82e5a595b9ce9faca62",
        136: "7ce759f1ab7f9ce437719970c26b0a66ff11fe3e38e17df89cf5d29c7d7f807e",
        271: "7c974895b2a88303ff2dc6b58f438ceb0b298cac91099ac0539cc0f477506191",
        272: "fdf2ec49e749960d3c8521a0219af8d03e30e2b3bf19bd16150ee0eaf133d66e",
    }
    for length, expected in vectors.items():
        data = bytes(i % 256 for i in range(length))
        expect(hash_hex(data), "0x" + expected, f"keccak256 padding boundary (len={length})")


def check_domain_hashes(vector):
    names = {
        "KEY_DOMAIN": "fairbind/key/v1",
        "PURCHASE_DOMAIN": "fairbind/v1",
        "HTTP_CANON_DOMAIN": "fairbind/http-canon/v1",
        "EPOCH_LEAF_DOMAIN": "fairbind/epoch-leaf/v1",
        "EPOCH_NODE_DOMAIN": "fairbind/epoch-node/v1",
        "SAMPLE_DOMAIN": "fairbind/sample/v1",
        "ASSIGN_DOMAIN": "fairbind/verifier/v1",
        "RECHECK_DOMAIN": "fairbind/recheck/v1",
        "SERVE_BUNDLE_DOMAIN": "fairbind/serve-bundle/v1",
        "RESPONSE_NODE_DOMAIN": "fairbind/response-node/v1",
    }
    for name, source in names.items():
        expect(hash_hex(source.encode()), vector["domainHashes"][name], name)
    expect(hash_hex(b""), "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470", "Keccak empty")


def check_canonicalization(vector, crypto):
    domain = hex_bytes(vector["canonId"], 32)
    expect(vector["canonId"], crypto["domainHashes"]["HTTP_CANON_DOMAIN"], "canonId")
    for item in vector["positive"]:
        normalized = item["normalized"]
        hashes = item["hashes"]
        values = [
            keccak256(normalized["method"].encode("ascii")),
            keccak256(normalized["path"].encode("ascii")),
            keccak256(normalized["query"].encode("ascii")),
            keccak256(hex_bytes(normalized["headerBlockHex"])),
            keccak256(hex_bytes(item["input"]["bodyHex"])),
        ]
        labels = ["methodHash", "pathHash", "queryHash", "headersHash", "bodyHash"]
        for label, value in zip(labels, values):
            expect("0x" + value.hex(), hashes[label], f"{item['name']} {label}")
        expect(hash_hex(domain + b"".join(values)), hashes["requestHash"], f"{item['name']} requestHash")


def check_identifiers(vector):
    f = vector["fixtures"]
    domains = vector["domainHashes"]
    key_encoded = b"".join([
        word_bytes32(domains["KEY_DOMAIN"]), word_uint(f["chainId"]),
        word_address(f["contractAddress"]), word_uint(f["sellerId"]),
        word_address(f["buyer"]), word_bytes16(f["idempotencyKey"]),
    ])
    expect(hash_hex(key_encoded), vector["purchaseIdentifiers"]["keyId"], "keyId")

    nonce_encoded = b"".join([
        word_bytes32(domains["PURCHASE_DOMAIN"]), word_uint(f["chainId"]),
        word_address(f["contractAddress"]), word_uint(f["sellerId"]),
        word_uint(f["profileId"]), word_bytes32(f["claimsHash"]),
        word_address(f["buyer"]), word_bytes16(f["idempotencyKey"]),
        word_bytes32(f["requestHash"]),
    ])
    expect(hash_hex(nonce_encoded), vector["purchaseIdentifiers"]["nonce"], "nonce")


def eip712_domain(name, version, chain_id, contract):
    type_hash = hash_hex(b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
    encoded = b"".join([
        word_bytes32(type_hash), keccak256(name.encode()), keccak256(version.encode()),
        word_uint(chain_id), word_address(contract),
    ])
    return type_hash, hash_hex(encoded)


def check_typed_data(vector):
    f = vector["fixtures"]
    domain = vector["eip712Domain"]
    type_hash, separator = eip712_domain(domain["name"], domain["version"], domain["chainId"], domain["verifyingContract"])
    expect(type_hash, domain["domainTypeHash"], "FairBind domain type hash")
    expect(separator, domain["domainSeparator"], "FairBind domain separator")

    receipt = vector["receipt"]
    message = receipt["message"]
    receipt_type = "FairBindReceipt(uint8 version,uint32 sellerId,uint32 profileId,bytes32 nonce,bytes32 requestHash,bytes32 responseHash,bytes32 claimsHash,bytes32 predicateCommitment,uint24 epoch,uint64 issuedAt)"
    expect(hash_hex(receipt_type.encode()), receipt["typeHash"], "receipt type hash")
    expect(hash_hex(hex_bytes(message["responseBodyHex"])), message["responseHash"], "receipt response hash")
    encoded = b"".join([
        word_bytes32(receipt["typeHash"]), word_uint(message["version"]),
        word_uint(message["sellerId"]), word_uint(message["profileId"]),
        word_bytes32(message["nonce"]), word_bytes32(message["requestHash"]),
        word_bytes32(message["responseHash"]), word_bytes32(message["claimsHash"]),
        word_bytes32(message["predicateCommitment"]), word_uint(message["epoch"]),
        word_uint(message["issuedAt"]),
    ])
    expect(hash_hex(encoded), receipt["structHash"], "receipt struct hash")
    expect(digest_typed(separator, receipt["structHash"]), receipt["digest"], "receipt digest")
    check_signature_shape(receipt["signature"], "receipt signature")

    alternate = vector["equivocatingReceipt"]
    expect(hash_hex(hex_bytes(alternate["responseBodyHex"])), alternate["responseHash"], "alternate response hash")
    alt_encoded = b"".join([
        word_bytes32(receipt["typeHash"]), word_uint(message["version"]),
        word_uint(message["sellerId"]), word_uint(message["profileId"]),
        word_bytes32(message["nonce"]), word_bytes32(message["requestHash"]),
        word_bytes32(alternate["responseHash"]), word_bytes32(message["claimsHash"]),
        word_bytes32(message["predicateCommitment"]), word_uint(message["epoch"]),
        word_uint(alternate["issuedAt"]),
    ])
    expect(hash_hex(alt_encoded), alternate["structHash"], "alternate receipt struct hash")
    expect(digest_typed(separator, alternate["structHash"]), alternate["digest"], "alternate receipt digest")
    check_signature_shape(alternate["signature"], "alternate receipt signature")

    serve = vector["serveAuthorization"]
    serve_type = "FairBindServeAuthorization(bytes32 nonce,uint8 role,uint64 caseOpenedBlock,uint64 validUntil)"
    expect(hash_hex(serve_type.encode()), serve["typeHash"], "serve type hash")
    serve_message = serve["message"]
    serve_encoded = b"".join([
        word_bytes32(serve["typeHash"]), word_bytes32(serve_message["nonce"]),
        word_uint(serve_message["role"]), word_uint(serve_message["caseOpenedBlock"]),
        word_uint(serve_message["validUntil"]),
    ])
    expect(hash_hex(serve_encoded), serve["structHash"], "serve struct hash")
    expect(digest_typed(separator, serve["structHash"]), serve["digest"], "serve digest")
    check_signature_shape(serve["signature"], "serve signature")

    verdict = vector["verdict"]
    verdict_type = "FairBindVerdict(uint8 version,bytes32 nonce,uint8 stage,uint8 attempt,uint32 verifierId,uint8 verdict,bytes32 evidenceHash)"
    expect(hash_hex(verdict_type.encode()), verdict["typeHash"], "verdict type hash")
    verdict_message = verdict["message"]
    verdict_encoded = b"".join([
        word_bytes32(verdict["typeHash"]), word_uint(verdict_message["version"]),
        word_bytes32(verdict_message["nonce"]), word_uint(verdict_message["stage"]),
        word_uint(verdict_message["attempt"]), word_uint(verdict_message["verifierId"]),
        word_uint(verdict_message["verdict"]), word_bytes32(verdict_message["evidenceHash"]),
    ])
    expect(hash_hex(verdict_encoded), verdict["structHash"], "verdict struct hash")
    expect(digest_typed(separator, verdict["structHash"]), verdict["digest"], "verdict digest")
    check_signature_shape(verdict["signature"], "verdict signature")

    payment = vector["paymentAuthorization"]
    payment_type_hash, payment_separator = eip712_domain(
        payment["tokenName"], payment["tokenVersion"], f["chainId"], payment["tokenAddress"]
    )
    expect(payment_type_hash, domain["domainTypeHash"], "token domain type hash")
    expect(payment_separator, payment["domainSeparator"], "token domain separator")
    # ADR 0016: the buyer signs ReceiveWithAuthorization, which the token
    # accepts only from the payee (the FairBind contract).
    expect(payment["primaryType"], "ReceiveWithAuthorization", "authorization primary type")
    auth_type = "ReceiveWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)"
    expect(hash_hex(auth_type.encode()), payment["typeHash"], "authorization type hash")
    auth = payment["message"]
    auth_encoded = b"".join([
        word_bytes32(payment["typeHash"]), word_address(auth["from"]),
        word_address(auth["to"]), word_uint(auth["value"]),
        word_uint(auth["validAfter"]), word_uint(auth["validBefore"]),
        word_bytes32(auth["nonce"]),
    ])
    expect(hash_hex(auth_encoded), payment["structHash"], "authorization struct hash")
    expect(digest_typed(payment_separator, payment["structHash"]), payment["digest"], "authorization digest")
    check_signature_shape(payment["signature"], "authorization signature")


def check_selection(vector):
    f = vector["fixtures"]
    d = vector["domainHashes"]
    values = vector["selection"]
    expect(hash_hex(b"fairbind/test/epoch-randomness/v1"), values["epochRandomness"], "epoch randomness fixture")
    sample_encoded = b"".join([
        word_bytes32(d["SAMPLE_DOMAIN"]), word_bytes32(values["epochRandomness"]),
        word_uint(f["sellerId"]), word_uint(14), word_bytes32(vector["purchaseIdentifiers"]["nonce"]),
    ])
    sample_value = hash_hex(sample_encoded)
    expect(sample_value, values["sampleValue"], "sample value")
    threshold = values["samplePpm"] * (1 << 256) // PPM
    expect("0x" + threshold.to_bytes(32, "big").hex(), values["sampleThreshold"], "sample threshold")
    expect(int(sample_value, 16) < threshold, values["sampled"], "sample decision")

    expect(hash_hex(b"fairbind/test/case-randomness/v1"), values["caseRandomness"], "case randomness fixture")
    assignment_encoded = b"".join([
        word_bytes32(d["ASSIGN_DOMAIN"]), word_bytes32(values["caseRandomness"]),
        word_bytes32(vector["purchaseIdentifiers"]["nonce"]), word_uint(values["stage"]),
        word_uint(values["attempt"]), word_uint(values["round"]),
    ])
    assignment_value = hash_hex(assignment_encoded)
    expect(assignment_value, values["assignmentValue"], "assignment value")
    expect(str(int(assignment_value, 16) % int(values["totalEffectiveWeight"])), values["ticket"], "assignment ticket")

    expect(hash_hex(b"fairbind/test/review-randomness/v1"), values["reviewRandomness"], "review randomness fixture")
    recheck_encoded = b"".join([
        word_bytes32(d["RECHECK_DOMAIN"]), word_bytes32(values["reviewRandomness"]),
        word_bytes32(vector["purchaseIdentifiers"]["nonce"]),
    ])
    recheck_value = hash_hex(recheck_encoded)
    expect(recheck_value, values["recheckValue"], "recheck value")
    recheck_threshold = values["recheckPpm"] * (1 << 256) // PPM
    expect("0x" + recheck_threshold.to_bytes(32, "big").hex(), values["recheckThreshold"], "recheck threshold")
    expect(int(recheck_value, 16) < recheck_threshold, values["selectedForRecheck"], "recheck decision")


def check_serve_bundle(vector):
    bundle = vector["serveBundle"]
    fixture = vector["fixtures"]
    receipt = vector["receipt"]
    encoded = (
        word_bytes32(vector["domainHashes"]["SERVE_BUNDLE_DOMAIN"])
        + word_bytes32(vector["purchaseIdentifiers"]["nonce"])
        + word_bytes16(fixture["idempotencyKey"])
        + word_bytes32(fixture["requestHash"])
        + word_bytes32(receipt["message"]["responseHash"])
        + word_bytes32(receipt["digest"])
        + word_bytes32(receipt["message"]["predicateCommitment"])
    )
    expect("0x" + encoded.hex(), bundle["encoded"], "serve bundle ABI")
    expect(hash_hex(encoded), bundle["bundleHash"], "serve bundle hash")


def response_root(leaves, domain):
    current = list(leaves)
    while len(current) > 1:
        next_level = []
        for index in range(0, len(current), 2):
            left = current[index]
            right = current[index + 1] if index + 1 < len(current) else left
            next_level.append(hash_hex(domain + word_bytes32(left) + word_bytes32(right)))
        current = next_level
    return current[0]


def check_response_commitment(vector):
    commitment = vector["responseCommitment"]
    body = hex_bytes(vector["receipt"]["message"]["responseBodyHex"])
    chunk_bytes = commitment["chunkBytes"]
    chunks = [body[index:index + chunk_bytes] for index in range(0, len(body), chunk_bytes)]
    if not chunks:
        chunks = [b""]
    leaves = [hash_hex(chunk) for chunk in chunks]
    domain = word_bytes32(vector["domainHashes"]["RESPONSE_NODE_DOMAIN"])
    expect(len(body), commitment["bodyBytes"], "response body length")
    expect(len(chunks), commitment["chunkCount"], "response chunk count")
    expect(response_root(leaves, domain), commitment["root"], "response root")
    expect(commitment["root"], vector["receipt"]["message"]["responseHash"], "receipt response root")

    example = commitment["threeLeafExample"]
    first = hash_hex(domain + word_bytes32(example["leaves"][0]) + word_bytes32(example["leaves"][1]))
    second = hash_hex(domain + word_bytes32(example["leaves"][2]) + word_bytes32(example["leaves"][2]))
    expect([first, second], example["levelOne"], "response tree level one")
    expect(response_root(example["leaves"], domain), example["root"], "response tree root")


def check_merkle(vector):
    leaf_domain = word_bytes32(vector["leafDomain"])
    node_domain = word_bytes32(vector["nodeDomain"])
    current = []
    previous_nonce = -1
    for entry in vector["entries"]:
        nonce_number = int(entry["nonce"], 16)
        if nonce_number <= previous_nonce:
            fail("Merkle entries are not strictly ordered")
        previous_nonce = nonce_number
        value = hash_hex(leaf_domain + word_bytes32(entry["nonce"]) + word_bytes32(entry["receiptLeaf"]))
        expect(value, entry["entryHash"], f"Merkle entry {entry['index']}")
        current.append(value)
    expect(current, vector["levels"][0], "Merkle level zero")

    levels = [current]
    while len(current) > 1:
        next_level = []
        for index in range(0, len(current), 2):
            left = current[index]
            right = current[index + 1] if index + 1 < len(current) else left
            next_level.append(hash_hex(node_domain + word_bytes32(left) + word_bytes32(right)))
        levels.append(next_level)
        current = next_level
    expect(levels, vector["levels"], "Merkle levels")
    expect(current[0], vector["root"], "Merkle root")

    publication = vector["publication"]
    expect(publication["manifest"]["root"], vector["root"], "publication root")
    expect(publication["manifest"]["count"], vector["count"], "publication count")
    expect(
        hash_hex(canonical_json(publication["manifest"])),
        publication["publicationHash"],
        "publication hash",
    )

    for entry in vector["entries"]:
        node = entry["entryHash"]
        index = entry["index"]
        count = vector["count"]
        for sibling in entry["siblings"]:
            if index % 2 == 0:
                node = hash_hex(node_domain + word_bytes32(node) + word_bytes32(sibling))
            else:
                node = hash_hex(node_domain + word_bytes32(sibling) + word_bytes32(node))
            index //= 2
            count = (count + 1) // 2
        expect((index, count, node), (0, 1, vector["root"]), f"inclusion proof {entry['index']}")

    omitted = int(vector["omissionExample"]["omittedNonce"], 16)
    left = int(vector["entries"][vector["omissionExample"]["leftIndex"]]["nonce"], 16)
    right = int(vector["entries"][vector["omissionExample"]["rightIndex"]]["nonce"], 16)
    if not left < omitted < right:
        fail("omission adjacency condition")


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def binomial_tail(n, k, q):
    """P[X >= k] for X ~ Binomial(n, q), exact in rationals.

    The shorter of the two tails is summed and complemented when needed, so
    the number of terms is min(k, n - k + 1).
    """
    if k <= 0:
        return Fraction(1)
    if k > n:
        return Fraction(0)
    if k <= n - k + 1:
        return 1 - sum(math.comb(n, j) * q**j * (1 - q) ** (n - j) for j in range(k))
    return sum(math.comb(n, j) * q**j * (1 - q) ** (n - j) for j in range(k, n + 1))


def wrongful_final_fail_model(basis, p):
    """(u1, u, q): per-verifier, per-judged-case and per-settlement wrongful
    final-failure probabilities of the failureLimit basis, as Fractions.

    A wrongful FINAL(FAIL) against an honest seller needs two independently
    drawn verifiers to err. One verifier errs with probability at most
    w1 = c * (1 - h) + h * alpha, where c is the share of non-honest weight
    that votes against an honest seller (convictionCollusionPpm); w1 is an
    upper bound only for c >= alpha, so c is replaced by max(c, alpha). Paths
    to a wrongful confirmed failure, per judged case (ADR 0021, erratum to
    ADR 0019):
      - initial FAIL, appealed by the seller, party review FAIL: w1^2;
      - initial FAIL, appealed, party review PASS, tiebreak FAIL: at most w1^2
        (w1 * (1 - w1) * w1), the path ADR 0019 left out;
      - initial PASS appealed by an adversarial buyer with probability b_a
        (buyerAppealsEveryPass: b_a = 1), party review FAIL, tiebreak FAIL:
        b_a * w1^2 (tiebreak error bounded by one after the flip);
      - unappealed initial PASS rechecked with probability
        s_re = recheckPpm / PPM, recheck FAIL, tiebreak FAIL: (1 - b_a) *
        s_re * w1^2.
    u = w1^2 * (2 + b_a + (1 - b_a) * s_re), which is 3 * w1^2 at b_a = 1,
    and per settlement q = pi * u with pi = samplePpm / PPM.
    """
    h = Fraction(basis["honestWeightPpm"], PPM)
    alpha = Fraction(basis["falseRejectionPpm"], PPM)
    c = max(Fraction(basis["convictionCollusionPpm"], PPM), alpha)
    s_re = Fraction(p["recheckPpm"], PPM)
    pi = Fraction(p["samplePpm"], PPM)
    b_a = Fraction(1)
    w1 = c * (1 - h) + h * alpha
    u = w1 * w1 * (2 + b_a + (1 - b_a) * s_re)
    return w1, u, pi * u


def check_failure_limit(profile, case_horizon):
    """Recompute failureLimit from the model recorded in failureLimitBasis.

    The settlements that can produce a confirmed failure inside one fixed
    failure window of W blocks are those settled in [w - caseHorizon, w + W]:
    a case opened on a purchase settled before the window can still end inside
    it. Their number is bounded from the rate fields at scale factor one by
    S = ceil(bucketCapacity + refillPpmPerBlock * (W + caseHorizon) / PPM).
    Each becomes a wrongful final failure with probability q = pi * u
    (wrongful_final_fail_model). failureLimit is the least k with
    C(S, k) * q^k <= the target, a union bound on the binomial tail
    P[X >= k]; the recorded union bound and exact tail at that k are recomputed
    as well.
    """
    name = profile["name"]
    p = profile["parameters"]
    a = profile["analysis"]
    basis = a["failureLimitBasis"]
    if basis["honestWeightPpm"] != a["assumedHonestWeightPpm"]:
        fail(f"{name} failureLimitBasis h differs from the detection h")
    if not 0 <= basis["convictionCollusionPpm"] <= PPM:
        fail(f"{name} conviction collusion share")
    for flag in ("recheckPathIncluded", "buyerAppealsEveryPass", "tiebreakOnPartyReview"):
        if basis[flag] is not True:
            fail(f"{name} failureLimitBasis.{flag} must be true")
    expect(basis["settlementBasis"], "failureWindow+caseHorizon", f"{name} settlement basis")
    if not 0 <= p["recheckPpm"] <= PPM:
        fail(f"{name} recheck probability")
    u1, u, q = wrongful_final_fail_model(basis, p)
    expect(math.ceil(u1 * PPM), basis["initialWrongFailPpm"], f"{name} initial wrong-fail probability")
    expect(math.ceil(u * PPM), basis["wrongFinalFailPpm"], f"{name} wrong final-fail probability")
    expect(case_horizon, basis["caseHorizonBlocks"], f"{name} failure limit case horizon")
    settlements = p["bucketCapacity"] + Fraction(
        p["refillPpmPerBlock"] * (p["failureWindowBlocks"] + case_horizon), PPM
    )
    n = math.ceil(settlements)
    expect(n, basis["settlementsPerWindowBound"], f"{name} settlements per window")
    expect(math.ceil(n * Fraction(p["samplePpm"], PPM)), basis["expectedJudgedCasesPerWindow"],
           f"{name} expected judged cases per window")
    expect(f"{float(n * q):.3f}", basis["expectedWrongFinalFailsPerWindow"],
           f"{name} expected wrongful final failures per window")
    target = Fraction(basis["targetWindowProbability"])
    limit = next((k for k in range(1, n + 1) if math.comb(n, k) * q**k <= target), None)
    if limit is None:
        fail(f"{name} no failure limit meets the target")
    expect(limit, p["failureLimit"], f"{name} failure limit")
    union = math.comb(n, limit) * q**limit
    tail = binomial_tail(n, limit, q)
    expect(f"{float(union):.3e}", basis["windowProbabilityBound"], f"{name} window probability bound")
    expect(f"{float(tail):.3e}", basis["binomialTailAtLimit"], f"{name} binomial tail at limit")


def check_profiles(document):
    for profile in document["profiles"]:
        p = profile["parameters"]
        a = profile["analysis"]
        expect(hash_hex(canonical_json(p)), profile["parameterHash"], f"{profile['name']} parameterHash")
        if not 0 < p["effectivePpm"] <= p["samplePpm"] <= PPM:
            fail(f"{profile['name']} probability order")
        headers = p["canonicalHeaders"]
        if headers != sorted(set(headers)) or any(name != name.lower() or not name.isascii() for name in headers):
            fail(f"{profile['name']} canonical headers")
        if not 0 <= p["recheckPpm"] <= PPM:
            fail(f"{profile['name']} recheck probability")
        if not 0 < p["deadlineConfig"]["sealBlocks"] <= 255:
            fail(f"{profile['name']} seal window")
        deadline_names = (
            "anchorBlocks", "openBlocks", "responseBlocks", "claimBlocks",
            "serveBlocks", "judgeBlocks", "evidenceBlocks", "appealBlocks",
        )
        if any(p["deadlineConfig"][name] <= 0 for name in deadline_names):
            fail(f"{profile['name']} zero deadline")
        if p["deadlineConfig"]["responseBlocks"] > p["epochBlocks"] + p["deadlineConfig"]["anchorBlocks"]:
            fail(f"{profile['name']} response exceeds anchor window")
        left = p["bucketCapacity"] * PPM + p["refillPpmPerBlock"] * p["enforcementBlocks"]
        right = p["maxRatePpmPerBlock"] * p["enforcementBlocks"]
        if left > right:
            fail(f"{profile['name']} rate condition")

        deadlines = p["deadlineConfig"]
        opening = max(
            2 * p["epochBlocks"] + deadlines["anchorBlocks"] + p["beaconDelayBlocks"]
            + deadlines["sealBlocks"] + deadlines["openBlocks"],
            deadlines["responseBlocks"] + deadlines["claimBlocks"],
        )
        attempts = p["maxAssignments"] * (deadlines["judgeBlocks"] + 1)
        # Opening, initial stage with one evidence window, appeal window, party
        # review and its tiebreak (ADR 0019), and the block recording the stop.
        judgment_delay = (
            opening
            + attempts + deadlines["evidenceBlocks"]
            + deadlines["appealBlocks"] + 2 * (1 + attempts)
            + 1
        )
        expect(judgment_delay, a["judgmentDelayBlocks"], f"{profile['name']} judgment delay")
        if p["enforcementBlocks"] < judgment_delay:
            fail(f"{profile['name']} enforcement shorter than judgment delay")
        # Two review seals, each of which may reopen once (ADR 0021).
        retention = (
            opening + 3 * (2 + 3 * p["maxAssignments"]) * deadlines["serveBlocks"]
            + 3 * p["maxAssignments"] * (2 * deadlines["judgeBlocks"] + deadlines["evidenceBlocks"] + 2 * deadlines["appealBlocks"] + 2)
            + 2 * 2 * (deadlines["sealBlocks"] + 2)
            + p["marginBlocks"]
        )
        expect(retention, a["retentionFloorBlocks"], f"{profile['name']} retention floor")
        if p["retentionBlocks"] < retention or p["deferBlocks"] < p["retentionBlocks"]:
            fail(f"{profile['name']} retention or deferral")
        if retention < judgment_delay:
            fail(f"{profile['name']} case horizon shorter than judgment delay")
        if p["claimWindowBlocks"] != p["retentionBlocks"]:
            fail(f"{profile['name']} claim window must equal retention")
        if p["beaconDelayBlocks"] < MIN_BEACON_DELAY_BLOCKS:
            fail(f"{profile['name']} beacon delay below 128 L1 blocks")
        if p["beaconSlackL1Blocks"] != 0:
            fail(f"{profile['name']} beacon slack must be zero on a chain without an L1 origin")
        if p["failureLimit"] <= 0 or p["failureWindowBlocks"] <= 0 or p["inconclusiveWindowBlocks"] <= 0:
            fail(f"{profile['name']} failure or inconclusive window")
        if not 0 < p["maxInconclusivePpm"] <= PPM or not 0 <= p["forfeitVerifierPpm"] <= PPM:
            fail(f"{profile['name']} inconclusive threshold or forfeiture split")
        if not 0 < p["bucketCapacityPercentilePpm"] <= PPM:
            fail(f"{profile['name']} bucket capacity percentile")
        # A production build admits only freezeOnInitialFail == false; the
        # admission-override test build accepts either and requires true when
        # retentionBlocks < caseHorizon (ADR 0020).
        if p["freezeOnInitialFail"] is not False:
            fail(f"{profile['name']} freezeOnInitialFail must be false in a production profile")
        if isinstance(p["minJudgedCount"], bool) or not 1 <= p["minJudgedCount"] <= 2**32 - 1:
            fail(f"{profile['name']} minJudgedCount must be at least one")
        basis = a["failureLimitBasis"]
        if basis["measured"] is not False and not isinstance(basis["measured"], bool):
            fail(f"{profile['name']} failure limit basis")
        check_failure_limit(profile, retention)

        expected_count = (PPM + p["effectivePpm"] - 1) // p["effectivePpm"]
        # Bond requirement: g * (1/p + maxRate * max(0, L - D)), in units of one
        # sellerPenalty. With D >= L the rate term is zero.
        exposed_blocks = max(0, judgment_delay - p["deferBlocks"])
        post_count = (p["maxRatePpmPerBlock"] * exposed_blocks + PPM - 1) // PPM
        floor = int(p["maxBadGain"]) * (expected_count + post_count)
        expect(expected_count, a["expectedDetectionCount"], f"{profile['name']} detection count")
        expect(post_count, a["postDetectionCount"], f"{profile['name']} post-detection count")
        expect(str(floor), a["expectedPenaltyFloor"], f"{profile['name']} penalty floor")
        if int(p["sellerPenalty"]) < floor:
            fail(f"{profile['name']} seller penalty")

        honest_correct = a["assumedHonestWeightPpm"] * (PPM - a["assumedFalseAcceptancePpm"]) // PPM
        # Only a necessary idealized ceiling: this does not establish the
        # history-conditional availability/enforcement lower bound in ADR 0009.
        idealized_ceiling = p["samplePpm"] * honest_correct * honest_correct // (PPM * PPM)
        if p["effectivePpm"] > idealized_ceiling:
            fail(f"{profile['name']} exceeds idealized detection ceiling")
        if a.get("conditionalDetectionBoundEstablished") is not False:
            fail(f"{profile['name']} functional defaults must not claim an established conditional bound")
        # ADR 0023: the margin keeps the last of 3 * maxAssignments assignments from
        # failing with probability above 1e-3 (experiments/verifier_count.py).
        if p["minVerifiers"] < 3 * p["maxAssignments"] + VERIFIER_COUNT_MARGIN:
            fail(f"{profile['name']} verifier count")
        if int(p["disputeDeposit"]) < int(p["maxPublicationCost"]):
            fail(f"{profile['name']} publication-cost coverage")
        if int(p["appealDeposit"]) < int(p["maxReviewCost"]):
            fail(f"{profile['name']} appeal-cost coverage")
        if int(p["verifierWrongPenalty"]) < int(p["maxReviewCost"]):
            fail(f"{profile['name']} wrong-verdict coverage")
        response_chunks = max(1, (p["maxResponseBytes"] + 16_383) // 16_384)
        if response_chunks + 2 > p["deadlineConfig"]["serveBlocks"]:
            fail(f"{profile['name']} publication block budget")


def check_predicates(vector):
    data_domain = vector["domains"]["dataCommitment"]
    open_domain = vector["domains"]["openWeightsCommitment"]
    expect(hash_hex(data_domain["text"].encode()), data_domain["hash"], "data commitment domain")
    expect(hash_hex(open_domain["text"].encode()), open_domain["hash"], "open-weights commitment domain")

    claims = vector["claims"]
    expect(hash_hex(canonical_json(claims["value"])), claims["claimsHash"], "predicate claims hash")

    data = vector["dataApiCommitment"]
    data_encoded = (
        word_bytes32(data_domain["hash"])
        + word_uint(data["referenceTime"])
        + word_bytes32(data["sourceSetHash"])
        + word_bytes32(data["tolerancePolicyHash"])
    )
    expect("0x" + data_encoded.hex(), data["encoded"], "data commitment ABI")
    expect(hash_hex(data_encoded), data["predicateCommitment"], "data predicate commitment")
    expect(data["sourceSetHash"], claims["value"]["sourceSetHash"], "data claims source set")
    expect(data["tolerancePolicyHash"], claims["value"]["tolerancePolicyHash"], "data claims tolerance policy")

    open_weights = vector["openWeightsCommitment"]
    open_encoded = (
        word_bytes32(open_domain["hash"])
        + word_bytes32(open_weights["toplocCommitment"])
        + word_bytes32(open_weights["modelHash"])
        + word_bytes32(open_weights["configHash"])
    )
    expect("0x" + open_encoded.hex(), open_weights["encoded"], "open-weights commitment ABI")
    expect(hash_hex(open_encoded), open_weights["predicateCommitment"], "open-weights predicate commitment")

    evidence = vector["evidence"]
    expect(hash_hex(canonical_json(evidence["value"])), evidence["canonicalHash"], "evidence hash")


def check_sortition(vector):
    domain = vector["setDomain"]
    expect(hash_hex(domain["text"].encode()), domain["hash"], "verifier-set domain")
    ids = vector["verifierIds"]
    weights = vector["weights"]
    if ids != sorted(set(ids)) or len(ids) != len(weights) or not ids:
        fail("sortition set order or length")
    total = sum(weights)
    expect(str(total), vector["totalEffectiveWeight"], "sortition total weight")

    head_size = 5 * 32
    ids_tail = word_uint(len(ids)) + b"".join(word_uint(value) for value in ids)
    weights_tail = word_uint(len(weights)) + b"".join(word_uint(value) for value in weights)
    encoded = (
        word_bytes32(domain["hash"])
        + word_uint(vector["profileId"])
        + word_uint(vector["version"])
        + word_uint(head_size)
        + word_uint(head_size + len(ids_tail))
        + ids_tail
        + weights_tail
    )
    expect("0x" + encoded.hex(), vector["encoded"], "sortition ABI")
    expect(hash_hex(encoded), vector["setHash"], "sortition set hash")

    for example in vector["tickets"]:
        ticket = int(example["ticket"])
        if ticket < 0 or ticket >= total:
            fail("sortition ticket outside total weight")
        cumulative = 0
        selected = None
        for verifier_id, weight in zip(ids, weights):
            cumulative += weight
            if ticket < cumulative:
                selected = verifier_id
                break
        expect(selected, example["verifierId"], f"sortition ticket {ticket}")


def without_members(value, names):
    result = dict(value)
    for name in names:
        result.pop(name, None)
    return result


def check_local_refs(value, label):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("$ref", "$id") and not child.startswith("#"):
                fail(f"{label} contains external {key}: {child}")
            check_local_refs(child, label)
    elif isinstance(value, list):
        for child in value:
            check_local_refs(child, label)


def check_x402(crypto):
    required = load("test-vectors/x402-v2/payment-required.json")
    payload = load("test-vectors/x402-v2/payment-payload.json")
    response = load("test-vectors/x402-v2/settlement-response.json")
    receipt = load("test-vectors/x402-v2/fairbind-receipt.json")
    headers = load("test-vectors/x402-v2/headers.json")

    negotiation_schema = without_members(
        load("schemas/fairbind-extension-v1.schema.json"), {"$id", "title", "description"}
    )
    settlement_schema = without_members(
        load("schemas/fairbind-settlement-v1.schema.json"), {"$id", "title", "description"}
    )
    required_ext = required["extensions"]["fairbind"]
    payload_ext = payload["extensions"]["fairbind"]
    response_ext = response["extensions"]["fairbind"]
    if "bondId" not in negotiation_schema["required"] or "bondId" not in negotiation_schema["properties"]:
        fail("x402 negotiation schema must require bondId")
    for name, info in (("PaymentRequired", required_ext["info"]), ("PaymentPayload", payload_ext["info"])):
        bond_id = info.get("bondId")
        if isinstance(bond_id, bool) or not isinstance(bond_id, int) or not 0 < bond_id < 2**32:
            fail(f"{name} extension info must carry a nonzero uint32 bondId")
    expect(required_ext["schema"], negotiation_schema, "PaymentRequired inline schema")
    expect(payload_ext["schema"], negotiation_schema, "PaymentPayload inline schema")
    expect(response_ext["schema"], settlement_schema, "SettlementResponse inline schema")
    check_local_refs(required_ext["schema"], "negotiation inline schema")
    check_local_refs(response_ext["schema"], "settlement inline schema")

    paid_server_info = dict(payload_ext["info"])
    paid_server_info.pop("idempotencyKey")
    paid_server_info.pop("requestHash")
    expect(paid_server_info, required_ext["info"], "x402 extension echo")
    expect(payload["accepted"], required["accepts"][0], "x402 accepted requirement")
    expect(payload["resource"], required["resource"], "x402 resource echo")

    auth = payload["payload"]["authorization"]
    expect(auth["from"], crypto["fixtures"]["buyer"], "x402 payer")
    expect(auth["to"], payload["accepted"]["payTo"], "x402 authorization recipient")
    expect(auth["to"], payload_ext["info"]["contract"], "x402 FairBind contract")
    expect(auth["nonce"], crypto["purchaseIdentifiers"]["nonce"], "x402 nonce")
    expect(payload["payload"]["signature"], crypto["paymentAuthorization"]["signature"], "x402 payment signature")
    expect(payload_ext["info"]["requestHash"], crypto["fixtures"]["requestHash"], "x402 request hash")

    profiles = load("profiles/local-evaluation-v1.json")["profiles"]
    profile = next(
        (item for item in profiles if item["profileId"] == required_ext["info"]["profileId"]),
        None,
    )
    if profile is None:
        fail("x402 profile is absent from the evaluation profile set")
    expect(required_ext["info"]["profileHash"], profile["parameterHash"], "x402 profile hash")
    expect(required_ext["info"]["predicateId"], profile["parameters"]["predicateId"], "x402 predicate id")
    expect(required_ext["info"]["canonId"], profile["parameters"]["canonId"], "x402 canon id")
    expect(required_ext["info"]["canonicalHeaders"], profile["parameters"]["canonicalHeaders"], "x402 canonical headers")
    expect(required_ext["info"]["maxRequestBytes"], profile["parameters"]["maxRequestBytes"], "x402 request bound")
    expect(required_ext["info"]["maxResponseBytes"], profile["parameters"]["maxResponseBytes"], "x402 response bound")
    quoted_epoch = (
        required_ext["info"]["quotedAtBlock"] - profile["parameters"]["epochOrigin"]
    ) // profile["parameters"]["epochBlocks"]
    expect(quoted_epoch, receipt["epoch"], "x402 quoted epoch")

    expect(response_ext["info"]["purchase"], crypto["purchaseIdentifiers"]["nonce"], "settlement purchase")
    expect(response_ext["info"]["keyId"], crypto["purchaseIdentifiers"]["keyId"], "settlement keyId")
    expect(receipt["signature"], crypto["receipt"]["signature"], "wire receipt signature")
    expect(receipt["responseHash"], crypto["receipt"]["message"]["responseHash"], "wire response hash")

    sources = {
        "PAYMENT-REQUIRED": required,
        "PAYMENT-SIGNATURE": payload,
        "PAYMENT-RESPONSE": response,
        "X-FairBind-Receipt": receipt,
    }
    for name, source in sources.items():
        encoded = base64.b64encode(json.dumps(source, ensure_ascii=False, separators=(",", ":")).encode()).decode()
        fixture = headers["encoded"][name]
        expect(encoded, fixture["value"], f"{name} base64")
        expect(len(encoded), fixture["length"], f"{name} length")

    raw_key = base64.urlsafe_b64decode(headers["requestHeaders"]["X-FairBind-Key"] + "==")
    expect("0x" + raw_key.hex(), crypto["fixtures"]["idempotencyKey"], "X-FairBind-Key")
    expect(headers["requestHeaders"]["X-FairBind-Payer"], crypto["fixtures"]["buyer"], "X-FairBind-Payer")


def update_x402_headers():
    path = ROOT / "test-vectors/x402-v2/headers.json"
    headers = load("test-vectors/x402-v2/headers.json")
    sources = {
        "PAYMENT-REQUIRED": "payment-required.json",
        "PAYMENT-SIGNATURE": "payment-payload.json",
        "PAYMENT-RESPONSE": "settlement-response.json",
        "X-FairBind-Receipt": "fairbind-receipt.json",
    }
    for name, filename in sources.items():
        source = load(f"test-vectors/x402-v2/{filename}")
        encoded = base64.b64encode(
            json.dumps(source, ensure_ascii=False, separators=(",", ":")).encode()
        ).decode()
        headers["encoded"][name] = {
            "source": filename,
            "length": len(encoded),
            "value": encoded,
        }
    path.write_text(json.dumps(headers, indent=2) + "\n", encoding="utf-8")


def check_required_files():
    files = [
        "docs/spec/fairbind-v1.md", "docs/spec/canonicalization-v1.md",
        "docs/spec/cryptography-v1.md", "docs/spec/merkle-v1.md",
        "docs/spec/contract-interface-v1.md", "docs/spec/lifecycle-v1.md",
        "docs/spec/predicate-interface-v1.md",
        "docs/spec/sortition-v1.md",
        "docs/spec/profile-v1.md", "docs/spec/governance-v1.md",
        "docs/spec/x402-v2-integration.md", "docs/spec/traceability.md",
        "docs/architecture.md", "docs/threat-model.md", "docs/implementation-plan.md",
    ]
    for relative in files:
        path = ROOT / relative
        if not path.is_file() or path.stat().st_size == 0:
            fail(f"missing required file: {relative}")

    forbidden = ("TODO", "TBD", "PARAMETER_HASH", "PREDICATE_ID", "CANON_ID")
    for relative in files:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for marker in forbidden:
            if marker in text:
                fail(f"unresolved marker {marker} in {relative}")


def main():
    check_required_files()
    check_keccak_padding_boundaries()
    crypto = load("test-vectors/cryptography-v1.json")
    check_domain_hashes(crypto)
    check_canonicalization(load("test-vectors/canonicalization-v1.json"), crypto)
    check_identifiers(crypto)
    check_typed_data(crypto)
    check_response_commitment(crypto)
    check_serve_bundle(crypto)
    check_selection(crypto)
    check_merkle(load("test-vectors/merkle-v1.json"))
    check_profiles(load("profiles/local-evaluation-v1.json"))
    check_predicates(load("test-vectors/predicate-v1.json"))
    check_sortition(load("test-vectors/sortition-v1.json"))
    check_x402(crypto)
    print("spec artifacts: ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--update-x402-headers"]:
        update_x402_headers()
        raise SystemExit(0)
    if sys.argv[1:]:
        fail("usage: check_spec.py [--update-x402-headers]")
    main()
