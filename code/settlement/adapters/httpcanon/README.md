# HTTP canonicalization adapter

Implements canonicalization-v1 from original target and body bytes, without URL
library decoding or JSON body rewriting. Operator-supplied selected header names
must be sorted, unique, lowercase tokens and explicitly declared comma-joinable.
Payment, framing, hop-by-hop and Connection-nominated headers are rejected even
when allowlisted. Content-Encoding must be selected when present. Both raw input
resource limits and normalized five-field contract limits are checked.

The caller must preserve raw target and pre-content-decoding bytes; the package
cannot detect an intermediary that already destroyed them. `CheckRoute` compares
the actual server route with the normalized path before execution. Tests cover all
three positive normative vectors, negative cases, dot segments, content boundary,
body ownership, route mismatch and normalization expansion at the size limit.
