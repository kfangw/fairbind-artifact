# C1 data-API collector

Collects the data-API sample of the C1 predicate study: seller-role captures
from Bitstamp and Gemini, wrong answers derived from them, and judgments of
every response by three verifier instances that each capture Coinbase and
Kraken on their own schedule and run `dataworker.Pipeline`. The rules (grid,
seeded lists, wrong-answer types, 429 rule, truth lookups) are fixed in
`experiments/calibration/c1-config.json` (`data_api` and `collection`).

| File | Role |
| --- | --- |
| `collector.py` | scheduler, state, sessions, wrong-answer assignment, CLI |
| `verify.py` | data-directory checks (`collector.py verify`) |
| `cmd/c1tool` | Go tool: captures, signed bundles, verifier instance, re-derivation |
| `sources.go`, `capture.go` | seller-role adapters (`last`), Bitfinex trade-history adapter |
| `instance.go`, `bundle.go` | instance schedule and judgment, test-seller bundles |

## Run-time requirements

- Python 3.8 or later, standard library only (Linux or macOS).
- `c1tool`, built once: `go build -o bin/c1tool ./experiments/c1collect/cmd/c1tool`
  (cross-compile with `GOOS=darwin GOARCH=arm64` for a Mac). It has no
  run-time dependencies.
- `cast` 1.7.1 at commit `4072e48` (Foundry). The pipeline's input gate
  verifies the seller signature with this exact build, and bundles are signed
  with it using the public test key 1.
- HTTPS access to the five hosts (Bitstamp, Gemini, Coinbase Exchange,
  Kraken, Bitfinex). An `http://` `HTTPS_PROXY` is used through CONNECT.
  Pass `--roots FILE.pem` at `init` if a TLS-terminating proxy is in the path.
  Bitfinex serves at most 15 requests per minute on `trades/.../hist` and
  returns trades at least a year back, so a late lookup reads the same data.

Go, Foundry's other tools and the repository's Solidity build are not needed
at run time. The working tree must be clean at `init`; the collector refuses
to run if `collector.py` or `c1tool` changed after `init`.

## Start

```sh
python3 experiments/c1collect/collector.py init --data DATA --c1tool bin/c1tool --cast /path/to/cast
python3 experiments/c1collect/collector.py run  --data DATA
```

`init` fixes the configuration, the seeded role and type lists, the git
revision and the hashes of both tools in `DATA/collection.json`. `run` works in
the foreground until a stop condition: both seller sources have 1,500 honest
captures and all 1,110 wrong-answer types are assigned, 2,400 complete cells,
or three consecutive HTTP 429 responses from one source.

## Running on a Mac

The main collection runs on the researcher's Mac under launchd. Build the tool
for the Mac from the repository (`CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go
build -o bin/c1tool ./experiments/c1collect/cmd/c1tool`) and use the Foundry
v1.7.1 `cast` for `darwin_arm64`. A LaunchAgent that keeps `run` alive:

```xml
<plist version="1.0"><dict>
  <key>Label</key><string>org.fairbind.c1collect</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>REPO/experiments/c1collect/collector.py</string>
    <string>run</string><string>--data</string><string>DATA</string></array>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>DATA/log/run.out</string>
  <key>StandardErrorPath</key><string>DATA/log/run.out</string>
</dict></plist>
```

`run` exits 0 when another process holds the lock or the collection is stopped
or on hold, so launchd restarting it every 30 s does no harm.

## Resume and watchdog

`run` is idempotent. It takes an exclusive lock on `DATA/lock`; a second
`run` while one holds the lock prints `collector already running` and exits 0.
On start it discards a cell that was open when the previous process ended,
closes that session, and continues with the first grid time more than 10 s
ahead. Grid times passed while it was not running stay unopened.

An external watchdog only has to call `run` repeatedly:

- launchd (macOS): a LaunchAgent with `ProgramArguments` set to the `run`
  command, `KeepAlive` true and `ThrottleInterval` 30. launchd restarts it
  after a crash and after wake-up.
- cron or a shell loop: `* * * * * python3 .../collector.py run --data DATA >> DATA/log/run.out 2>&1`.
- systemd: a user service with `Restart=always` and `RestartSec=30`.

A machine suspend does not kill the process. The collector compares a clock
that runs during suspend with one that stops (Linux `CLOCK_BOOTTIME` and
`CLOCK_MONOTONIC`, macOS `CLOCK_MONOTONIC` and `CLOCK_UPTIME_RAW`). A gap of
more than 1 s inside a cell discards the cell; a gap while waiting ends the
session. Both end the session with reason `machine_sleep`.

## Stop

```sh
python3 experiments/c1collect/collector.py stop    --data DATA --reason "machine needed for other work"
python3 experiments/c1collect/collector.py release --data DATA --reason "..."
```

`stop` asks the running collector to end its session before the next cell
(reason `user_stop`, the text goes into the session record) and puts the
collection on hold: `run` does nothing until `release`. After the 429 rule
stopped the collection, `release` resets the consecutive counts; write the
reason into the change log first. SIGTERM or SIGINT discard the open cell and
end the session with reason `other`.

## Status

```sh
python3 experiments/c1collect/collector.py status --data DATA   # exit 0 running, 1 not running
```

It prints complete and discarded cells, per-source availability (HTTP 200 per
attempt), remaining honest captures per source and remaining wrong-answer
captures. It never prints a judgment outcome, and neither does the log. The
collector writes each judgment record once and does not read it again.

## Data directory

```
DATA/collection.json       configuration, seeded-list hash, revision, tool hashes (fixed at init)
DATA/plan/lists.json       seeded role lists (per seller) and type list
DATA/state.json            progress: list positions, deferred types, adaptive state,
                           429 counts, sessions, counters (atomic replace)
DATA/cells/YYYY-MM-DD/T/   one complete cell per grid time T (Unix seconds), immutable
    manifest.json          file list with SHA-256 and sizes, state after the cell
    controller.json        seller captures, roles, types, generated responses, seeded values
    seller/, generator/    raw objects (fairbind/refsource-raw/v1)
    instance-N/            the instance's reference raw objects and judgment.json
    requests.log           one line per HTTP request of the cell
DATA/discarded/T.json      discarded cell: reason, note, HTTP requests
DATA/discarded/T.work/     raw objects of the discarded cell (no judgment record kept)
DATA/truth/                truth-lookup queue and results (controller side)
DATA/work/T/               the open cell; renamed into cells/ when complete
DATA/log/collector.log     progress log (no outcomes)
```

A cell is complete when its seller and reference raw objects, the assignment,
the three judgment records and the adaptive state are on disk: the collector
writes them into `work/T/` (each file fsynced), writes the manifest, renames
the directory into `cells/` and then replaces `state.json`. If the process
dies between the rename and the state write, the next start adopts the state
stored in the newest manifest, so a grid time is never completed twice.

Measured in the container smoke run: about 214 KB per complete cell with two
honest responses (three judgment records of about 48 KB each hold the full
evidence, including the reference raw objects). 2,400 cells need about
0.5 GB. Cells with a D-adaptive response add the generator's two raw objects.

## Verify

```sh
python3 experiments/c1collect/collector.py verify --data DATA
python3 experiments/c1collect/collector.py verify --data DATA --deep   # after the collection
```

`verify` checks grid alignment, that no grid time is both complete and
discarded, every manifest hash and size, the controller records, a replay of
the role and type list consumption against the seeded lists and the state,
session counts, and decodes and verifies every raw object with `c1tool
objects`. It hashes judgment records but does not parse them. `--deep` also
re-derives every judgment from its evidence (`c1tool rederive`) and prints
counts only; it is refused while the collection is open unless
`--allow-open` is given.

## Archive

Complete cells never change after the rename, so they can be copied
incrementally:

```sh
python3 experiments/c1collect/collector.py archive --data DATA --to DEST
```

copies each cell not yet present in `DEST/cells` into a temporary directory,
checks every file against its manifest and renames it into place, then
refreshes `collection.json`, `state.json`, `plan/`, `discarded/`, `truth/`
and `log/`. The same holds for `rsync -a --ignore-existing DATA/cells/ DEST/cells/`,
because `work/` is outside `cells/`.

## Decisions taken in the implementation

These are not fixed by the collection plan and are recorded in the
`collection` section of the configuration:

- Instance schedule: slots at -9, -4 and +1 s from the grid time, assigned to
  instances by a seeded permutation, plus a seeded jitter of 0 to 3 s; each
  instance captures its two references one after the other in its seeded
  order. The instance processes start 10 s before the grid time.
- One generator capture of the two references per cell, shared by both
  D-adaptive responses when both sellers draw one (keeps the reference
  request rate at four per five minutes). If neither reference answers, the
  D-adaptive type is put back at the head of the deferred queue and the
  capture takes the next type.
- The 429 count is per source over every HTTP response in time order,
  including the three instances' requests in one cell; a 429 skips that
  source in the next opened cell. A connection-stage failure (DNS, TCP,
  proxy CONNECT or TLS handshake) is "no HTTP response" for the network rule.
- A cell whose tool call fails (not a network failure) is discarded with
  reason `other` and ends the session.
- The 429 count is per HTTP response, so three instances receiving 429 from
  the same reference in one cell stop the collection at once. The plan says
  "three consecutive from the same source" without fixing the unit; the
  response is the stricter reading.
- The first truth lookup of a cell waits until `reference_time + max_skew +
  settle_seconds` (30 s), so the ±10 s window has closed and Bitfinex has
  published it. The plan fixes only "after the cell's judgments are stored";
  a lookup before the window closes could miss the nearest trade.
- Truth lookups are at least `min_interval_seconds` (5 s) apart, so a backlog
  after an interruption stays under Bitfinex's 15 requests per minute and
  cannot trigger the 429 rule by itself.
- Discarded cells leave the lists, the successful-capture history (D-stale),
  the adaptive state and the availability counts unchanged; their HTTP
  requests and any 429 responses are counted.
