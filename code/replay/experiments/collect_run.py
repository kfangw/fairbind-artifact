"""Collect the observations of one finished hold-period harness run.

    python3 experiments/collect_run.py --rpc-url URL --run-dir RUN --ground-truth GT.json --out OBS.jsonl
        [--ledger ledger.json] [--document OBS.json]

The collector joins the chain with the controller's ground truth after the run, while the chain is
still readable. It writes two files:

- `--out`: observation rows `{"metric", "value", "observation_id"}`, one JSON object per line, in
  metric order (the rows the runner reads into the result envelope; experiments/metrics.md);
- `--document` (default: `--out` with the suffix `.json`): one JSON document (format
  `fairbind-run-observations/v1`) with the inputs it read, the per-sale rows, the effective-detection
  cases, the episodes, the verifier columns, the fault_observed items and every metric value.

Inputs, relative to the run directory (the runner's layout):

- ledger (required): `--ledger`, else `ledger.json`, else written there by `fairbind-ledger-dump`
  (`$FAIRBIND_LEDGER_DUMP`, else `go run ./services/casepath/cmd/fairbind-ledger-dump`) from
  `--rpc-url` and `proc/deploy/deployment.json`; format `fairbind-ledger-dump/v1`;
- ground truth (required): `--ground-truth`, with `bad_sales_rule` (`all_cheater_episode_sales`,
  `first_m` with `bad_sales_m`, or `none`) and the run parameters;
- `shared/profile.json` (required): the profile the controller derived (its deadline configuration
  gives T_case);
- optional: `proc/deploy/deployment.json` (seller id, setup block, assignable verifiers),
  `proc/<process>/directive.json`, keeper `proc/keeper/events.jsonl` (`call_sent` and `case_delay`
  rows), seller `meta/policy.json` and `meta/attack.json`, verifier `injection/<key>.json` records,
  `workload/summary.json` and `pool/replacements.jsonl`.

Output is deterministic: the same inputs give byte-identical files (sorted keys, no clock reads, no
absolute paths).
"""
import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
from controller import profile as prof  # noqa: E402

FORMAT = 'fairbind-run-observations/v1'
LEDGER_FORMAT = 'fairbind-ledger-dump/v1'
BAD_SALES_RULES = ('all_cheater_episode_sales', 'first_m', 'none')

# Contract enums (docs/spec/contract-interface-v1.md section 2).
VERDICTS = {0: None, 1: 'PASS', 2: 'FAIL', 3: 'INCONCLUSIVE'}
STAGES = {1: 'initial', 2: 'party', 3: 'auto', 4: 'tiebreak'}
TRIGGER_SAMPLE = 1
REQUESTER_KEEPER = 3
ACTOR_SELLER, ACTOR_VERIFIER = 1, 2
SLASH_VERIFIER_LATE = 2
REACHED = ('RELEASED', 'RELEASABLE')
LOST = ('REFUNDED', 'FORFEITED', 'FROZEN_CLAIMABLE', 'REFUNDABLE')
TERMINAL_CASE_STATES = ('FINAL', 'UNSERVED', 'INCONCLUSIVE', 'DELIVERED')

# Verifier judgment-injection draw (services/verifier/injected.go).
INJECTION_DOMAIN = b'fairbind/seed/verifier'
PURPOSES = ('honesty', 'outcome')


class InputError(Exception):
    """A required input is missing or malformed."""


# ---------------------------------------------------------------------------------------------
# Small helpers


def _int(v):
    if v is None:
        return None
    if isinstance(v, bool):
        raise InputError(f'expected an integer, got {v!r}')
    return int(v)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise InputError(f'{path}: {exc}') from exc


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def injection_draw(seed, nonce, stage, attempt, purpose):
    """u = (uint64_be(SHA-256(domain || uint64_be(seed) || nonce[32] || stage || attempt || purpose)[0:8])
    >> 11) / 2^53."""
    raw = bytes.fromhex(nonce[2:] if nonce.startswith('0x') else nonce)
    if len(raw) != 32:
        raise ValueError(f'nonce {nonce} is not 32 bytes')
    digest = hashlib.sha256(INJECTION_DOMAIN + struct.pack('>Q', int(seed)) + raw
                            + bytes([int(stage), int(attempt)]) + purpose.encode('ascii')).digest()
    return (int.from_bytes(digest[:8], 'big') >> 11) / 2 ** 53


def injected_verdict(params, predicate_verdict, u1, u2):
    """The verdict the injection rule gives (services/verifier/injected.go Decide)."""
    alpha, c = params['alpha'], params['c']
    if params.get('honestErrorOff'):
        alpha, c = 0, 0
    honest = u1 < params['h']
    if honest and predicate_verdict == 'FAIL':
        return honest, 'beta', ('PASS' if u2 < params['beta'] else 'FAIL')
    if honest:
        return honest, 'alpha', ('FAIL' if u2 < alpha else 'PASS')
    if predicate_verdict == 'FAIL':
        return honest, 'none', 'PASS'
    return honest, 'c', ('FAIL' if u2 < c else 'PASS')


# ---------------------------------------------------------------------------------------------
# Inputs


def dump_ledger(rpc_url, run_dir, out):
    deployment = run_dir / 'proc' / 'deploy' / 'deployment.json'
    if not deployment.exists():
        raise InputError(f'no ledger and no {deployment} to dump one from')
    binary = os.environ.get('FAIRBIND_LEDGER_DUMP')
    cmd = [binary] if binary else ['go', '-C', str(ROOT), 'run', './services/casepath/cmd/fairbind-ledger-dump']
    cmd += ['-rpc', rpc_url, '-deployment', str(deployment), '-out', str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise InputError(f'fairbind-ledger-dump exited with {result.returncode}: {result.stderr.strip()[-2000:]}')


def _optional_json(path):
    return _read_json(path) if path.exists() else None


def _jsonl(path):
    rows = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as exc:
            raise InputError(f'{path}:{number}: {exc}') from exc
    return rows


def _unique(paths, what):
    paths = sorted(paths)
    if len(paths) > 1:
        raise InputError(f'several {what}: {[str(p) for p in paths]}')
    return paths[0] if paths else None


def load_inputs(run_dir, ground_truth, ledger=None, rpc_url=None, injection_dirs=None):
    """Read every input of one run. Returns a dict; `sources` records what was present."""
    run_dir = Path(run_dir)
    sources = {}

    def note(name, path, required=False):
        present = path is not None and Path(path).exists()
        if required and not present:
            raise InputError(f'{name}: {path} not found')
        sources[name] = dict(present=present, sha256=_sha256(path) if present else None,
                             path=str(Path(path).relative_to(run_dir)) if present and _inside(path, run_dir)
                             else (Path(path).name if present else None))
        return present

    ledger_path = Path(ledger) if ledger else run_dir / 'ledger.json'
    if not ledger_path.exists():
        if ledger:
            raise InputError(f'ledger: {ledger_path} not found')
        if not rpc_url:
            raise InputError('no ledger.json in the run directory and no --rpc-url to dump one')
        dump_ledger(rpc_url, run_dir, ledger_path)
    note('ledger', ledger_path, required=True)
    led = _read_json(ledger_path)
    if led.get('format') != LEDGER_FORMAT:
        raise InputError(f'ledger format {led.get("format")!r}, expected {LEDGER_FORMAT}')

    note('ground_truth', Path(ground_truth), required=True)
    gt = _read_json(ground_truth)
    rule = gt.get('bad_sales_rule')
    if rule not in BAD_SALES_RULES:
        raise InputError(f'ground truth bad_sales_rule {rule!r} is not one of {BAD_SALES_RULES}')
    if rule == 'first_m' and not (isinstance(gt.get('bad_sales_m'), int) and gt['bad_sales_m'] >= 1):
        raise InputError('ground truth first_m without a positive bad_sales_m')

    profile_path = run_dir / 'shared' / 'profile.json'
    note('profile', profile_path, required=True)
    profile_doc = _read_json(profile_path)

    deployment_path = run_dir / 'proc' / 'deploy' / 'deployment.json'
    note('deployment', deployment_path)
    directives = {}
    for name in ('verifier', 'seller', 'keeper', 'buyer'):
        path = run_dir / 'proc' / name / 'directive.json'
        if note(f'directive_{name}', path):
            directives[name] = _read_json(path)

    keeper_path = run_dir / 'proc' / 'keeper' / 'events.jsonl'
    keeper_rows = _jsonl(keeper_path) if note('keeper_events', keeper_path) else None

    policy_path = _unique([p for p in run_dir.rglob('meta/policy.json')], 'seller policy logs')
    note('seller_policy', policy_path)
    attack_path = _unique([p for p in run_dir.rglob('meta/attack.json')], 'seller attack records')
    note('seller_attack', attack_path)

    dirs = [Path(d) for d in injection_dirs] if injection_dirs else sorted(
        p for p in run_dir.rglob('injection') if p.is_dir())
    records = []
    for d in dirs:
        for path in sorted(d.glob('*.json')):
            if path.name.startswith('.'):
                continue
            rec = _read_json(path)
            rec['_file'] = path.name
            records.append(rec)
    sources['injection_records'] = dict(present=bool(records), count=len(records),
                                        sha256=hashlib.sha256(json.dumps(
                                            [r for r in records], sort_keys=True).encode()).hexdigest()
                                        if records else None, path=None)

    summary_path = run_dir / 'workload' / 'summary.json'
    note('workload_summary', summary_path)
    # The verifier pool writes pool/ next to its progress file ({run_dir}/proc/verifier/pool).
    pool_path = next((p for p in (run_dir / 'proc' / 'verifier' / 'pool' / 'replacements.jsonl',
                                  run_dir / 'pool' / 'replacements.jsonl') if p.exists()),
                     run_dir / 'proc' / 'verifier' / 'pool' / 'replacements.jsonl')
    note('pool_replacements', pool_path)
    # The facilitator's settlement attempts (one file per purchase nonce): status `rejected` with the
    # revert name when the contract refused the settlement (simulated or mined).
    attempts_dir = run_dir / 'proc' / 'deploy' / 'services' / 'facilitator' / 'data' / 'attempts'
    attempts = [_read_json(p) for p in sorted(attempts_dir.glob('*.json'))] if attempts_dir.is_dir() else None
    sources['facilitator_attempts'] = dict(present=attempts is not None, count=len(attempts or []),
                                           sha256=hashlib.sha256(json.dumps(
                                               [(a.get('nonce'), a.get('status'), a.get('revert')) for a in attempts],
                                               sort_keys=True).encode()).hexdigest() if attempts is not None else None,
                                           path=None)

    return dict(
        ledger=led, ground_truth=gt, profile_doc=profile_doc,
        deployment=_optional_json(deployment_path), directives=directives, keeper_rows=keeper_rows,
        policy=_read_json(policy_path) if policy_path else None,
        attack=_read_json(attack_path) if attack_path else None,
        injection_records=records if dirs else None,
        workload_summary=_optional_json(summary_path),
        pool_replacements=_jsonl(pool_path) if pool_path.exists() else None,
        facilitator_attempts=attempts, sources=sources)


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------------------------
# Ledger indexing


class Ledger:
    def __init__(self, doc, seller_id):
        self.doc = doc
        self.events = sorted(doc['events'], key=lambda e: (e['block'], e['logIndex']))
        self.view_block = doc['viewBlock']
        self.tx_block = {}
        for e in self.events:
            self.tx_block.setdefault(e['tx'], e['block'])
        self.by_nonce = {}
        for e in self.events:
            n = e['args'].get('nonce') or e['args'].get('triggerNonce')
            if n is not None:
                self.by_nonce.setdefault(n, []).append(e)
        sellers = {s['sellerId']: s for s in doc['views']['sellers']}
        if seller_id is None:
            if len(sellers) != 1:
                raise InputError(f'{len(sellers)} sellers in the ledger and no deployment naming one')
            seller_id = next(iter(sellers))
        if seller_id not in sellers:
            raise InputError(f'seller {seller_id} not in the ledger views')
        self.seller_id = seller_id
        self.seller = sellers[seller_id]
        self.bond_id = self.seller['bondId']
        self.bond = next((b for b in doc['views']['bonds'] if b['bondId'] == self.bond_id), None)
        profiles = {p['profileId']: p for p in doc['views']['profiles']}
        if self.seller['profileId'] not in profiles:
            raise InputError(f'profile {self.seller["profileId"]} of the seller not in the ledger views')
        self.profile = profiles[self.seller['profileId']]
        self.params = self.profile['parameters']
        self.purchases = {p['nonce']: p for p in doc['views']['purchases']}

    def named(self, *names):
        return [e for e in self.events if e['event'] in names]

    def of_seller(self, *names):
        return [e for e in self.named(*names) if e['args'].get('sellerId') == self.seller_id]

    def of_bond(self, *names):
        return [e for e in self.named(*names) if e['args'].get('bondId') == self.bond_id]

    def nonce_events(self, nonce, *names):
        return [e for e in self.by_nonce.get(nonce, []) if e['event'] in names]


# ---------------------------------------------------------------------------------------------
# Per-sale rows and cases


def _bad_nonces(rule, m, settled):
    if rule == 'all_cheater_episode_sales':
        return {s['nonce'] for s in settled}
    if rule == 'first_m':
        return {s['nonce'] for s in settled[:m]}
    return set()


def _confirmed_block(led, nonce, state, calls_by_nonce):
    """Block of a confirmed failure: CaseFinalized for a final FAIL; for UNSERVED the claim window or
    suspension it triggered, else the keeper's timeoutServe (the rule of services/internal/casepath)."""
    if state == 'FINAL':
        fin = led.nonce_events(nonce, 'CaseFinalized')
        return fin[-1]['block'] if fin else None
    blocks = [e['block'] for e in led.nonce_events(nonce, 'ClaimWindowOpened', 'SellerSuspended')
              if e['args'].get('triggerNonce') == nonce]
    if blocks:
        return min(blocks)
    for c in calls_by_nonce.get(nonce, []):
        if c.get('action') == 'timeoutServe' and c['tx'] in led.tx_block:
            return led.tx_block[c['tx']]
    return None


def _worst_path_mismatch(led, nonce, m, state):
    """Differences from the worst judgment path of maxAssignments m (services/internal/casepath)."""
    if state != 'FINAL':
        return ['not a final FAIL']
    ev = lambda *names: led.nonce_events(nonce, *names)  # noqa: E731
    bad = []

    def check(what, got, want):
        if got != want:
            bad.append(f'{what}: {got}, want {want}')
    opened = ev('CaseOpened')
    if len(opened) != 1 or opened[0]['args']['trigger'] != TRIGGER_SAMPLE:
        bad.append('not opened by sampling')
    per_stage = {}
    for e in ev('VerifierAssigned'):
        per_stage[e['args']['stage']] = per_stage.get(e['args']['stage'], 0) + 1
    check('initial assignments', per_stage.get(1, 0), m)
    check('party review assignments', per_stage.get(2, 0), m)
    check('tiebreak assignments', per_stage.get(4, 0), m)
    check('auto review assignments', per_stage.get(3, 0), 0)
    check('serve rounds', len(ev('ServeRequested')), 3 * m)
    check('evidence requests', len(ev('EvidenceRequested')), m)
    check('evidence disclosures', len(ev('EvidenceDisclosed')), 1)
    check('review reseals', len(ev('ReviewResealed')), 2)
    counts = dict(initial_fail=0, party_pass=0, tiebreak_fail=0, other=0)
    for e in ev('VerdictSubmitted'):
        a = e['args']
        if a['stage'] == 1 and a['verdict'] == 2:
            counts['initial_fail'] += 1
        elif a['stage'] == 2 and a['verdict'] == 1:
            counts['party_pass'] += 1
        elif a['stage'] == 4 and a['verdict'] == 2:
            counts['tiebreak_fail'] += 1
        else:
            counts['other'] += 1
    check('initial FAIL verdicts', counts['initial_fail'], m)
    check('party review PASS verdicts', counts['party_pass'], 1)
    check('tiebreak FAIL verdicts', counts['tiebreak_fail'], 1)
    check('other verdicts', counts['other'], 0)
    return bad


def build_sales(led, gt, calls, case_delays, g_default):
    """One row per settled sale of the seller, in settlement order, and the effective-detection cases."""
    settled = [dict(nonce=e['args']['nonce'], settled_block=e['block'], log_index=e['logIndex'],
                    epoch=e['args']['epoch'], value=_int(e['args']['value']), buyer=e['args']['buyer'])
               for e in led.of_seller('Settled')]
    rule, m = gt['bad_sales_rule'], gt.get('bad_sales_m')
    bad = _bad_nonces(rule, m, settled)
    calls_by_nonce, calls_by_epoch = {}, {}
    for c in calls:
        if c.get('nonce'):
            calls_by_nonce.setdefault(c['nonce'], []).append(c)
        if c.get('epoch'):
            calls_by_epoch.setdefault(c['epoch'], []).append(c)
    forfeits = sorted(e['block'] for e in led.of_bond('UnclaimedForfeited'))
    max_assignments = led.params['maxAssignments']
    sales, cases = [], []
    for index, s in enumerate(settled, 1):
        nonce = s['nonce']
        view = led.purchases.get(nonce)
        if view is None:
            raise InputError(f'purchase {nonce} has no view in the ledger')
        case = view['case']
        state = view['purchaseStateName']
        row = dict(s, index=index, bad=nonce in bad, g=g_default if nonce in bad else 0,
                   financial_state=state, release_block=_int(view['purchase']['releaseBlock']))
        released = led.nonce_events(nonce, 'Released')
        row['released_block'] = released[0]['block'] if released else None
        if row['released_block'] is not None:
            row['reached_block'] = row['released_block']
        elif state == 'RELEASABLE':
            row['reached_block'] = row['release_block']
        else:
            row['reached_block'] = None
        repaid = led.nonce_events(nonce, 'Refunded', 'FrozenClaimPaid')
        row['repaid_block'] = repaid[0]['block'] if repaid else None
        row['repaid_amount'] = sum(_int(e['args']['value']) for e in repaid)
        forfeited = [e['block'] for e in led.nonce_events(nonce, 'UnclaimedForfeited') if e['args']['nonce'] == nonce]
        if forfeited:
            row['forfeited_block'] = forfeited[0]
        elif state == 'FORFEITED':
            row['forfeited_block'] = next((b for b in forfeits if b >= s['settled_block']), None)
        else:
            row['forfeited_block'] = None
        row['lost_block'] = row['repaid_block'] or row['forfeited_block']
        row['outcome'] = 'reached' if state in REACHED else 'lost' if state in LOST else 'open'
        opened = led.nonce_events(nonce, 'CaseOpened')
        row['case_opened_block'] = opened[0]['block'] if opened else None
        row['case_trigger'] = opened[0]['args']['trigger'] if opened else None
        row['case_state'] = case['stateName'] if opened else None
        row['final_verdict'] = VERDICTS.get(case['finalVerdict']) if opened else None
        fin = led.nonce_events(nonce, 'CaseFinalized')
        row['case_finalized_block'] = fin[-1]['block'] if fin else None
        effective = opened and (case['stateName'] == 'UNSERVED' or
                                (case['stateName'] == 'FINAL' and case['finalVerdict'] == 2))
        row['effective_detection'] = 'UNSERVED' if effective and case['stateName'] == 'UNSERVED' else (
            'FAIL' if effective else None)
        row['confirmed_block'] = None
        if effective:
            confirmed = _confirmed_block(led, nonce, case['stateName'], calls_by_nonce)
            if confirmed is None:
                raise InputError(f'case {nonce}: {case["stateName"]} without a block that confirms it')
            row['confirmed_block'] = confirmed
            keeper_calls, unresolved = [], 0
            epoch_key = f'{led.seller_id}:{s["epoch"]}'
            for c in calls_by_nonce.get(nonce, []) + [c for c in calls_by_epoch.get(epoch_key, [])
                                                        if c.get('nonce') != nonce]:
                block = led.tx_block.get(c['tx'])
                if block is None:
                    unresolved += 1
                    continue
                if block > confirmed or block < s['settled_block']:
                    continue
                due = _int(c.get('due')) or 0
                keeper_calls.append(dict(action=c.get('action'), due=due, block=block,
                                         delay=block - due if due and block > due else 0))
            keeper_calls.sort(key=lambda k: (k['block'], k['action'] or '', k['due']))
            kappa_sigma = sum(k['delay'] for k in keeper_calls)
            mismatch = _worst_path_mismatch(led, nonce, max_assignments, case['stateName'])
            cd = case_delays.get(nonce)
            cases.append(dict(
                nonce=nonce, index=index, bad=row['bad'], outcome=row['effective_detection'],
                settled_block=s['settled_block'], confirmed_block=confirmed, trigger=row['case_trigger'],
                case_path_blocks=confirmed - s['settled_block'], keeper_delay_sum_blocks=kappa_sigma,
                case_path_minus_keeper=confirmed - s['settled_block'] - kappa_sigma,
                keeper_calls=keeper_calls, keeper_calls_unresolved=unresolved,
                case_delay_kappa_sigma=None if cd is None else _int(cd.get('kappa_sigma')),
                worst_path=not mismatch, worst_path_mismatch=mismatch))
        sales.append(row)
    return sales, cases


# ---------------------------------------------------------------------------------------------
# Episodes


def _episode_bounds(led, sales, view_block):
    """Episodes: from the start (first settlement) and from every SellerReinstated of the seller."""
    reinstated = [e['block'] for e in led.of_seller('SellerReinstated')]
    start = sales[0]['settled_block'] if sales else None
    starts = ([start] if start is not None else []) + [b for b in reinstated if start is None or b > start]
    return [(b, starts[i + 1] if i + 1 < len(starts) else None) for i, b in enumerate(starts)]


def _net_gain(sales_in, penalties):
    gain = 0
    for r in sales_in:
        if r['bad'] and r['outcome'] == 'reached':
            gain += r['g']
        elif r['bad'] and r['outcome'] == 'lost':
            gain += r['g'] - r['value']
        elif not r['bad'] and r['outcome'] == 'lost':
            gain -= r['value']
    return gain - penalties


def build_episodes(led, sales, cases, ctx):
    """Episode columns. A finite attack has one episode ending at the settlement block of the m-th
    bad sale plus T_hold plus T_case, or earlier at the first confirmed failure caused by a bad sale;
    other runs split at every re-entry and end each episode at its first confirmed failure."""
    confirmed = sorted((c['confirmed_block'], c['nonce']) for c in cases)
    slashes = [e for e in led.named('Slashed') if e['args']['actorType'] == ACTOR_SELLER
               and e['args']['actorId'] == led.seller_id]
    penalty_by_nonce = {}
    for e in slashes:
        penalty_by_nonce[e['args']['nonce']] = penalty_by_nonce.get(e['args']['nonce'], 0) + _int(e['args']['amount'])
    view_block = led.view_block
    out = []
    if ctx['finite']:
        bad = [r for r in sales if r['bad']]
        m = ctx['m']
        if len(bad) < m:
            out.append(dict(episode=1, start_block=sales[0]['settled_block'] if sales else None, mode='open',
                            end_block=None, sales=[r['nonce'] for r in sales], bad_sales=len(bad),
                            detected=False, detection_block=None, detected_by=None,
                            released_bad_gain=None, y_f=None, net_gain=None, deduction=ctx['deduction'],
                            note=f'{len(bad)} of {m} bad sales settled'))
        else:
            horizon_end = bad[m - 1]['settled_block'] + ctx['t_hold'] + ctx['t_case']
            detections = sorted((r['confirmed_block'], r['nonce']) for r in bad if r['effective_detection'])
            first = detections[0] if detections and detections[0][0] <= horizon_end else None
            end = first[0] if first else horizon_end
            mode = 'with_detection' if first else ('without_detection' if view_block >= end else 'open')
            released = sum(r['g'] for r in bad if r['reached_block'] is not None and r['reached_block'] <= end)
            in_ep = [r for r in sales if r['settled_block'] <= end]
            penalties = sum(penalty_by_nonce.get(r['nonce'], 0) for r in in_ep)
            y_f = None if mode == 'open' else released - (ctx['deduction'] if first else 0)
            out.append(dict(
                episode=1, start_block=sales[0]['settled_block'], end_block=None if mode == 'open' else end,
                horizon_end_block=horizon_end, mode=mode, detected=bool(first),
                detection_block=first[0] if first else None, detected_by=first[1] if first else None,
                sales=[r['nonce'] for r in in_ep], bad_sales=len(bad), released_bad_gain=released, y_f=y_f,
                deduction=ctx['deduction'],
                charged_deduction=penalty_by_nonce.get(first[1]) if first else None,
                net_gain=None if mode == 'open' else _net_gain(in_ep, penalties), penalties=penalties))
        return out
    for j, (start, nxt) in enumerate(_episode_bounds(led, sales, view_block), 1):
        in_ep = [r for r in sales if r['settled_block'] >= start and (nxt is None or r['settled_block'] < nxt)]
        ends = [b for b, _ in confirmed if b >= start and (nxt is None or b < nxt)]
        end = ends[0] if ends else None
        penalties = sum(penalty_by_nonce.get(r['nonce'], 0) for r in in_ep)
        out.append(dict(episode=j, start_block=start, next_start_block=nxt, end_block=end,
                        mode='with_detection' if end is not None else 'open',
                        sales=[r['nonce'] for r in in_ep], bad_sales=sum(r['bad'] for r in in_ep),
                        net_gain=_net_gain(in_ep, penalties), penalties=penalties))
    return out


def episode_columns(episodes, sales):
    by_nonce = {r['nonce']: r for r in sales}
    for ep in episodes:
        rows = [by_nonce[n] for n in ep['sales']]
        bad = [r for r in rows if r['bad']]
        ep['exposure'] = sum(r['g'] for r in bad if r['outcome'] == 'reached')
        detected = [r for r in bad if r['effective_detection']]
        first = detected[0] if detected else None
        if first is not None:
            k = bad.index(first) + 1
            ep['first_detection_index'] = dict(K=k, censored=False)
            at = (first['settled_block'], first['log_index'])
            after = [r for r in bad if (r['settled_block'], r['log_index']) > at]
            ep['post_detection_leak'] = sum(r['g'] for r in after if r['outcome'] == 'reached')
        else:
            ep['first_detection_index'] = dict(K=len(bad), censored=True)
            ep['post_detection_leak'] = 0
        repaid = [r for r in bad if r['repaid_block'] is not None]
        ep['buyer_refund_paid'] = sum(r['repaid_amount'] for r in repaid)
        ep['buyer_refund_blocks'] = [r['repaid_block'] - r['settled_block'] for r in repaid]
        ep['buyer_unrecovered_amount'] = sum(r['value'] for r in bad if r['outcome'] == 'reached'
                                             or r['financial_state'] == 'FORFEITED')
    return episodes


# ---------------------------------------------------------------------------------------------
# Verifiers and assignment failures


def verifier_columns(led, deployment, floor, sampled_cases, setup_block):
    registered = led.named('VerifierRegistered')
    initial = [e for e in registered if e['block'] <= setup_block]
    later = [e for e in registered if e['block'] > setup_block]
    removals = sorted(led.doc['derived']['verifierRemovals'], key=lambda r: (r['block'], r['logIndex']))
    bond_of = {e['args']['verifierId']: _int(e['args']['bond']) for e in registered}
    marked = {v['verifierId']: v.get('assignable') for v in (deployment or {}).get('verifiers', [])}
    expected_assignable = [e['args']['verifierId'] for e in initial
                           if marked.get(e['args']['verifierId'], True) is not False]
    under = sorted(v for v in expected_assignable + [e['args']['verifierId'] for e in later] if bond_of[v] < floor)
    pairs = []
    for i, r in enumerate(removals):
        rep = later[i] if i < len(later) else None
        pairs.append(dict(removed_verifier=r['verifierId'], removal_block=r['block'],
                          replacement_verifier=rep['args']['verifierId'] if rep else None,
                          replacement_block=rep['block'] if rep else None,
                          next_block=rep is not None and rep['block'] == r['block'] + 1))
    # Assignable-active count over time: +1 per registration at or above the floor, -1 per removal
    # or exit of such a verifier.
    deltas = []
    for e in registered:
        if bond_of[e['args']['verifierId']] >= floor:
            deltas.append((e['block'], e['logIndex'], 1))
    removed_ids = set()
    for r in removals:
        removed_ids.add(r['verifierId'])
        if bond_of.get(r['verifierId'], 0) >= floor:
            deltas.append((r['block'], r['logIndex'], -1))
    for e in led.named('VerifierExited'):
        v = e['args']['verifierId']
        if v not in removed_ids and bond_of.get(v, 0) >= floor:
            deltas.append((e['block'], e['logIndex'], -1))
    deltas.sort()
    timeline, count = [], 0
    for block, _, d in deltas:
        count += d
        if timeline and timeline[-1][0] == block:
            timeline[-1] = (block, count)
        else:
            timeline.append((block, count))

    def count_at(block):
        c = 0
        for b, v in timeline:
            if b > block:
                break
            c = v
        return c
    gaps = []
    for p in pairs:
        until = p['replacement_block'] if p['replacement_block'] is not None else led.view_block + 1
        points = [p['removal_block']] + [b for b, _ in timeline if p['removal_block'] < b < until]
        gaps.append(min(count_at(b) for b in points))
    removed = len(removals)
    return dict(
        registered_count=len(initial),
        assignable_count=sum(1 for e in initial if bond_of[e['args']['verifierId']] >= floor),
        assignable_floor=floor, expected_assignable=len(expected_assignable), under_floor=under,
        min_bond_ok=not under, removed_count=removed, replacement_count=len(later),
        removal_rate_per_case=removed / sampled_cases if sampled_cases else None,
        replacements=pairs, assignable_min_between_removal_and_replacement=gaps, setup_block=setup_block,
        assignable_at=count_at)


def assignment_failures(led, sales, assignable_at=None):
    """Cases that ended through the protocol INCONCLUSIVE path while their last stage had fewer
    assignments than maxAssignments and no INCONCLUSIVE verdict and no second seal lapse: the stage
    found no eligible verifier (FairBindCore _assignVerifier). The cause counts the verifiers of the
    epoch's checkpoint that the case had already used (participation) and that strikes had removed
    by then; `liability_or_draw` when neither explains every checkpoint entry."""
    m = led.params['maxAssignments']
    seals = {(e['args']['sellerId'], e['args']['epoch']): e for e in led.of_seller('EpochSealed')}
    checkpoints = {cp['version']: cp for cp in led.profile.get('checkpoints', [])}
    removals = led.doc['derived']['verifierRemovals']
    out = []
    for r in sales:
        if r['case_trigger'] is None:
            continue
        view = led.purchases[r['nonce']]['case']
        keeper_publication = view['requesterRole'] == REQUESTER_KEEPER and view['stage'] == 1
        inconclusive = view['stateName'] == 'INCONCLUSIVE' or (view['stateName'] == 'FINAL'
                                                               and view['finalVerdict'] == 3)
        if not (keeper_publication or inconclusive):
            continue
        events = led.by_nonce.get(r['nonce'], [])
        assigned = [e for e in events if e['event'] == 'VerifierAssigned']
        stages = [e['args']['stage'] for e in assigned] + [1]
        selected = [e for e in events if e['event'] == 'ReviewSelected']
        for e in selected:
            stages.append(2 if e['args']['partyAppeal'] else 3)
        verdicts = [e for e in events if e['event'] == 'VerdictSubmitted']
        review = [e for e in verdicts if e['args']['stage'] in (2, 3)]
        initial = [e for e in verdicts if e['args']['stage'] == 1]
        if review and initial and review[-1]['args']['verdict'] != initial[-1]['args']['verdict']:
            stages.append(4)
        stage = max(stages)
        in_stage = [e for e in assigned if e['args']['stage'] == stage]
        if len(in_stage) >= m:
            continue
        if any(e['args']['stage'] == stage and e['args']['verdict'] == 3 for e in verdicts):
            continue
        if sum(1 for e in events if e['event'] == 'ReviewResealed' and e['args']['stage'] == stage) >= 2:
            continue
        prior = [e for e in events if e['event'] in ('VerifierAssigned', 'CaseOpened', 'ReviewSelected',
                                                     'VerdictSubmitted', 'Slashed', 'ReviewResealed')]
        block = prior[-1]['block'] if prior else r['case_opened_block']
        seal = seals.get((led.seller_id, r['epoch']))
        cp = checkpoints.get(seal['args']['sortitionVersion']) if seal else None
        ids = cp['verifierIds'] if cp else []
        used = {e['args']['verifierId'] for e in assigned}
        gone = {x['verifierId'] for x in removals if x['block'] <= block}
        participated = sum(1 for v in ids if v in used)
        removed = sum(1 for v in ids if v not in used and v in gone)
        if ids and participated + removed == len(ids):
            cause = 'strike_removal' if removed else 'participation'
        else:
            cause = 'liability_or_draw'
        out.append(dict(nonce=r['nonce'], stage=STAGES[stage], attempt=len(in_stage), block=block, cause=cause,
                        checkpoint_version=seal['args']['sortitionVersion'] if seal else None,
                        checkpoint_size=len(ids), participated=participated, removed=removed,
                        assignable_count=assignable_at(block) if assignable_at else None))
    return out


# ---------------------------------------------------------------------------------------------
# Injection audit


def injection_audit(led, records, directive, sales, worst):
    """Re-derive every recorded draw and outcome and match the records with the submitted verdicts."""
    block = (directive or {}).get('judgment_injection')
    seed = (directive or {}).get('seed')
    bad = {r['nonce']: r['bad'] for r in sales}
    sampled = {r['nonce'] for r in sales if r['case_trigger'] == TRIGGER_SAMPLE}
    mismatches = []
    by_key = {}
    for rec in records or []:
        key = (rec['nonce'], rec['stage'], rec['attempt'], rec['verifierId'])
        by_key[key] = rec
        where = rec.get('_file')
        if seed is not None and rec.get('seed') != seed:
            mismatches.append(dict(record=where, field='seed', recorded=rec.get('seed'), expected=seed))
        if block is not None:
            want = dict(h=block['h'], alpha=block['alpha'], beta=block['beta'], c=block['c'],
                        honestErrorOff=bool(block.get('honest_error_off')))
            if rec.get('params') != want:
                mismatches.append(dict(record=where, field='params', recorded=rec.get('params'), expected=want))
        if not rec.get('applied'):
            if rec.get('honestyDraw') is not None or rec.get('outcomeDraw') is not None:
                mismatches.append(dict(record=where, field='draws', recorded='present', expected='null'))
            if rec.get('verdict') != rec.get('predicateVerdict'):
                mismatches.append(dict(record=where, field='verdict', recorded=rec.get('verdict'),
                                       expected=rec.get('predicateVerdict')))
            continue
        u = {p: injection_draw(rec['seed'], rec['nonce'], rec['stage'], rec['attempt'], p) for p in PURPOSES}
        for purpose, field in (('honesty', 'honestyDraw'), ('outcome', 'outcomeDraw')):
            if rec.get(field) != u[purpose]:
                mismatches.append(dict(record=where, field=field, recorded=rec.get(field), expected=u[purpose]))
        honest, rule, verdict = injected_verdict(rec['params'], rec['predicateVerdict'], u['honesty'], u['outcome'])
        for field, value in (('honest', honest), ('outcomeRule', rule), ('verdict', verdict)):
            if rec.get(field) != value:
                mismatches.append(dict(record=where, field=field, recorded=rec.get(field), expected=value))
    # Every verdict submitted on an injected assignment has a record with the same verdict.
    assigned = {}
    for e in led.named('VerifierAssigned'):
        a = e['args']
        assigned[(a['nonce'], a['stage'], a['verifierId'])] = a['attempt']
    unrecorded, disagreeing, truth_mismatch = [], [], []
    submitted = 0
    for e in led.named('VerdictSubmitted'):
        a = e['args']
        if a['nonce'] not in bad:
            continue
        if worst and bad[a['nonce']] and a['nonce'] in sampled:
            continue  # the worst-path directive decides these verdicts
        submitted += 1
        attempt = assigned.get((a['nonce'], a['stage'], a['verifierId']))
        rec = by_key.get((a['nonce'], a['stage'], attempt, a['verifierId']))
        if rec is None:
            unrecorded.append(dict(nonce=a['nonce'], stage=a['stage'], verifierId=a['verifierId']))
        elif rec.get('verdict') != VERDICTS.get(a['verdict']):
            disagreeing.append(dict(nonce=a['nonce'], stage=a['stage'], verifierId=a['verifierId'],
                                    recorded=rec.get('verdict'), submitted=VERDICTS.get(a['verdict'])))
    for rec in records or []:
        if rec.get('gate') != 'READY' or rec['nonce'] not in bad:
            continue
        want = 'FAIL' if bad[rec['nonce']] else 'PASS'
        if rec.get('predicateVerdict') != want:
            truth_mismatch.append(dict(record=rec.get('_file'), predicate=rec.get('predicateVerdict'), truth=want))
    applied = [r for r in records or [] if r.get('applied')]
    return dict(directive_present=block is not None, records=len(records or []), applied=len(applied),
                honest_draws=sum(1 for r in applied if r.get('honest')), draw_mismatches=mismatches,
                verdicts_checked=submitted, unrecorded_verdicts=unrecorded, disagreeing_verdicts=disagreeing,
                predicate_truth_mismatches=truth_mismatch)


# ---------------------------------------------------------------------------------------------
# Collection


def _seller_id(inputs):
    dep = inputs['deployment']
    if dep and dep.get('seller', {}).get('sellerId') is not None:
        return dep['seller']['sellerId']
    return None


def _g(gt, params):
    g = (gt.get('parameters') or {}).get('bad_sale_gain_atomic')
    if isinstance(g, int) and not isinstance(g, bool):
        return g
    return _int(params['maxPurchaseValue'])


def _active_blocks(led, start, end):
    """Blocks in [start, end] in which the seller was ACTIVE (not suspended, exiting or exited)."""
    if start is None or end < start:
        return 0
    changes = []
    for e in led.of_seller('SellerSuspended', 'SellerReinstated', 'SellerExitRequested', 'SellerExited'):
        changes.append((e['block'], e['logIndex'], e['event'] == 'SellerReinstated'))
    changes.sort()
    active, at, total = True, start, 0
    for block, _, becomes in changes:
        if block < start:
            active = becomes
            continue
        if block > end:
            break
        if active:
            total += block - at
        active, at = becomes, block
    if active:
        total += end + 1 - at
    return total


def collect(inputs):
    gt = inputs['ground_truth']
    led = Ledger(inputs['ledger'], _seller_id(inputs))
    params = led.params
    profile_doc = inputs['profile_doc']
    shared = profile_doc['profiles'][0] if len(profile_doc.get('profiles') or []) == 1 else next(
        (p for p in profile_doc.get('profiles') or [] if p.get('profileId') == led.seller['profileId']), None)
    if shared is None or 'deadlineConfig' not in shared.get('parameters', {}):
        raise InputError('shared/profile.json names no profile with a deadline configuration')
    merged = dict(parameters=dict(params, deadlineConfig=shared['parameters']['deadlineConfig']))
    t_case = prof.case_horizon(merged)
    t_hold = max(_int(params['deferBlocks']), _int(params['retentionBlocks']))
    margin = _int(params['marginBlocks'])
    penalty, k = _int(params['sellerPenalty']), _int(params['failureLimit'])
    floor = prof.assignable_bond_floor(dict(parameters=params))
    gparams = gt.get('parameters') or {}
    kappa = gparams.get('keeper_delay_budget_blocks', 0)
    kappa = kappa if isinstance(kappa, int) and not isinstance(kappa, bool) else 0
    worst = gparams.get('judgment_path') == 'worst'
    directives = inputs['directives']
    seller_dir = directives.get('seller') or {}
    policy_block = seller_dir.get('seller_policy') or {}
    finite_block = seller_dir.get('finite_attack') or {}
    after = finite_block.get('after') or gparams.get('finite_attack_after')
    role = policy_block.get('role') or gparams.get('seller_role')
    rule = gt['bad_sales_rule']
    ctx = dict(finite=rule == 'first_m', m=gt.get('bad_sales_m'), t_hold=t_hold, t_case=t_case,
               deduction=penalty // k if k else None)

    rows = inputs['keeper_rows'] or []
    calls = [dict(action=r.get('action'), tx=(r.get('tx') or '').lower(), due=r.get('due'),
                  nonce=(r.get('nonce') or '').lower(), epoch=r.get('epoch') or '')
             for r in rows if r.get('event') == 'call_sent' and r.get('status') == 'sent' and r.get('tx')]
    case_delays = {}
    for r in rows:
        if r.get('event') == 'case_delay' and r.get('nonce'):
            case_delays[r['nonce'].lower()] = r
    sales, cases = build_sales(led, gt, calls, case_delays, _g(gt, params))
    episodes = episode_columns(build_episodes(led, sales, cases, ctx), sales)

    dep = inputs['deployment'] or {}
    setup_block = dep.get('setupBlock')
    if setup_block is None:
        setup_block = (sales[0]['settled_block'] - 1) if sales else led.view_block
    sampled_cases = sum(1 for r in sales if r['case_trigger'] == TRIGGER_SAMPLE)
    verifiers = verifier_columns(led, dep, floor, sampled_cases, setup_block)
    failures = assignment_failures(led, sales, verifiers['assignable_at'])
    audit = injection_audit(led, inputs['injection_records'], directives.get('verifier'), sales, worst)

    # Exits (F-exit) and what was still deferred then.
    def deferred_at(block):
        open_rows = [r for r in sales if r['settled_block'] <= block
                     and not (r['reached_block'] is not None and r['reached_block'] <= block)
                     and not (r['lost_block'] is not None and r['lost_block'] <= block)]
        return len(open_rows), sum(r['value'] for r in open_rows)

    def open_sampled_at(block):
        return sum(1 for r in sales if r['case_trigger'] == TRIGGER_SAMPLE and r['case_opened_block'] <= block
                   and (r['case_finalized_block'] is None or r['case_finalized_block'] > block)
                   and not (r['effective_detection'] and r['confirmed_block'] <= block))
    seller_exits = [dict(block=e['block'], deferred_entries=deferred_at(e['block'])[0])
                    for e in led.of_seller('SellerExited')]
    bond_exits = [dict(block=e['block'], deferred_balance=deferred_at(e['block'])[1],
                       open_sampled_cases=open_sampled_at(e['block'])) for e in led.of_bond('BondExited')]

    # Honest windows: complete windows of failureWindowBlocks laid end to end from the start of the
    # experiment plus T_hold; truncated windows are left out.
    first_window = honest_first_window(inputs['workload_summary'], sales, t_hold)
    width = _int(params['failureWindowBlocks'])
    windows = []
    if rule == 'none' and first_window is not None:
        sanctions = [e['block'] for e in led.of_seller('SellerSanctioned')]
        a = first_window
        while a + width - 1 <= led.view_block:
            b = a + width - 1
            windows.append(dict(start=a, end=b, wrongful_confirmed_failures=sum(
                1 for r in sales if not r['bad'] and r['effective_detection'] and a <= r['confirmed_block'] <= b),
                sanctioned=sum(1 for x in sanctions if a <= x <= b)))
            a += width

    honest_sampled = [r for r in sales if not r['bad'] and r['case_trigger'] == TRIGGER_SAMPLE
                      and r['case_state'] in TERMINAL_CASE_STATES]
    wrongful_final = [r for r in sales if not r['bad'] and r['final_verdict'] == 'FAIL' and r['case_state'] == 'FINAL']
    post_switch = []
    if ctx['finite'] and after == 'serve_honestly':
        post = [r for r in sales if not r['bad'] and r['effective_detection']]
        post_switch.append(dict(FAIL=sum(1 for r in post if r['effective_detection'] == 'FAIL'),
                                UNSERVED=sum(1 for r in post if r['effective_detection'] == 'UNSERVED')))

    # Verdict counts by truth, per stage and final.
    counts = {}
    truth_of = {r['nonce']: ('bad' if r['bad'] else 'honest') for r in sales}
    for e in led.named('VerdictSubmitted'):
        n = e['args']['nonce']
        if n in truth_of:
            key = (truth_of[n], STAGES.get(e['args']['stage'], str(e['args']['stage'])))
            v = VERDICTS.get(e['args']['verdict']) or 'NONE'
            counts.setdefault(key, {})[v] = counts.setdefault(key, {}).get(v, 0) + 1
    for r in sales:
        if r['case_state'] in ('FINAL', 'UNSERVED', 'INCONCLUSIVE'):
            v = 'UNSERVED' if r['case_state'] == 'UNSERVED' else (r['final_verdict'] or 'NONE')
            key = (truth_of[r['nonce']], 'final')
            counts.setdefault(key, {})[v] = counts.setdefault(key, {}).get(v, 0) + 1
    verdict_counts = [dict(truth=t, stage=s, **{v: c.get(v, 0) for v in ('PASS', 'FAIL', 'INCONCLUSIVE', 'UNSERVED')})
                      for (t, s), c in sorted(counts.items())]

    policy_actions = (inputs['policy'] or {}).get('actions')
    fault = fault_observed(inputs, led, sales, cases, ctx, kappa, worst, after, verifiers, audit, post_switch)

    # Metric values.
    bad_rows = [r for r in sales if r['bad']]
    released_exposure = sum(r['g'] for r in bad_rows if r['outcome'] == 'reached')
    slashes = [e for e in led.named('Slashed') if e['args']['actorType'] == ACTOR_SELLER
               and e['args']['actorId'] == led.seller_id]
    penalties = sum(_int(e['args']['amount']) for e in slashes)
    sealed = {e['args']['epoch'] for e in led.of_seller('EpochSealed')}
    det_den = [r for r in bad_rows if r['epoch'] in sealed and (r['case_state'] is None
                                                                 or r['case_state'] in TERMINAL_CASE_STATES)]
    # Per-sale eligibility for a detection (metrics.md, detection_eligible): the epoch was sealed, its
    # sampling window (openSample through sealDeadline + openBlocks) ended by the view block, and the
    # sale has no case or a terminal one.
    open_blocks = _int(merged['parameters']['deadlineConfig']['openBlocks'])
    seal_blocks = _int(merged['parameters']['deadlineConfig']['sealBlocks'])
    window_end = {e['args']['epoch']: e['args']['randomBlock'] + seal_blocks + open_blocks
                  for e in led.of_seller('Anchored')}
    for r in sales:
        end = window_end.get(r['epoch'])
        r['detection_eligible'] = (r['epoch'] in sealed and end is not None and end <= led.view_block
                                   and (r['case_state'] is None or r['case_state'] in TERMINAL_CASE_STATES))
    in_sealed = [r for r in sales if r['epoch'] in sealed]
    window_end = led.view_block
    first_settle = sales[0]['settled_block'] if sales else None
    active = _active_blocks(led, first_settle, window_end)
    m = {}
    m['released_exposure'] = released_exposure
    m['episode_exposure'] = [ep['exposure'] for ep in episodes]
    m['episode_net_gain'] = [ep['net_gain'] for ep in episodes]
    if len(episodes) >= 2:
        m['second_episode_exposure'] = episodes[1]['exposure']
        m['second_episode_net_gain'] = episodes[1]['net_gain']
    m['cheater_net_gain'] = (sum(r['g'] for r in bad_rows) - sum(r['value'] for r in sales if r['outcome'] == 'lost')
                             - penalties)
    if penalty:
        m['exposure_vs_bond'] = released_exposure / penalty
    m['post_detection_leak'] = [ep['post_detection_leak'] for ep in episodes]
    reinstated = [e['block'] for e in led.of_seller('SellerReinstated')]
    m['releases_after_reentry'] = sum(1 for r in bad_rows if r['outcome'] == 'reached' and reinstated
                                      and r['settled_block'] > reinstated[0])
    m['first_detection_index'] = [ep['first_detection_index'] for ep in episodes]
    m['episode_end_mode'] = [ep['mode'] for ep in episodes]
    m['episode_end_block'] = [ep['end_block'] for ep in episodes]
    m['y_f'] = [ep['y_f'] for ep in episodes] if ctx['finite'] else []
    m['buyer_refund_paid'] = [ep['buyer_refund_paid'] for ep in episodes]
    m['buyer_refund_paid_blocks'] = [b for ep in episodes for b in ep['buyer_refund_blocks']]
    m['buyer_unrecovered_amount'] = [ep['buyer_unrecovered_amount'] for ep in episodes]
    if det_den:
        m['realized_detection_rate'] = sum(1 for r in det_den if r['effective_detection']) / len(det_den)
    if in_sealed:
        m['realized_sample_rate'] = sum(1 for r in in_sealed if r['case_trigger'] == TRIGGER_SAMPLE) / len(in_sealed)
    m['case_path_blocks'] = [c['case_path_blocks'] for c in cases]
    m['keeper_delay_sum_blocks'] = [c['keeper_delay_sum_blocks'] for c in cases]
    m['case_path_minus_keeper'] = [c['case_path_minus_keeper'] for c in cases]
    if cases:
        m['keeper_delay_sum_max_blocks'] = max(c['keeper_delay_sum_blocks'] for c in cases)
    m['worst_path_case_blocks'] = [c['case_path_minus_keeper'] for c in cases if worst and c['worst_path']]
    m['judgment_delay_distribution'] = [r['case_finalized_block'] - r['settled_block'] for r in sales
                                        if r['case_finalized_block'] is not None]
    m['recovery_time_blocks'] = [r['repaid_block'] - r['settled_block'] for r in sales if r['repaid_block'] is not None]
    m['frozen_amount'] = [_int(e['args']['frozenTotal']) for e in led.of_bond('SellerDeferredFrozen')]
    settle_block = {r['nonce']: r['settled_block'] for r in sales}
    m['freeze_delay_blocks'] = [_int(e['args']['frozenAtBlock']) - settle_block[e['args']['triggerNonce']]
                                for e in led.of_bond('SellerDeferredFrozen')
                                if e['args']['triggerNonce'] in settle_block]
    m['seller_penalty_charged'] = penalties
    m['suspension_count'] = len(led.of_seller('SellerSuspended'))
    m['reinstatement_count'] = len(reinstated)
    m['final_failure_count'] = sum(1 for r in sales if r['case_state'] == 'FINAL' and r['final_verdict'] == 'FAIL')
    m['wrongful_final_fail_count'] = len(wrongful_final)
    m['false_positive_recovery_amount'] = sum(r['value'] for r in sales if rule == 'none' and r['outcome'] == 'lost')
    if rule == 'none':
        m['honest_seller_delay_blocks'] = [r['released_block'] - r['settled_block'] for r in sales
                                           if r['released_block'] is not None]
        if first_settle is not None and window_end >= first_settle:
            total = window_end - first_settle + 1
            m['honest_seller_suspended_fraction'] = (total - active) / total
        if windows:
            m['honest_sanctions_per_window'] = sum(w['sanctioned'] for w in windows) / len(windows)
        if honest_sampled:
            wrongful_sampled = sum(1 for r in honest_sampled
                                   if r['case_state'] == 'FINAL' and r['final_verdict'] == 'FAIL')
            m['wrongful_final_fail_per_sampled_case'] = wrongful_sampled / len(honest_sampled)
    m['honest_windows'] = windows
    if active:
        m['achieved_settlement_rate'] = len(sales) / active
    workload = (directives.get('buyer') or {}).get('workload') or {}
    if isinstance(workload.get('rate_per_block'), (int, float)) and not isinstance(workload['rate_per_block'], bool):
        m['configured_settlement_rate'] = workload['rate_per_block']
    m['effective_hold_period_blocks'] = t_hold
    m['freeze_on_initial_fail'] = 1 if params['freezeOnInitialFail'] else 0
    if policy_actions is not None and role == 'honest':
        m['honest_top_up_count'] = sum(1 for a in policy_actions if a.get('action') == 'top_up'
                                       and a.get('cause') == 'deduction')
    if rule == 'none':
        scales = [_int(e['args']['scaleFactor']) for e in led.of_bond('BondRegistered')]
        scales += [_int(e['args']['newScaleFactor']) for e in led.of_bond('BondScaled')]
        if led.bond is not None:
            scales.append(_int(led.bond['failureWindowScale']))
        if scales:
            m['honest_max_window_scale'] = max(scales)
    attempts = inputs.get('facilitator_attempts')
    if attempts is not None:
        rejected = [a for a in attempts if a.get('status') == 'rejected']
        m['rejected_settlement_count'] = sum(1 for a in rejected if a.get('revert') == 'RateLimitExceeded')
        by_revert = {}
        for a in rejected:
            by_revert[a.get('revert') or ''] = by_revert.get(a.get('revert') or '', 0) + 1
        m['rejected_settlements_by_revert'] = dict(sorted(by_revert.items()))
    m['verifier_registered_count'] = verifiers['registered_count']
    m['verifier_assignable_count'] = verifiers['assignable_count']
    m['verifier_min_bond_ok'] = 1 if verifiers['min_bond_ok'] else 0
    m['verifier_removed_count'] = verifiers['removed_count']
    if verifiers['removal_rate_per_case'] is not None:
        m['verifier_removal_rate_per_case'] = verifiers['removal_rate_per_case']
    m['verifier_replacement_count'] = verifiers['replacement_count']
    m['assignable_min_between_removal_and_replacement'] = verifiers['assignable_min_between_removal_and_replacement']
    m['assignment_failure'] = [dict(nonce=f['nonce'], stage=f['stage'], cause=f['cause'], block=f['block'],
                                    assignable_count=f['assignable_count']) for f in failures]
    m['post_switch_confirmed_failures'] = post_switch
    m['seller_exit_finalized_block'] = [x['block'] for x in seller_exits]
    m['seller_exit_deferred_entries'] = [x['deferred_entries'] for x in seller_exits]
    m['bond_exit_finalized_block'] = [x['block'] for x in bond_exits]
    m['bond_exit_deferred_balance'] = [x['deferred_balance'] for x in bond_exits]
    m['bond_exit_open_sampled_cases'] = [x['open_sampled_cases'] for x in bond_exits]
    m['operating_point_k'] = k
    m['verdict_counts_by_truth'] = verdict_counts
    m['injection_draw_mismatch_count'] = len(audit['draw_mismatches'])
    m['fault_observed'] = fault

    run = dict(
        run_id=gt.get('run_id'), scenario=gt.get('scenario'), cell=gt.get('cell'), bad_sales_rule=rule,
        bad_sales_m=gt.get('bad_sales_m'), seller_id=led.seller_id, bond_id=led.bond_id,
        profile_id=led.seller['profileId'], seller_role=role, finite_attack_after=after, judgment_path=(
            'worst' if worst else 'normal'), kappa=kappa, g=_g(gt, params), v=_int(params['maxPurchaseValue']),
        seller_penalty=penalty, failure_limit=k, deduction=ctx['deduction'], t_hold=t_hold, t_case=t_case,
        margin_blocks=margin, keeper_margin=t_hold - t_case, view_block=led.view_block, setup_block=setup_block,
        profile_hash_matches=shared.get('parameterHash') in (None, params.get('parameterHash')))
    sources, workload, timing = split_nondeterministic(inputs['sources'], inputs['workload_summary'])
    return dict(
        format=FORMAT, run=run, sources=sources, sales=sales, cases=cases, episodes=episodes,
        verifiers={k: v for k, v in verifiers.items() if k != 'assignable_at'}, assignment_failures=failures, injection=audit, seller_exits=seller_exits,
        bond_exits=bond_exits, workload_summary=workload, nondeterministic=timing,
        pool_replacements=None if inputs['pool_replacements'] is None else dict(
            lines=len(inputs['pool_replacements']), matches_ledger=len(inputs['pool_replacements'])
            == verifiers['replacement_count']),
        policy_actions=policy_actions, metrics=m)


def split_nondeterministic(sources, summary):
    """Split the parts of the document that differ between two runs with the same seed: the input
    files' SHA-256 (the files carry wall-clock times) and the driver's wall-clock and timing fields.
    Returns (sources without sha256, workload summary without them, the split-off part)."""
    kept = {k: {f: v for f, v in s.items() if f != 'sha256'} for k, s in (sources or {}).items()}
    timing = dict(sources_sha256={k: s.get('sha256') for k, s in (sources or {}).items()})
    if summary is None:
        return kept, None, timing
    summary = json.loads(json.dumps(summary))
    timing['workload_wall'] = summary.pop('wall', None)
    clock = summary.get('clock') or {}
    timing['workload_clock'] = {k: clock.pop(k) for k in sorted(clock) if k.endswith(('_seconds', '_ms'))}
    return kept, summary, timing


def honest_first_window(summary, sales, t_hold):
    """First block of the first honest window: the workload driver's honest_windows.first_window_start,
    else its start block (blocks.start) plus T_hold, else the first settlement plus T_hold."""
    summary = summary or {}
    first = (summary.get('honest_windows') or {}).get('first_window_start')
    if first is not None:
        return first
    start = (summary.get('blocks') or {}).get('start')
    if start is None:
        start = sales[0]['settled_block'] if sales else None
    return None if start is None else start + t_hold


def worst_path_missed(inputs, led):
    """Worst-path calls that did not land in the block the directive names: the keeper's
    worst_path_missed rows, and openSample calls whose transaction landed after their due block (the
    last block of the open window), each once by key."""
    out = {}
    for r in inputs['keeper_rows'] or []:
        if r.get('event') == 'worst_path_missed':
            out[r.get('key')] = dict(action=r.get('action'), key=r.get('key'), nonce=r.get('nonce'),
                                     target_block=r.get('target_block'), sent=r.get('sent'),
                                     lateness_blocks=_int(r.get('lateness_blocks')) or 0, source='keeper')
    for r in inputs['keeper_rows'] or []:
        if r.get('event') != 'call_sent' or r.get('action') != 'openSample' or not r.get('tx'):
            continue
        block, due = led.tx_block.get(r['tx'].lower()), _int(r.get('due'))
        if block is not None and due and block > due:
            out[r.get('key')] = dict(action='openSample', key=r.get('key'), nonce=r.get('nonce'), target_block=due,
                                     sent=True, lateness_blocks=block - due, source='ledger')
    return sorted(out.values(), key=lambda m: (m['target_block'] or 0, m['key'] or ''))


def fault_observed(inputs, led, sales, cases, ctx, kappa, worst, after, verifiers, audit, post_switch):
    """Whether each injected behavior happened: one item per check, with applicability and a reason."""
    items = []

    def item(name, applicable, ok, reason):
        items.append(dict(item=name, applicable=applicable, ok=bool(ok) if applicable else True, reason=reason))
    if ctx['finite']:
        attack = inputs['attack']
        gt_bad = [r['nonce'] for r in sales if r['bad']]
        if attack is None:
            item('bad_responses', True, False, 'the seller attack record (meta/attack.json) is missing')
        else:
            cheated = [c.lower() for c in attack.get('cheated') or []]
            item('bad_responses', True, cheated == gt_bad,
                 f'seller cheated {len(cheated)} sales, ground truth {len(gt_bad)}'
                 + ('' if cheated == gt_bad else ' (lists differ)'))
    else:
        item('bad_responses', False, True, 'the seller keeps a per-sale cheat record only in a finite attack; '
             'predicate_matches_truth checks the responses')
    records = inputs['injection_records'] or []
    ready = [r for r in records if r.get('gate') == 'READY' and r['nonce'] in {s['nonce'] for s in sales}]
    item('predicate_matches_truth', bool(ready), not audit['predicate_truth_mismatches'],
         f'{len(ready)} judged assignments, {len(audit["predicate_truth_mismatches"])} predicate verdicts against '
         'the ground truth' if ready else 'no injection record of a judged assignment')
    applicable = audit['directive_present'] or bool(records)
    problems = []
    if audit['directive_present'] and audit['verdicts_checked'] and not records:
        problems.append('no injection records')
    if audit['draw_mismatches']:
        problems.append(f'{len(audit["draw_mismatches"])} record fields differ from the re-derived draw')
    if audit['unrecorded_verdicts']:
        problems.append(f'{len(audit["unrecorded_verdicts"])} submitted verdicts without a record')
    if audit['disagreeing_verdicts']:
        problems.append(f'{len(audit["disagreeing_verdicts"])} submitted verdicts differ from the record')
    item('injection_log', applicable, not problems,
         '; '.join(problems) or f'{audit["records"]} records, {audit["verdicts_checked"]} verdicts matched')
    if kappa > 0:
        off = [c['nonce'] for c in cases if c['keeper_delay_sum_blocks'] != kappa
               or (c['case_delay_kappa_sigma'] is not None and c['case_delay_kappa_sigma'] != kappa)]
        item('kappa_sigma', True, bool(cases) and not off,
             f'{len(cases)} effective-detection cases, {len(off)} with kappa_Sigma != {kappa}'
             if cases else 'no effective-detection case')
    else:
        item('kappa_sigma', False, True, 'keeper delay budget 0')
    if worst:
        directed = [c for c in cases if c['bad'] and c['trigger'] == TRIGGER_SAMPLE]
        off = [c['nonce'] for c in directed if not c['worst_path']]
        missed = worst_path_missed(inputs, led)
        reason = (f'{len(directed)} sampled bad-sale cases, {len(off)} off the worst path'
                  if directed else 'no sampled bad-sale case ended in a confirmed failure')
        if missed:
            reason += (f'; {len(missed)} worst-path calls missed their block (lateness '
                       f'{sorted(m["lateness_blocks"] for m in missed)} blocks)')
        item('worst_path_structure', True, bool(directed) and not off and not missed, reason)
    else:
        item('worst_path_structure', False, True, 'normal judgment path')
    if post_switch:
        n = post_switch[0]['FAIL'] + post_switch[0]['UNSERVED']
        item('post_switch_no_confirmed_failure', True, n == 0,
             f'{post_switch[0]["FAIL"]} final FAIL and {post_switch[0]["UNSERVED"]} UNSERVED after the switch')
    else:
        item('post_switch_no_confirmed_failure', False, True, 'not a finite attack that switches to honest sales')
    item('verifier_bonds', True, verifiers['min_bond_ok'],
         f'{len(verifiers["under_floor"])} assignable or replacement verifiers below the floor '
         f'{verifiers["assignable_floor"]}')
    reps = verifiers['replacements']
    late = [p for p in reps if not p['next_block']]
    # The rule checks the registration block; the pool checkpoints the verifier tree in a later block,
    # so the measured removal-to-checkpoint gap (the pool's gapBlocks) is reported alongside.
    gaps = {(r.get('removedVerifierId'), r.get('removalBlock')): r.get('gapBlocks')
            for r in inputs.get('pool_replacements') or []}
    detail = '; '.join(
        f"verifier {p['removed_verifier']} removed at {p['removal_block']}, registered "
        f"{'-' if p['replacement_block'] is None else p['replacement_block'] - p['removal_block']} blocks later, "
        f"checkpoint gap {gaps.get((p['removed_verifier'], p['removal_block']), '-')} blocks" for p in reps)
    item('replacement_next_block', bool(reps), not late,
         f'{len(reps)} removals, {len(late)} not registered in the next block ({detail})' if reps
         else 'no verifier removed')
    return items


# ---------------------------------------------------------------------------------------------
# Output


def rows(document):
    """Observation rows, one per metric, in metric order."""
    run_id = document['run']['run_id']
    return [dict(metric=k, value=v, observation_id=run_id) for k, v in sorted(document['metrics'].items())
            if v is not None]


def _dumps(value, **kw):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, **kw)


def write(document, out, doc_path):
    out, doc_path = Path(out), Path(doc_path)
    for path, text in ((doc_path, _dumps(document) + '\n'),
                       (out, ''.join(_dumps(r) + '\n' for r in rows(document)))):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name('.' + path.name + '.tmp')
        tmp.write_text(text)
        tmp.replace(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--rpc-url', help='JSON-RPC URL of the run chain (used only to dump a missing ledger)')
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--ground-truth', required=True)
    ap.add_argument('--out', required=True, help='observation rows (JSON lines)')
    ap.add_argument('--ledger', help='ledger dump to read instead of RUN/ledger.json')
    ap.add_argument('--document', help='observations document (default: --out with the suffix .json)')
    ap.add_argument('--injection-dir', action='append', help='verifier injection record directory (repeatable; '
                    'default: every injection directory under the run directory)')
    a = ap.parse_args(argv)
    doc_path = a.document or str(Path(a.out).with_suffix('.json'))
    if Path(doc_path).resolve() == Path(a.out).resolve():
        ap.error('--document must differ from --out')
    try:
        inputs = load_inputs(a.run_dir, a.ground_truth, ledger=a.ledger, rpc_url=a.rpc_url,
                             injection_dirs=a.injection_dir)
        document = collect(inputs)
    except InputError as exc:
        print(f'collect_run: {exc}', file=sys.stderr)
        return 2
    write(document, a.out, doc_path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
