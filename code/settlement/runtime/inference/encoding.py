"""Hashing and canonical encodings shared by the open-weights binding.

Keccak-256 matches `protocol.Keccak256`. `canonical` produces RFC 8785 (JCS)
bytes for the narrow value set used here: objects with printable-ASCII keys,
printable-ASCII strings, lists, booleans and safe nonnegative integers. Anything
else is rejected rather than normalized. It is not a general JCS library.
"""
import json

MASK64 = (1 << 64) - 1
ROUND_CONSTANTS = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]
ROTATION = [
    [0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56], [27, 20, 39, 8, 14],
]

def _rol(value, shift):
    return ((value << shift) | (value >> (64 - shift))) & MASK64 if shift else value

def _permute(state):
    for constant in ROUND_CONSTANTS:
        c = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        for i in range(25):
            state[i] ^= d[i % 5]
        moved = [0] * 25
        for y in range(5):
            for x in range(5):
                moved[y + 5 * ((2 * x + 3 * y) % 5)] = _rol(state[x + 5 * y], ROTATION[x][y])
        for y in range(5):
            row = moved[5 * y:5 * y + 5]
            for x in range(5):
                state[x + 5 * y] = row[x] ^ ((~row[(x + 1) % 5]) & row[(x + 2) % 5])
        state[0] ^= constant

def keccak256(data: bytes) -> bytes:
    rate = 136
    padded = bytearray(data)
    padded.append(0x01)
    padded.extend(b'\x00' * ((-len(padded)) % rate))
    padded[-1] |= 0x80
    state = [0] * 25
    for offset in range(0, len(padded), rate):
        for lane in range(rate // 8):
            start = offset + lane * 8
            state[lane] ^= int.from_bytes(padded[start:start + 8], 'little')
        _permute(state)
    return b''.join(state[lane].to_bytes(8, 'little') for lane in range(4))

def hex32(data: bytes) -> str:
    if len(data) != 32:
        raise ValueError('expected 32 bytes')
    return '0x' + data.hex()

def parse_hex32(value) -> bytes:
    if not isinstance(value, str) or len(value) != 66 or not value.startswith('0x'):
        raise ValueError('invalid bytes32')
    return bytes.fromhex(value[2:])

def _check(value):
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int):
        if not 0 <= value < 2**53:
            raise ValueError('unsupported integer')
    elif isinstance(value, str):
        if any(not 32 <= ord(ch) <= 126 for ch in value):
            raise ValueError('unsupported string')
    elif isinstance(value, list):
        for item in value:
            _check(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError('unsupported key')
            _check(key)
            _check(item)
    else:
        raise ValueError('unsupported value type')

def canonical(value) -> bytes:
    _check(value)
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')

def _pairs(rows):
    out = {}
    for key, item in rows:
        if key in out:
            raise ValueError('duplicate JSON member')
        out[key] = item
    return out

def parse_canonical(raw: bytes):
    """Parse bytes and require that they are exactly their canonical encoding."""
    value = json.loads(raw, object_pairs_hook=_pairs, parse_float=lambda _: (_ for _ in ()).throw(ValueError('float')),
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
    if canonical(value) != raw:
        raise ValueError('noncanonical encoding')
    return value

def object_hash(value) -> bytes:
    """keccak256(UTF8(JCS(value)))."""
    return keccak256(canonical(value))

OPEN_WEIGHTS_DOMAIN = keccak256(b'fairbind/open-weights-commitment/v1')

def open_weights_commitment(toploc_commitment: bytes, model_hash: bytes, config_hash: bytes) -> bytes:
    """predicateCommitment for class 2: keccak256(abi.encode(domain, toploc, model, config))."""
    for word in (toploc_commitment, model_hash, config_hash):
        if len(word) != 32:
            raise ValueError('expected bytes32')
    return keccak256(OPEN_WEIGHTS_DOMAIN + toploc_commitment + model_hash + config_hash)
