# FairBind HTTP Canonicalization Version 1

Status: Release candidate for implementation

Canonicalization identifier:

```text
canonId = keccak256(UTF8("fairbind/http-canon/v1"))
```

This rule converts one HTTP request into six fixed-length hashes and then uses
Solidity ABI encoding. It does not parse or rewrite JSON, form data, or another
application body format.

## 1. Inputs

The resource server and buyer use the same request before either side adds x402
or FairBind payment headers. The inputs are:

- the HTTP method;
- the path from the request target;
- the raw query from the request target, without the leading question mark;
- the request body after transfer-coding removal and before content-coding
  removal;
- the ordered list of canonical header names advertised by the service profile;
- all field values for those names in their received order.

`PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE`, `PAYMENT-RESPONSE`,
`X-FairBind-Key`, `X-FairBind-Payer`, `X-FairBind-Receipt`, hop-by-hop headers,
and transport framing never enter the canonical request. A profile MUST NOT list
one of these names.

The implementation MUST reject an input when it cannot recover the request
target before URL-library decoding or the body bytes at the specified boundary.

## 2. Method

The method consists of printable ASCII bytes from `0x21` through `0x7e`. The
implementation converts `a` through `z` to uppercase and leaves other bytes
unchanged. An empty method or a byte outside the allowed interval is invalid.

## 3. Percent normalization

Path and query components use the following percent-normalization function.

1. Reject a percent sign that is not followed by two hexadecimal digits.
2. Decode a percent triplet only when its decoded byte is an RFC 3986 unreserved
   byte: `A-Z`, `a-z`, `0-9`, hyphen, period, underscore, or tilde.
3. Keep every other encoded byte in percent form and uppercase its two
   hexadecimal digits.
4. Reject a raw byte outside printable ASCII. A caller must first encode a
   non-ASCII UTF-8 byte as a percent triplet.

The plus sign is a literal plus sign. It never represents a space.

## 4. Path

An empty path becomes `/`. A nonempty path MUST begin with `/`. The
implementation applies percent normalization and then removes dot segments by
RFC 3986 Section 5.2.4. It preserves consecutive slashes and a trailing slash.
It does not perform Unicode normalization, case folding, or file-system path
resolution.

The server MUST route the request using the same normalized path that enters the
hash. If its framework routes a decoded or otherwise rewritten path, the adapter
MUST compare that route with the FairBind normalized path and reject a mismatch.

## 5. Query

An empty query produces an empty byte string. Otherwise, the implementation:

1. splits the raw query at every ampersand, including empty fields;
2. splits each field at its first equals sign;
3. treats a missing equals sign as an empty value;
4. percent-normalizes the name and value separately;
5. sorts fields by normalized name bytes and then by normalized value bytes;
6. retains duplicate pairs;
7. serializes each pair as `name=value` and joins pairs with `&`.

Sorting compares unsigned bytes. It is stable for identical pairs, although
their order does not affect the serialized result. A semicolon is data and not a
separator. An empty query field becomes `=`.

## 6. Headers

The profile stores a nonempty or empty array of lowercase header names. Names
MUST be unique, sorted by unsigned ASCII bytes, and satisfy the HTTP field-name
token grammar. The request MUST contain every listed header at least once.

For each value, the implementation rejects a carriage return, line feed, NUL,
or byte outside horizontal tab and printable ASCII. It replaces each maximal run
of spaces and horizontal tabs with one space and removes a leading or trailing
space. Repeated values retain their received order and join with one comma and no
additional space.

The header block contains one line per advertised name:

```text
lowercase-name:normalized-value\n
```

`set-cookie` and any header whose field definition does not permit comma joining
MUST NOT appear in a profile.

## 7. Body

The body is the exact entity body after HTTP transfer coding, such as chunked
framing, has been removed. Content coding, such as gzip, remains. An absent body
and a zero-length body both produce the empty byte string.

A profile that permits content coding MUST include `content-encoding` in its
canonical header list. A server MUST reject transparent content decoding by an
intermediary when it cannot reproduce the bytes that the buyer hashed.

## 8. Hash construction

The implementation computes:

```text
domainHash  = keccak256(UTF8("fairbind/http-canon/v1"))
methodHash  = keccak256(methodBytes)
pathHash    = keccak256(normalizedPathBytes)
queryHash   = keccak256(normalizedQueryBytes)
headersHash = keccak256(canonicalHeaderBlockBytes)
bodyHash    = keccak256(bodyBytes)

requestHash = keccak256(abi.encode(
  bytes32(domainHash),
  bytes32(methodHash),
  bytes32(pathHash),
  bytes32(queryHash),
  bytes32(headersHash),
  bytes32(bodyHash)
))
```

`abi.encode` is the Solidity ABI encoding of six static `bytes32` values. The
encoded input is exactly 192 bytes. Implementations MUST NOT hash a delimited
text rendering or use `abi.encodePacked` for the final construction.

## 9. Failure behavior

The buyer rejects an invalid request locally before signing. The resource server
returns `400` with `fairbind_canonicalization_failed` when the unpaid request is
invalid. It returns `402` with `fairbind_request_hash_mismatch` when a paid retry
is valid but produces a different `requestHash` from the echoed extension.

The positive and negative examples in
[`../../test-vectors/canonicalization-v1.json`](../../test-vectors/canonicalization-v1.json)
are normative.
