# Reference-source adapters

`refsource` implements `dataworker.ReferenceProvider` for the experimental
decimal-median comparison. It retrieves quotes from public price endpoints,
keeps every response as a raw replay object, and derives observations only
from those objects. Live capture and replay share the same verification,
parsing and normalization code.

## Sources

| Source ID | Endpoint | Fields used |
| --- | --- | --- |
| `coinbase-exchange:ticker:BTC-USD` | `GET https://api.exchange.coinbase.com/products/BTC-USD/ticker` | `price`, `bid`, `ask`, `time` |
| `kraken:ticker:XBTUSD` | `GET https://api.kraken.com/0/public/Ticker?pair=XBTUSD` | `result.XXBTZUSD.c[0]`, `b[0]`, `a[0]` |

Both adapters emit `price` (last trade), `bid` and `ask` in unit `USD`. Values
are normalized to plain decimal strings with no sign, exponent, leading integer
zeros or trailing fraction zeros (`64229.80000` becomes `64229.8`). Anything
else is rejected, not rounded. The observation time is the server `Date`
header, in Unix seconds. Coinbase additionally reports the last trade time;
a ticker whose last trade is more than five minutes older than `Date` is
rejected. Kraken's ticker has no trade time, so staleness there rests on `Date`
and the policy's `max_skew`.

Only operator configuration (`Registry`) maps a source ID to an endpoint. A
policy or source set selects registry entries by ID; it cannot supply a URL.
An object whose `source_id` or URL does not match the registry entry is
rejected.

### Why these two are independent

Independence here means that the two sources derive their values from
disjoint upstream data and can fail or be manipulated separately.

- Each endpoint reports the state of its operator's own matching engine: the
  last trade executed on that venue and the top of that venue's order book.
  Neither ticker is computed from the other venue's trades or quotes. They
  are operated by different companies under different regulators, with
  separate order books, customers and market-data infrastructure.
- Their values agree because arbitrage links the venues, not because one
  copies the other. A wash trade or a spoofed order on one venue moves only
  that venue's ticker. The comparison's `reference_spread` bounds the
  disagreement allowed between them, and a larger gap is `INCONCLUSIVE`.
- An aggregator (for example CoinGecko or CoinMarketCap) was not chosen as the
  second source, because such indices include Coinbase and Kraken among their
  inputs and are therefore not independent of an exchange source.

Limits of this argument:

- Both hostnames are commonly served through the same CDN (Cloudflare at the
  time of writing). A compromise of that CDN's TLS termination would affect
  both sources. The recorded certificate chain, `Server` and `CF-RAY` headers
  show the serving infrastructure of each capture, so this can be checked per
  run but is not excluded.
- Two venues do not make a representative market price. They make two
  independently produced observations of the same pair.
- If the seller under test resells one of these venues' data, that source is
  not independent of the seller for that experiment.

## Authenticity

Neither endpoint signs its responses. Authenticity rests on TLS server
authentication at capture time plus the recorded raw replay object, not on a
signature. TLS does not sign application data, so a raw object is not
transferable proof: anyone holding it could have edited it and recomputed the
hash. A replay is as trustworthy as the operator that captured and stored it.

What the object does let a later reader check:

- the exact request bytes and the exact response bytes (status line, headers,
  transfer framing and body), with their SHA-256;
- that the recorded certificate chain was valid for the URL host at the capture
  time under a given root set, and that its root equals the root that verified
  the live handshake;
- the TLS version, cipher suite, ALPN, session resumption, stapled OCSP
  response and signed certificate timestamps observed by the client;
- that the server `Date` header falls inside the local capture window.

A TLS-intercepting proxy fails chain validation unless its CA was added to the
roots, and its CA then appears in the recorded chain. Signed-response price
feeds (for example oracle networks whose reports carry publisher or guardian
signatures) would give transferable proof, but need a separate signature
verifier and a separate check that their publisher set does not include these
venues; they are not implemented here.

## Raw replay object

Format `fairbind/refsource-raw/v1`, one JSON object per file. Byte fields are
standard base64.

| Member | Content |
| --- | --- |
| `source_id`, `method`, `url` | registry source, `GET`, the full `https` URL |
| `request_raw` | exact HTTP/1.1 request bytes sent |
| `started_at_unix_ms`, `finished_at_unix_ms` | local clock before dialing and after the last byte |
| `response_raw`, `response_sha256` | exact response bytes read from the TLS stream and their SHA-256 |
| `response_head` | the status line and header block as text; must equal the prefix of `response_raw` |
| `tls` | version, cipher suite, server name, ALPN, resumption, DER peer chain, OCSP, SCTs, remote address, SHA-256 of the verified root |
| `capture` | tool, `synthetic` flag, proxy used, note |

The object ID is the SHA-256 of the compact Go JSON encoding of the decoded
object. `DirSink` stores objects as `<source>-<id prefix>.json` and never
overwrites an existing file. A sink receives each object before it is verified
or parsed, so error responses are kept as well.

The capturer speaks HTTP/1.1 directly over `crypto/tls` with
`Accept-Encoding: identity` and `Connection: close`, so `response_raw` is what
the server sent and not a re-serialization. Compressed responses are rejected.

When no object can be produced, `Capture` returns a `*CaptureError` whose
`Stage` says how far the exchange got: `connect` (name resolution, TCP
connection, proxy CONNECT or TLS handshake; no HTTP response from the origin),
`exchange` (after the handshake, before a complete response head) or
`response` (after the head was read). A caller can use it to tell a local
network outage from a server that answered badly.

## Modes

- `Live{Capturer}` fetches each source now. It ignores the reference time; the
  comparison drops observations outside `max_skew`, so a live capture must run
  within the skew of the committed reference time.
- `Replay` serves saved objects. For each source it picks the object whose
  `Date` is nearest the reference time, ties broken by object ID, so results
  depend only on the stored files.

By default `Provider.Retrieve` returns an error if any source fails, which the
worker reports as `INCONCLUSIVE` (`references_unavailable`). With
`AllowPartial` it returns the sources that succeeded and leaves the quorum to
the comparison.

For the predicate pipeline, `Provider.Collect` implements
`dataworker.ReplaySource`: it returns each obtained raw object as its compact
JSON encoding (whose SHA-256 is the object ID) and lists sources that could not
be obtained, without parsing. `Decoder` implements `dataworker.ReplayDecoder`:
it checks the object ID, decodes strictly, checks the registered endpoint,
verifies and parses. The pipeline and a second verifier use the same decoder.

## Fixtures

`../testdata/refsource/` holds synthetic raw objects, marked `synthetic-` in
their file names and `"synthetic": true` inside. They were built by
`gen_synthetic.py` to the documented JSON shapes of both endpoints; they carry
no TLS chain and no real market data. `Verify` rejects synthetic objects unless
`VerifyOptions.AllowSynthetic` is set, and rejects a synthetic-tagged object
that contains a chain. `replay/` holds one object per source at Unix time
1790000000 plus an older Coinbase object; `malformed/` holds error responses
(HTTP 503, Kraken unknown pair, duplicate JSON member, exponent notation,
stale last trade).

The live capture path is tested against a local TLS server with a test root.

## Live capture

Run from the repository root on a host with direct HTTPS access:

```sh
go run ./runtime/dataworker/refsource/cmd/refcapture -out runtime/dataworker/testdata/refsource/live
```

The command captures both sources, stores the raw objects under `-out`, then
verifies and parses them and prints one record per source. It exits nonzero if
any source fails. `-sources` limits the source IDs, `-roots FILE.pem` replaces
the system roots, and an `http://` `HTTPS_PROXY` is used through CONNECT (the
proxy is recorded in `capture.proxy`). To check saved objects again:

```sh
go run ./runtime/dataworker/refsource/cmd/refcapture -replay DIR -reference-time UNIX
```

Replay verifies each recorded chain against the current system roots at the
capture time; pass `-roots` to pin the root set used at capture.

## Not covered

- No live capture has been run from this package yet; all committed fixtures
  are synthetic.
- The source set manifest is still a list of IDs. Endpoint, field mapping and
  authenticity rules are fixed by the registry, not committed in
  `sourceSetHash`.
- `Worker` tests use in-memory references; the pipeline tests replay these
  fixtures. Both need the pinned `cast` build for receipt signatures.
