"""Resumable C1 data-API collector.

Opens one cell per 5-minute UTC grid time. In each cell it captures the two
seller-role sources, assigns each successful capture a role (honest or wrong
answer) and a wrong-answer type from seeded lists, and has three verifier
instances (separate `c1tool instance` processes) capture the two references on
a seeded schedule and judge every response of the cell. A cell is written
atomically when complete; interrupted cells are discarded. The rules are those
of the collection plan in experiments/calibration/c1-config.json.

    python3 collector.py init    --data DIR --c1tool BIN [--cast BIN]
    python3 collector.py run     --data DIR
    python3 collector.py status  --data DIR
    python3 collector.py verify  --data DIR [--deep]
    python3 collector.py stop    --data DIR --reason TEXT
    python3 collector.py release --data DIR --reason TEXT
    python3 collector.py archive --data DIR --to DEST

The collector never reads a judgment record after writing it and never prints
or logs a judgment outcome. See README.md for operation.
"""
import argparse
import base64
import datetime
import decimal
import errno
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

FORMAT_COLLECTION = 'fairbind/experimental/c1-collection/v1'
FORMAT_STATE = 'fairbind/experimental/c1-collector-state/v1'
FORMAT_CELL = 'fairbind/experimental/c1-cell/v1'
FORMAT_CONTROLLER = 'fairbind/experimental/c1-controller/v1'
FORMAT_DISCARD = 'fairbind/experimental/c1-discarded-cell/v1'
REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO / 'experiments' / 'calibration' / 'c1-config.json'

SELLERS = ['bitstamp:ticker:btcusd', 'gemini:pubticker:btcusd']
REFERENCES = ['coinbase-exchange:ticker:BTC-USD', 'kraken:ticker:XBTUSD']
TRUTH = 'bitfinex:trades:tBTCUSD'
END_REASONS = ('machine_sleep', 'network', 'user_stop', '429_rule', 'collection_complete', 'other')

decimal.getcontext().prec = 200


# ----------------------------------------------------------------------------
# Small utilities


def utcnow_iso(t=None):
    t = time.time() if t is None else t
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).isoformat(timespec='milliseconds')


def sha256_hex(b):
    return hashlib.sha256(b).hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':')).encode()


def fsync_dir(path):
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_atomic(path, data):
    """Temporary file in the same directory, fsync, rename, fsync directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f'.tmp-{path.name}-{os.getpid()}'
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fsync_dir(path.parent)


def write_json_atomic(path, obj):
    write_atomic(path, json.dumps(obj, indent=1, sort_keys=True).encode() + b'\n')


def normalize_decimal(d):
    """Plain decimal string: no sign, exponent, leading or trailing zeros."""
    if not isinstance(d, decimal.Decimal):
        d = decimal.Decimal(d)
    if d < 0 or not d.is_finite():
        raise ValueError('negative or non-finite decimal')
    s = format(d, 'f')
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    s = s.lstrip('0') or '0'
    if s.startswith('.'):
        s = '0' + s
    return s


def exponent_form(price):
    """The same value in lowercase e notation with a one-digit integer part."""
    d = decimal.Decimal(price)
    sign, digits, exp = d.normalize().as_tuple()
    ds = ''.join(map(str, digits))
    e = len(ds) - 1 + exp
    mant = ds[0] + ('.' + ds[1:] if len(ds) > 1 else '')
    return f'{mant}e{e}'


def body_json(price):
    return json.dumps({'price': price}, separators=(',', ':')).encode()


# ----------------------------------------------------------------------------
# Seeded values


class Seeds:
    """Seeded values depend only on the base seed, the grid time and an ID."""

    PREFIX = 'fairbind/c1-collect/v1'

    def __init__(self, seed):
        self.seed = int(seed)

    def h(self, label, t, source_id):
        m = f'{self.PREFIX}|{self.seed}|{label}|{int(t)}|{source_id}'.encode()
        return int.from_bytes(hashlib.sha256(m).digest(), 'big')

    def base_instance(self, t, seller):
        return 1 + self.h('base-instance', t, seller) % 3

    def sigma(self, t, seller):
        return 1 if self.h('sigma', t, seller) % 2 == 0 else -1

    def reference_order(self, t, instance):
        return sorted(REFERENCES, key=lambda r: (self.h(f'reference-order/instance-{instance}', t, r), r))

    def slots(self, t, n=3):
        """Slot index (0-based) of each instance 1..n: a seeded permutation."""
        order = sorted(range(1, n + 1), key=lambda i: (self.h('slot', t, f'instance-{i}'), i))
        return {inst: k for k, inst in enumerate(order)}

    def jitter_ms(self, t, instance, span):
        return self.h('offset-jitter', t, f'instance-{instance}') % span

    def response_id(self, t, seller):
        return format(self.h('response-id', t, seller), '064x')[:32]

    def _uniform(self, label, i, n):
        limit = (1 << 256) // n * n
        k = 0
        while True:
            m = f'{self.PREFIX}|{self.seed}|list|{label}|{i}|{k}'.encode()
            x = int.from_bytes(hashlib.sha256(m).digest(), 'big')
            if x < limit:
                return x % n
            k += 1

    def shuffle(self, items, label):
        a = list(items)
        for i in range(len(a) - 1, 0, -1):
            j = self._uniform(label, i, i + 1)
            a[i], a[j] = a[j], a[i]
        return a


def type_strata(cfg):
    out = []
    for g in cfg['data_api']['wrong_answer_generators']:
        for s in g['strata']:
            out.append(s)
    return out


def build_lists(cfg):
    col = cfg['collection']
    seeds = Seeds(col['seed'])
    roles = {}
    for src in SELLERS:
        items = ['honest'] * col['role_list']['honest'] + ['wrong'] * col['role_list']['wrong']
        roles[src] = seeds.shuffle(items, f'roles/{src}')
    types = []
    for s in type_strata(cfg):
        types += [s['type']] * s['count']
    types = seeds.shuffle(types, 'types')
    lists = {'roles': roles, 'types': types}
    return lists, sha256_hex(canonical(lists))


# ----------------------------------------------------------------------------
# Clocks


class SystemClock:
    """Wall time plus a clock that runs during suspend and one that stops."""

    def __init__(self):
        if sys.platform.startswith('linux'):
            self._run, self._stop = time.CLOCK_BOOTTIME, time.CLOCK_MONOTONIC
        elif sys.platform == 'darwin':
            # Darwin: CLOCK_MONOTONIC continues during sleep, CLOCK_UPTIME_RAW stops.
            self._run, self._stop = time.CLOCK_MONOTONIC, time.CLOCK_UPTIME_RAW
        else:
            raise SystemExit('unsupported platform for sleep detection: ' + sys.platform)

    def now(self):
        return time.time()

    def running(self):
        return time.clock_gettime(self._run)

    def stopping(self):
        return time.clock_gettime(self._stop)

    def sleep(self, s):
        if s > 0:
            time.sleep(s)


class ClockMark:
    def __init__(self, clock):
        self.clock = clock
        self.run0, self.stop0 = clock.running(), clock.stopping()

    def divergence(self):
        return abs((self.clock.running() - self.run0) - (self.clock.stopping() - self.stop0))


def boot_id():
    try:
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        pass
    try:
        out = subprocess.run(['sysctl', '-n', 'kern.boottime'], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# ----------------------------------------------------------------------------
# Lock


class Lock:
    def __init__(self, data):
        self.path = Path(data) / 'lock'
        self.fd = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(fd)
            if e.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                return False
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f'{os.getpid()}\n'.encode())
        self.fd = fd
        return True

    def release(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def held_by_other(self):
        if not self.path.exists():
            return False
        fd = os.open(str(self.path), os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            return True
        finally:
            os.close(fd)
        return False


# ----------------------------------------------------------------------------
# Backend: the real one runs c1tool; tests substitute a fake.


class ToolFailure(Exception):
    pass


class ToolBackend:
    def __init__(self, c1tool, cast, roots=None, timeout=10):
        self.c1tool, self.cast, self.roots, self.timeout = c1tool, cast, roots, timeout

    def _common(self, d, log):
        a = ['-dir', str(d), '-log', str(log), '-timeout', f'{self.timeout}s']
        if self.roots:
            a += ['-roots', self.roots]
        return a

    def _json(self, proc_out, what):
        try:
            return json.loads(proc_out.decode().strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise ToolFailure(f'{what}: no result')

    def start_captures(self, role, sources, d, log):
        cmd = [self.c1tool, 'capture', '-role', role, '-sources', ','.join(sources)] + self._common(d, log)
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)

    def finish_captures(self, proc, what):
        try:
            out, err = proc.communicate(timeout=self.timeout * 4 + 10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise ToolFailure(f'{what}: timeout')
        if proc.returncode != 0:
            raise ToolFailure(f'{what}: exit {proc.returncode}: {err.decode(errors="replace")[-300:]}')
        return self._json(out, what)['captures']

    def bundle(self, t, responses):
        payload = json.dumps({'reference_time': t, 'responses': [
            {'response_id': r['response_id'], 'body': base64.b64encode(r['body']).decode()} for r in responses]}).encode()
        p = subprocess.run([self.c1tool, 'bundle', '-cast', self.cast], input=payload, capture_output=True, timeout=60)
        if p.returncode != 0:
            raise ToolFailure(f'bundle: exit {p.returncode}: {p.stderr.decode(errors="replace")[-300:]}')
        return p.stdout

    def start_instance(self, plan, d, log, stderr_path):
        cmd = [self.c1tool, 'instance', '-plan', json.dumps(plan, separators=(',', ':')), '-cast', self.cast] + self._common(d, log)
        err = open(stderr_path, 'wb')
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err)
        err.close()
        return p

    def finish_instance(self, proc, cases, timeout):
        """Returns (record_bytes, record) or raises ToolFailure."""
        try:
            out, _ = proc.communicate(input=cases, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise ToolFailure('instance: timeout')
        except BrokenPipeError:
            proc.wait()
            raise ToolFailure(f'instance: exit {proc.returncode} before cases')
        if proc.returncode != 0:
            raise ToolFailure(f'instance: exit {proc.returncode}')
        line = out.strip().splitlines()[-1] if out.strip() else b''
        try:
            return line + b'\n', json.loads(line)
        except ValueError:
            raise ToolFailure('instance: malformed record')

    def abort_instance(self, proc):
        if proc.poll() is None:
            proc.kill()
        try:
            proc.communicate(timeout=5)
        except (subprocess.SubprocessError, ValueError, OSError):
            pass

    def truth(self, t, d, log):
        cmd = [self.c1tool, 'truth', '-reference-time', str(t)] + self._common(d, log)
        p = subprocess.run(cmd, capture_output=True, timeout=self.timeout * 60 + 30)
        if p.returncode != 0:
            raise ToolFailure(f'truth: exit {p.returncode}')
        return self._json(p.stdout, 'truth')


# ----------------------------------------------------------------------------
# State


class Stop(Exception):
    """Ends the run loop with a session end reason."""

    def __init__(self, reason, note=''):
        super().__init__(reason)
        self.reason, self.note = reason, note


class Signalled(Exception):
    pass


def new_state(cfg, lists_sha):
    return {
        'format': FORMAT_STATE,
        'lists_sha256': lists_sha,
        'last_complete_t': None,
        'complete_cells': 0,
        'discarded_cells': 0,
        'discarded_by_reason': {},
        'role_pos': {s: 0 for s in SELLERS},
        'type_pos': 0,
        'deferred': [],
        'honest': {s: 0 for s in SELLERS},
        'wrong': {s: 0 for s in SELLERS},
        'types_assigned': 0,
        'unused': {s: {} for s in SELLERS},
        'successes': {s: {} for s in SELLERS},
        'adaptive': {'delta': cfg['collection']['adaptive']['delta_initial'], 'set_by_t': None, 'set_by_session': None,
                     'initial_used': False, 'last_response_t': None},
        'rate_limit': {'consecutive': {}, 'skip_next': []},
        'requests': {'complete_cells': 0, 'discarded_cells': 0, 'truth': 0, 'truth_split_pages': 0},
        'availability': {},
        'skipped_429': {},
        'sessions': [],
        'current_session': None,
        'open_cell': None,
        'stopped': None,
        'hold': None,
        'boot_id': None,
    }


class Collector:
    def __init__(self, data, backend, clock, out=None):
        self.data = Path(data)
        self.backend, self.clock = backend, clock
        self.out = out or sys.stdout
        self.collection = json.loads((self.data / 'collection.json').read_text())
        self.cfg = self.collection['config']
        col = self.cfg['collection']
        self.col = col
        self.seeds = Seeds(col['seed'])
        self.lists, sha = build_lists(self.cfg)
        if sha != self.collection['lists_sha256']:
            raise SystemExit('seeded lists differ from the lists fixed at init')
        self.grid = col['grid_seconds']
        self.skew = col['max_skew_seconds']
        self.state = self._load_state()
        self.process_started = self.clock.now()
        self.stop_requested = None

    # -- persistence ---------------------------------------------------------

    @property
    def state_path(self):
        return self.data / 'state.json'

    def _load_state(self):
        if self.state_path.exists():
            st = json.loads(self.state_path.read_text())
        else:
            st = new_state(self.cfg, self.collection['lists_sha256'])
        # A cell renamed into place after the last state write carries the
        # state it completed; adopt the newest such cell.
        last = st['last_complete_t']
        for t, d in self._cell_dirs():
            if last is None or t > last:
                man = json.loads((d / 'manifest.json').read_text())
                st = man['state_after']
                last = t
        return st

    def save(self):
        write_json_atomic(self.state_path, self.state)

    def _cell_dirs(self):
        root = self.data / 'cells'
        out = []
        if root.exists():
            for day in sorted(root.iterdir()):
                if not day.is_dir():
                    continue
                for c in day.iterdir():
                    if c.is_dir() and c.name.isdigit() and (c / 'manifest.json').exists():
                        out.append((int(c.name), c))
        return sorted(out)

    def cell_dir(self, t):
        day = datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime('%Y-%m-%d')
        return self.data / 'cells' / day / str(t)

    def log(self, msg):
        line = f'{utcnow_iso(self.clock.now())} {msg}'
        p = self.data / 'log' / 'collector.log'
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, 'a') as f:
            f.write(line + '\n')
        print(line, file=self.out, flush=True)

    # -- sessions ------------------------------------------------------------

    def _open_session(self, t):
        st = self.state
        n = len(st['sessions']) + 1
        st['current_session'] = {'id': n, 'process_started_at': utcnow_iso(self.process_started),
                                 'started_at': utcnow_iso(self.clock.now()), 'first_opened_t': t,
                                 'first_complete_t': None, 'last_complete_t': None,
                                 'complete_cells': 0, 'discarded_cells': 0, 'http_requests': 0}

    def end_session(self, reason, note='', process_end=False, at=None):
        st = self.state
        s = st['current_session']
        if s is None:
            return
        assert reason in END_REASONS, reason
        s['ended_at'] = utcnow_iso(self.clock.now() if at is None else at)
        s['process_ended_at'] = s['ended_at'] if process_end else None
        s['end_reason'] = reason
        s['end_note'] = note
        st['sessions'].append(s)
        st['current_session'] = None
        self.save()
        self.log(f'session {s["id"]} ended: {reason}{(" (" + note + ")") if note else ""}; '
                 f'complete {s["complete_cells"]}, discarded {s["discarded_cells"]}')

    # -- recovery at start ---------------------------------------------------

    def recover(self):
        st = self.state
        bid = boot_id()
        if st['open_cell'] is not None:
            t = st['open_cell']['t']
            if st['last_complete_t'] is not None and t <= st['last_complete_t']:
                st['open_cell'] = None
            else:
                self.discard(t, 'interrupted', 'process ended inside the cell', work=self.data / 'work' / str(t))
        if st['current_session'] is not None:
            note = 'process ended without a session record (killed or crashed)'
            if st.get('boot_id') and bid and bid != st['boot_id']:
                note = 'machine restarted while the collector ran'
            self.end_session('other', note, process_end=True, at=self._last_activity())
        st['boot_id'] = bid
        # Leftover work directories of cells that are complete or discarded.
        work = self.data / 'work'
        if work.exists():
            for d in work.iterdir():
                if d.name.isdigit():
                    t = int(d.name)
                    dest = self.data / 'discarded' / f'{t}.work'
                    if not dest.exists():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(d, dest)
                    else:
                        shutil.rmtree(d)
        self.save()

    def _last_activity(self):
        p = self.data / 'log' / 'collector.log'
        try:
            return p.stat().st_mtime
        except OSError:
            return self.clock.now()

    # -- targets -------------------------------------------------------------

    def total_types(self):
        return len(self.lists['types'])

    def targets_met(self):
        st = self.state
        return all(st['honest'][s] >= self.col['role_list']['honest'] for s in SELLERS) and \
            st['types_assigned'] >= self.total_types()

    def check_stop_conditions(self):
        st = self.state
        if self.targets_met():
            raise Stop('collection_complete', 'targets reached')
        if st['complete_cells'] >= self.col['max_cells']:
            raise Stop('collection_complete', f'{self.col["max_cells"]} complete cells')

    # -- scheduling ----------------------------------------------------------

    def next_grid_time(self, now):
        g = self.grid
        t = (int(now) // g + 1) * g
        while t - now <= self.skew:
            t += g
        last = self.state['last_complete_t']
        if last is not None and t <= last:
            t = last + g
        return t

    def run(self):
        """Main loop. Returns the end reason."""
        self.recover()
        st = self.state
        if st['stopped']:
            self.log(f'collection is stopped ({st["stopped"]["reason"]}); nothing to do')
            return st['stopped']['reason']
        if st['hold']:
            self.log('collection is on hold (user stop); run `release` to continue')
            return 'user_stop'
        try:
            while True:
                self.check_stop_conditions()
                self.check_hold()
                t = self.next_grid_time(self.clock.now())
                launch = t - self.col['instance_launch_lead_seconds']
                if not self.wait_until(launch):
                    continue  # suspended while waiting: choose the grid time again
                if self.clock.now() - launch > 1.0:
                    continue  # overslept: this grid time stays unopened
                self.run_cell(t)
        except Stop as s:
            st = self.state  # complete() replaces the state object
            if s.reason in ('collection_complete', '429_rule'):
                st['stopped'] = {'reason': s.reason, 'note': s.note, 'at': utcnow_iso(self.clock.now())}
            if s.reason == 'user_stop':
                st['hold'] = {'reason': s.note, 'at': utcnow_iso(self.clock.now())}
            self.end_session(s.reason, s.note, process_end=True)
            self.save()
            self.log(f'collector stopped: {s.reason}')
            return s.reason
        except Signalled as s:
            st = self.state
            if st['open_cell'] is not None:
                t = st['open_cell']['t']
                self.discard(t, 'interrupted', f'terminated by signal {s}', work=self.data / 'work' / str(t))
            self.end_session('other', f'terminated by signal {s}', process_end=True)
            return 'other'

    def check_hold(self):
        p = self.data / 'stop-request.json'
        if p.exists():
            req = json.loads(p.read_text())
            p.unlink()
            raise Stop('user_stop', req.get('reason', ''))
        if self.stop_requested:
            raise Signalled(self.stop_requested)

    def wait_until(self, target):
        """Sleep until target in short steps, doing truth lookups when time
        allows. A suspend while waiting ends the current session and returns
        False."""
        while True:
            now = self.clock.now()
            if now >= target:
                return True
            self.check_hold()
            if self.truth_step(deadline=target):
                continue
            step = min(5.0, target - now)
            mark = ClockMark(self.clock)
            self.clock.sleep(step)
            if mark.divergence() > self.col['sleep_divergence_seconds']:
                self.log('suspend detected while waiting')
                self.end_session('machine_sleep', 'suspend between cells')
                return False

    # -- one cell ------------------------------------------------------------

    def instance_plans(self, t):
        sched = self.col['instance_schedule']
        slots = self.seeds.slots(t)
        skip = [s for s in self.state['rate_limit']['skip_next'] if s in REFERENCES]
        plans = {}
        for i in (1, 2, 3):
            off_ms = sched['slot_offsets_seconds'][slots[i]] * 1000 + self.seeds.jitter_ms(t, i, sched['jitter_ms'])
            plans[i] = {'reference_time': t, 'instance': i, 'start_unix_ms': t * 1000 + off_ms,
                        'order': self.seeds.reference_order(t, i), 'skip': skip}
        return plans

    def run_cell(self, t):
        st = self.state
        if st['current_session'] is None:
            self._open_session(t)
        work = self.data / 'work' / str(t)
        if work.exists():
            shutil.rmtree(work)
        (work / 'seller').mkdir(parents=True)
        reqlog = work / 'requests.log'
        reqlog.touch()
        st['open_cell'] = {'t': t, 'opened_at': utcnow_iso(self.clock.now()), 'session': st['current_session']['id']}
        self.save()
        mark = ClockMark(self.clock)
        opened = self.clock.now()
        plans = self.instance_plans(t)
        skip_next = list(st['rate_limit']['skip_next'])
        procs = {}
        try:
            for i, plan in plans.items():
                d = work / f'instance-{i}'
                d.mkdir()
                procs[i] = self.backend.start_instance(plan, d, reqlog, work / f'instance-{i}.stderr')
            # Seller captures at the grid time, both sources at once.
            self.sleep_until(t)
            seller_skip = [s for s in SELLERS if s in skip_next]
            running = {s: self.backend.start_captures('seller', [s], work / 'seller', reqlog)
                       for s in SELLERS if s not in seller_skip}
            sellers = {}
            for s in SELLERS:
                if s in running:
                    sellers[s] = self.backend.finish_captures(running[s], s)[0]
                else:
                    sellers[s] = {'source_id': s, 'stage': 'skipped_429'}
            ctl = self.assign(t, sellers, work, reqlog, skip_next)
            responses = ctl.pop('_responses')
            cases = self.backend.bundle(t, responses)
            timeout = max(30.0, t + 120 - self.clock.now())
            records = {}
            for i in (1, 2, 3):
                records[i] = self.backend.finish_instance(procs.pop(i), cases, timeout)
                self.check_record(records[i][1], t, i, responses)
        except ToolFailure as e:
            for p in procs.values():
                self.backend.abort_instance(p)
            self.discard(t, 'other', f'tool failure: {e}', work=work, rate=None)
            self.end_session('other', f'tool failure in cell {t}')
            return
        except BaseException:
            for p in procs.values():
                try:
                    self.backend.abort_instance(p)
                except Exception:
                    pass
            raise
        finished = self.clock.now()
        # Requests of this cell in time order, for the network and 429 rules.
        reqs = self.cell_requests(sellers, ctl, records)
        if mark.divergence() > self.col['sleep_divergence_seconds']:
            self.discard(t, 'machine_sleep', f'clock divergence {mark.divergence():.3f} s', work=work, rate=reqs)
            self.end_session('machine_sleep', f'suspend inside cell {t}')
            return
        if reqs and all(r['stage'] == 'connect' for r in reqs):
            self.discard(t, 'network', 'every request failed at the connection stage', work=work, rate=reqs)
            self.end_session('network', f'no HTTP response in cell {t}')
            return
        self.complete(t, work, sellers, ctl, records, reqs, opened, finished, plans)

    @staticmethod
    def check_record(rec, t, i, responses):
        """Structural check only; no decision is inspected here."""
        plan = rec.get('plan') or {}
        if rec.get('format') != 'fairbind/experimental/c1-judgment/v1' or plan.get('reference_time') != t or plan.get('instance') != i:
            raise ToolFailure(f'instance {i}: record does not belong to the cell')
        ids = [j.get('response_id') for j in rec.get('judgments') or []]
        if ids != [r['response_id'] for r in responses]:
            raise ToolFailure(f'instance {i}: judgments do not match the cell responses')
        if any(j.get('error') for j in rec['judgments']):
            raise ToolFailure(f'instance {i}: a response could not be judged')

    def sleep_until(self, target):
        while True:
            d = target - self.clock.now()
            if d <= 0:
                return
            self.clock.sleep(min(d, 1.0))

    # -- assignment ----------------------------------------------------------

    def stale_back(self, typ):
        for g in self.cfg['data_api']['wrong_answer_generators']:
            for s in g['strata']:
                if s['type'] == typ:
                    return s.get('cells_back')
        return None

    def eligible(self, st, typ, src, t, no_adaptive):
        back = self.stale_back(typ)
        if back is not None:
            return str(t - back * self.grid) in st['successes'][src]
        if typ == 'D-adaptive' and no_adaptive:
            return False
        return True

    def next_type(self, st, src, t, no_adaptive=False):
        for k, d in enumerate(st['deferred']):
            if self.eligible(st, d, src, t, no_adaptive):
                st['deferred'].pop(k)
                return d, 'deferred'
        types = self.lists['types']
        while st['type_pos'] < len(types):
            d = types[st['type_pos']]
            st['type_pos'] += 1
            if self.eligible(st, d, src, t, no_adaptive):
                return d, 'list'
            st['deferred'].append(d)
        return None, None

    def stratum(self, typ):
        for s in type_strata(self.cfg):
            if s['type'] == typ:
                return s
        raise KeyError(typ)

    def assign(self, t, sellers, work, reqlog, skip_next):
        """Consumes the lists on a copy of the state; the copy becomes the
        state only if the cell completes."""
        st = json.loads(json.dumps(self.state))
        tol = decimal.Decimal(self.cfg['data_api']['relative_tolerance'])
        ctl = {'format': FORMAT_CONTROLLER, 'reference_time': t, 'captures': [], 'generator': None,
               'seeded': {'sigma': {}, 'base_instance': {}}}
        responses = []
        generator = None  # (median or None, summaries), captured once per cell
        for src in SELLERS:
            cap = sellers[src]
            sig, base = self.seeds.sigma(t, src), self.seeds.base_instance(t, src)
            ctl['seeded']['sigma'][src], ctl['seeded']['base_instance'][src] = sig, base
            entry = {'source_id': src, 'capture': cap, 'role': None, 'type': None}
            ctl['captures'].append(entry)
            if cap.get('stage') != 'ok':
                continue
            price = cap['value']
            if st['role_pos'][src] < len(self.lists['roles'][src]):
                role = self.lists['roles'][src][st['role_pos'][src]]
                entry['role_list_index'] = st['role_pos'][src]
                st['role_pos'][src] += 1
            else:
                role = 'wrong'
                entry['role_list_index'] = None
            entry['role'] = role
            st['successes'][src][str(t)] = price
            if role == 'honest':
                st['honest'][src] += 1
                body = body_json(price)
            else:
                no_adaptive = generator is not None and generator[0] is None
                typ, origin = self.next_type(st, src, t, no_adaptive)
                if typ == 'D-adaptive' and generator is None:
                    generator = self.run_generator(work, reqlog, skip_next)
                    ctl['generator'] = generator[1]
                    if generator[0] is None:
                        st['deferred'].insert(0, typ)
                        entry['adaptive_deferred'] = True
                        typ, origin = self.next_type(st, src, t, no_adaptive=True)
                if typ is None:
                    reason = 'targets_met' if st['type_pos'] >= len(self.lists['types']) and not st['deferred'] \
                        else 'no_assignable_type'
                    st['unused'][src][reason] = st['unused'][src].get(reason, 0) + 1
                    entry['unused'] = reason
                    continue
                st['wrong'][src] += 1
                st['types_assigned'] += 1
                entry['type'], entry['type_origin'] = typ, origin
                body = self.wrong_body(st, entry, typ, src, t, price, sig, tol, generator)
            rid = self.seeds.response_id(t, src)
            entry['response_id'] = rid
            entry['response'] = body.decode()
            responses.append({'response_id': rid, 'body': body})
        ctl['_state_after'] = st
        ctl['_responses'] = responses
        return ctl

    def run_generator(self, work, reqlog, skip_next):
        d = work / 'generator'
        d.mkdir(exist_ok=True)
        srcs = [r for r in REFERENCES if r not in skip_next]
        caps = []
        if srcs:
            caps = self.backend.finish_captures(self.backend.start_captures('generator', srcs, d, reqlog), 'generator')
        caps += [{'source_id': r, 'stage': 'skipped_429'} for r in REFERENCES if r in skip_next]
        vals = sorted(decimal.Decimal(c['value']) for c in caps if c.get('stage') == 'ok' and c.get('value'))
        if not vals:
            return None, caps
        n = len(vals)
        med = (vals[(n - 1) // 2] + vals[n // 2]) / 2
        return med, caps

    def wrong_body(self, st, entry, typ, src, t, price, sig, tol, generator):
        p = decimal.Decimal(price)
        s = self.stratum(typ)
        if typ.startswith('D-perturb') or typ.startswith('D-near'):
            m = decimal.Decimal(s['m'])
            entry['params'] = {'m': s['m'], 'sigma': sig}
            return body_json(normalize_decimal(p * (1 + sig * m * tol)))
        if typ.startswith('D-stale'):
            earlier = t - s['cells_back'] * self.grid
            old = st['successes'][src][str(earlier)]
            entry['params'] = {'earlier_t': earlier, 'earlier_price': old, 'current_price': price}
            return body_json(old)
        if typ == 'D-unit':
            entry['params'] = {'factor': s['factor']}
            return body_json(normalize_decimal(p * decimal.Decimal(s['factor'])))
        if typ == 'D-format/missing':
            return b'{}'
        if typ == 'D-format/exponent':
            return body_json(exponent_form(price))
        if typ == 'D-adaptive':
            a = st['adaptive']
            delta = decimal.Decimal(a['delta'])
            med = generator[0]
            entry['params'] = {'sigma': sig, 'delta': a['delta'], 'estimated_median': normalize_decimal(med),
                               'delta_set_by_t': a['set_by_t'], 'delta_is_initial': a['set_by_t'] is None,
                               'previous_adaptive_t': a['last_response_t'],
                               'feedback_skipped_response': a['set_by_t'] is not None and a['set_by_t'] != a['last_response_t'],
                               'feedback_crossed_session': a['set_by_session'] is not None and
                               a['set_by_session'] != self.state['current_session']['id']}
            if a['set_by_t'] is None:
                a['initial_used'] = True
            a['last_response_t'] = t
            return body_json(normalize_decimal(med * (1 + sig * tol * (1 + delta))))
        raise KeyError(typ)

    # -- completion ----------------------------------------------------------

    def cell_requests(self, sellers, ctl, records):
        reqs = []
        for s in SELLERS:
            c = sellers[s]
            if c.get('stage') != 'skipped_429':
                reqs.append(c)
        for c in (ctl.get('generator') or []):
            if c.get('stage') != 'skipped_429':
                reqs.append(c)
        for i in (1, 2, 3):
            for c in records[i][1].get('captures', []):
                if c.get('stage') != 'skipped_429':
                    reqs.append(c)
        return sorted(reqs, key=lambda c: (c.get('finished_unix_ms') or 0, c['source_id']))

    def apply_rate_limit(self, st, reqs, t):
        rl = st['rate_limit']
        rl['skip_next'] = []
        hit = []
        for r in reqs:
            src = r['source_id']
            if r.get('stage') in ('ok', 'invalid', 'response') and r.get('http_status'):
                if r['http_status'] == 429:
                    rl['consecutive'][src] = rl['consecutive'].get(src, 0) + 1
                    if src not in rl['skip_next']:
                        rl['skip_next'].append(src)
                    if rl['consecutive'][src] >= self.col['rate_limit']['stop_after_consecutive']:
                        hit.append(src)
                else:
                    rl['consecutive'][src] = 0
        for s in rl['skip_next']:
            self.log(f'HTTP 429 from {s}: its next cell is skipped')
        return hit

    def availability(self, st, reqs):
        av = st['availability']
        for r in reqs:
            a = av.setdefault(r['source_id'], {'attempts': 0, 'ok': 0})
            a['attempts'] += 1
            if r.get('stage') == 'ok' and r.get('http_status') == 200:
                a['ok'] += 1

    def complete(self, t, work, sellers, ctl, records, reqs, opened, finished, plans):
        st = ctl.pop('_state_after')
        st['open_cell'] = None
        # D-adaptive feedback: the base instance's decision, in seller order.
        a = st['adaptive']
        col = self.col['adaptive']
        for e in ctl['captures']:
            if e.get('type') != 'D-adaptive':
                continue
            base = ctl['seeded']['base_instance'][e['source_id']]
            v = next(j['verdict'] for j in records[base][1]['judgments'] if j['response_id'] == e['response_id'])
            d = decimal.Decimal(a['delta'])
            d = d / 2 if v == 'FAIL' else d * 2
            d = min(max(d, decimal.Decimal(col['delta_min'])), decimal.Decimal(col['delta_max']))
            a['delta'] = normalize_decimal(d)
            a['set_by_t'] = t
            a['set_by_session'] = st['current_session']['id']
        hit = self.apply_rate_limit(st, reqs, t)
        self.availability(st, reqs)
        for s in SELLERS:
            if sellers[s].get('stage') == 'skipped_429':
                st['skipped_429'][s] = st['skipped_429'].get(s, 0) + 1
        # Keep only the successes a later D-stale can use.
        horizon = t - max(s.get('cells_back') or 0 for s in type_strata(self.cfg)) * self.grid
        for s in SELLERS:
            st['successes'][s] = {k: v for k, v in st['successes'][s].items() if int(k) >= horizon}
        nreq = self.count_requests(work)
        st['requests']['complete_cells'] += nreq
        sess = st['current_session']
        sess['complete_cells'] += 1
        sess['http_requests'] += nreq
        sess['last_complete_t'] = t
        if sess['first_complete_t'] is None:
            sess['first_complete_t'] = t
        st['complete_cells'] += 1
        st['last_complete_t'] = t
        truth_needed = any((e.get('type') or '').startswith(('D-near', 'D-adaptive')) for e in ctl['captures'])
        ctl['truth_lookup_queued'] = truth_needed
        ctl['timing'] = {'opened_at': utcnow_iso(opened), 'finished_at': utcnow_iso(finished)}
        ctl['instance_plans'] = plans
        ctl['http_requests'] = nreq
        files = {}
        write_json_atomic(work / 'controller.json', ctl)
        for i in (1, 2, 3):
            raw = records[i][0]
            write_atomic(work / f'instance-{i}' / 'judgment.json', raw)
            files[f'instance-{i}/judgment.json'] = {'sha256': sha256_hex(raw), 'bytes': len(raw)}
        for p in sorted(work.rglob('*')):
            if p.is_file():
                rel = p.relative_to(work).as_posix()
                if rel not in files:
                    b = p.read_bytes()
                    files[rel] = {'sha256': sha256_hex(b), 'bytes': len(b)}
        manifest = {'format': FORMAT_CELL, 'reference_time': t, 'session': sess['id'], 'files': files,
                    'state_after': st}
        write_json_atomic(work / 'manifest.json', manifest)
        dest = self.cell_dir(t)
        if dest.exists():
            raise SystemExit(f'cell {t} already complete; refusing to complete it twice')
        dest.parent.mkdir(parents=True, exist_ok=True)
        fsync_dir(work)
        os.replace(work, dest)
        fsync_dir(dest.parent)
        self.state = st
        self.save()
        if truth_needed:
            self.truth_enqueue(t)
        self.log(f'cell {t} complete ({nreq} requests, {finished - opened:.1f} s); ' + self.progress_line())
        if hit:
            raise Stop('429_rule', 'three consecutive HTTP 429 from ' + ','.join(hit))

    def count_requests(self, work):
        try:
            with open(work / 'requests.log') as f:
                return sum(1 for _ in f)
        except OSError:
            return 0

    def discard(self, t, reason, note, work=None, rate=None):
        st = self.state
        nreq = self.count_requests(work) if work else 0
        rec = {'format': FORMAT_DISCARD, 'reference_time': t, 'reason': reason, 'note': note,
               'http_requests': nreq, 'recorded_at': utcnow_iso(self.clock.now()),
               'session': (st['current_session'] or {}).get('id')}
        dest = self.data / 'discarded'
        dest.mkdir(parents=True, exist_ok=True)
        if work is not None and work.exists():
            # Keep raw objects for audit; no judgment record is kept for a discarded cell.
            for j in work.glob('instance-*/judgment.json'):
                j.unlink()
            target = dest / f'{t}.work'
            if target.exists():
                shutil.rmtree(target)
            os.replace(work, target)
        write_json_atomic(dest / f'{t}.json', rec)
        if rate:
            hit = self.apply_rate_limit(st, rate, t)
        else:
            # The skip, if any, was applied in this opened cell.
            st['rate_limit']['skip_next'] = []
            hit = []
        st['discarded_cells'] += 1
        st['discarded_by_reason'][reason] = st['discarded_by_reason'].get(reason, 0) + 1
        st['requests']['discarded_cells'] += nreq
        if st['current_session'] is not None:
            st['current_session']['discarded_cells'] += 1
            st['current_session']['http_requests'] += nreq
        st['open_cell'] = None
        self.save()
        self.log(f'cell {t} discarded: {reason} ({note}); {nreq} requests')
        if hit:
            raise Stop('429_rule', 'three consecutive HTTP 429 from ' + ','.join(hit))

    # -- truth lookups -------------------------------------------------------

    @property
    def truth_path(self):
        return self.data / 'truth' / 'queue.json'

    def truth_queue(self):
        if self.truth_path.exists():
            return json.loads(self.truth_path.read_text())
        return {'items': []}

    def truth_enqueue(self, t):
        q = self.truth_queue()
        if any(i['reference_time'] == t for i in q['items']):
            return
        # The window runs to reference_time + max_skew; the first lookup waits
        # until it has closed and the exchange has had time to publish it.
        first = t + self.skew + self.col['truth_lookup']['settle_seconds']
        q['items'].append({'reference_time': t, 'attempts': [], 'next_due': max(self.clock.now(), first),
                           'done': False})
        write_json_atomic(self.truth_path, q)

    def truth_step(self, deadline):
        """Runs one due lookup if it fits before deadline. Returns True if it ran."""
        cfg = self.col['truth_lookup']
        if not self.collection.get('truth_lookups_enabled', True):
            return False
        now = self.clock.now()
        if deadline - now < cfg['reserve_seconds']:
            return False
        q = self.truth_queue()
        rl = self.state['rate_limit']
        if now < rl.get('truth_skip_until', 0):
            return False
        # Keep lookups apart so a backlog after an interruption stays well
        # under the truth host's public limit.
        if now - rl.get('truth_last_lookup', 0) < cfg['min_interval_seconds']:
            return False
        due =[i for i in q['items'] if not i['done'] and i['next_due'] <= now]
        if not due:
            return False
        item = min(due, key=lambda i: i['reference_time'])
        t = item['reference_time']
        n = len(item['attempts']) + 1
        d = self.data / 'truth' / str(t)
        d.mkdir(parents=True, exist_ok=True)
        log = d / 'requests.log'
        before = self.count_requests(d) if log.exists() else 0
        started = self.clock.now()
        try:
            res = self.backend.truth(t, d / 'objects', log)
            fail = None if res.get('ok') else (res.get('failure') or 'failed')
        except (ToolFailure, subprocess.SubprocessError, OSError) as e:
            res, fail = None, f'tool failure: {e}'
        nreq = (self.count_requests(d) if log.exists() else 0) - before
        self.state['rate_limit']['truth_last_lookup'] = self.clock.now()
        if res is not None:
            write_json_atomic(d / f'attempt-{n}.json', res)
        item['attempts'].append({'n': n, 'at': utcnow_iso(started), 'ok': fail is None, 'failure': fail,
                                 'requests': nreq, 'file': f'attempt-{n}.json' if res is not None else None})
        st = self.state
        st['requests']['truth'] += nreq
        st['requests']['truth_split_pages'] += max(0, nreq - 1)
        pages = (res or {}).get('pages') or []
        self.availability(st, pages)
        hit = []
        if pages:
            hit = self.apply_truth_rate_limit(st, pages)
        if fail is None or n >= cfg['max_attempts']:
            item['done'] = True
            item['result'] = 'ok' if fail is None else 'no_truth'
        else:
            # Retries at 1 min, 11 min and 21 min after the first failure; a
            # lookup delayed by an interruption runs when the collector resumes.
            item.setdefault('first_failure_epoch', started)
            item['next_due'] = item['first_failure_epoch'] + cfg['first_retry_after_seconds'] + \
                cfg['retry_interval_seconds'] * (n - 1)
        write_json_atomic(self.truth_path, q)
        self.save()
        self.log(f'truth lookup for cell {t}: attempt {n}, {nreq} requests')
        if hit:
            raise Stop('429_rule', 'three consecutive HTTP 429 from ' + TRUTH)
        return True

    def apply_truth_rate_limit(self, st, pages):
        rl = st['rate_limit']
        hit = []
        for r in pages:
            if r.get('stage') in ('ok', 'invalid', 'response') and r.get('http_status'):
                if r['http_status'] == 429:
                    rl['consecutive'][TRUTH] = rl['consecutive'].get(TRUTH, 0) + 1
                    rl['truth_skip_until'] = self.clock.now() + self.grid
                    if rl['consecutive'][TRUTH] >= self.col['rate_limit']['stop_after_consecutive']:
                        hit.append(TRUTH)
                else:
                    rl['consecutive'][TRUTH] = 0
        return hit

    # -- display -------------------------------------------------------------

    def progress_line(self):
        st = self.state
        return (f'complete {st["complete_cells"]}, discarded {st["discarded_cells"]}, '
                f'remaining honest {self.remaining_honest()}, remaining wrong-answer types {self.remaining_types()}')

    def remaining_honest(self):
        return {s.split(':')[0]: self.col['role_list']['honest'] - self.state['honest'][s] for s in SELLERS}

    def remaining_types(self):
        return self.total_types() - self.state['types_assigned']


# ----------------------------------------------------------------------------
# Commands


def git_revision():
    try:
        rev = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(['git', 'status', '--porcelain'], cwd=REPO, capture_output=True, text=True,
                                    timeout=30).stdout.strip())
        return rev or None, dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


def file_sha(path):
    return sha256_hex(Path(path).read_bytes())


def tool_identity(c1tool, cast):
    ident = {'c1tool': str(Path(c1tool).resolve()), 'c1tool_sha256': file_sha(c1tool),
             'collector_sha256': file_sha(__file__), 'cast': cast}
    try:
        v = subprocess.run([cast, '--version'], capture_output=True, text=True, timeout=10).stdout
        ident['cast_version'] = v.strip()
    except OSError:
        ident['cast_version'] = None
    return ident


def cmd_init(a):
    data = Path(a.data)
    cfg = json.loads(Path(a.config).read_text())
    lists, lsha = build_lists(cfg)
    rev, dirty = git_revision()
    if dirty and not a.allow_dirty:
        raise SystemExit('the working tree has uncommitted changes; commit them before starting a collection')
    frame = json.loads(subprocess.run([a.c1tool, 'frame'], capture_output=True, text=True, timeout=30).stdout)
    if frame['frame_sha256'] != cfg['data_api']['policy_frame_sha256']:
        raise SystemExit('policy frame hash of c1tool differs from the configuration')
    cast = shutil.which(a.cast) or a.cast
    ident = tool_identity(a.c1tool, cast)
    if not ident.get('cast_version') or 'cast Version: 1.7.1' not in ident['cast_version']:
        raise SystemExit('the pinned cast 1.7.1 build is required (input gate signature check)')
    col = {'format': FORMAT_COLLECTION, 'created_at': utcnow_iso(), 'revision': rev, 'dirty_tree': dirty,
           'config': cfg, 'config_sha256': sha256_hex(canonical(cfg)), 'lists_sha256': lsha,
           'policy_frame_sha256': frame['frame_sha256'], 'tools': ident, 'roots': a.roots,
           'truth_lookups_enabled': not a.no_truth_lookups,
           'upstreams': json.loads((REPO / 'UPSTREAMS.lock.json').read_text()),
           'platform': sys.platform, 'python': sys.version.split()[0]}
    if (data / 'collection.json').exists():
        old = json.loads((data / 'collection.json').read_text())
        if old['config_sha256'] == col['config_sha256'] and old['lists_sha256'] == lsha:
            print(f'{data} is already initialized')
            return 0
        raise SystemExit(f'{data} holds another collection')
    data.mkdir(parents=True, exist_ok=True)
    write_json_atomic(data / 'collection.json', col)
    write_json_atomic(data / 'plan' / 'lists.json', lists)
    print(f'initialized {data}: lists {lsha[:16]}, config {col["config_sha256"][:16]}')
    return 0


def open_collector(data, clock=None, out=None):
    col = json.loads((Path(data) / 'collection.json').read_text())
    tools = col['tools']
    backend = ToolBackend(tools['c1tool'], tools['cast'], col.get('roots'),
                          col['config']['collection']['request_timeout_seconds'])
    return Collector(data, backend, clock or SystemClock(), out), col


def cmd_run(a):
    data = Path(a.data)
    if not (data / 'collection.json').exists():
        raise SystemExit(f'{data} is not initialized')
    lock = Lock(data)
    if not lock.acquire():
        print('collector already running')
        return 0
    try:
        c, col = open_collector(data)
        tools = col['tools']
        if file_sha(tools['c1tool']) != tools['c1tool_sha256'] or file_sha(__file__) != tools['collector_sha256']:
            print('collector or c1tool differs from the version fixed at init; not running', file=sys.stderr)
            return 2

        def on_signal(signum, _frame):
            c.stop_requested = signum
            raise Signalled(signum)
        signal.signal(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGINT, on_signal)
        c.run()
        return 0
    finally:
        lock.release()


def cmd_status(a):
    data = Path(a.data)
    alive = Lock(data).held_by_other()
    st_path = data / 'state.json'
    col = json.loads((data / 'collection.json').read_text())
    cfg = col['config']
    st = json.loads(st_path.read_text()) if st_path.exists() else new_state(cfg, col['lists_sha256'])
    types_total = sum(s['count'] for s in type_strata(cfg))
    print(f'collector: {"running" if alive else "not running"}')
    if st.get('stopped'):
        print(f'stopped: {st["stopped"]["reason"]} ({st["stopped"].get("note", "")})')
    if st.get('hold'):
        print(f'on hold (user stop): {st["hold"]["reason"]}')
    print(f'complete cells: {st["complete_cells"]} of at most {cfg["collection"]["max_cells"]}')
    print(f'discarded cells: {st["discarded_cells"]} {json.dumps(st["discarded_by_reason"], sort_keys=True)}')
    print('availability (HTTP 200 / attempts):')
    for src in SELLERS + REFERENCES + [TRUTH]:
        av = st['availability'].get(src, {'attempts': 0, 'ok': 0})
        print(f'  {src}: {av["ok"]}/{av["attempts"]}')
    honest = cfg['collection']['role_list']['honest']
    print('remaining honest captures: ' + ', '.join(f'{s}: {honest - st["honest"][s]}' for s in SELLERS))
    print(f'remaining wrong-answer captures: {types_total - st["types_assigned"]} of {types_total}')
    if st.get('last_complete_t'):
        print(f'last complete cell: {utcnow_iso(st["last_complete_t"])}')
    print(f'sessions: {len(st["sessions"]) + (1 if st.get("current_session") else 0)}')
    return 0 if alive else 1


def cmd_stop(a):
    write_json_atomic(Path(a.data) / 'stop-request.json', {'reason': a.reason, 'at': utcnow_iso()})
    print('stop requested; the collector ends its session before the next cell')
    return 0


def cmd_release(a):
    data = Path(a.data)
    lock = Lock(data)
    if not lock.acquire():
        raise SystemExit('the collector is running')
    try:
        st = json.loads((data / 'state.json').read_text())
        note = {'reason': a.reason, 'at': utcnow_iso(), 'hold': st.get('hold'), 'stopped': st.get('stopped')}
        if st.get('stopped') and st['stopped']['reason'] == '429_rule':
            st['rate_limit']['consecutive'] = {k: 0 for k in st['rate_limit']['consecutive']}
            st['stopped'] = None
        elif st.get('stopped'):
            raise SystemExit('the collection is complete; nothing to release')
        st['hold'] = None
        st.setdefault('releases', []).append(note)
        write_json_atomic(data / 'state.json', st)
        (data / 'stop-request.json').unlink(missing_ok=True)
        print('released; the next `run` continues the collection')
        return 0
    finally:
        lock.release()


def cmd_archive(a):
    """Copies complete cells not yet in DEST, plus the metadata files."""
    data, dest = Path(a.data), Path(a.to)
    copied = 0
    for day in sorted((data / 'cells').glob('*')):
        for cell in sorted(day.iterdir()):
            if not (cell / 'manifest.json').exists():
                continue
            target = dest / 'cells' / day.name / cell.name
            if (target / 'manifest.json').exists():
                continue
            tmp = target.parent / f'.incoming-{cell.name}'
            if tmp.exists():
                shutil.rmtree(tmp)
            tmp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(cell, tmp)
            man = json.loads((tmp / 'manifest.json').read_text())
            for rel, meta in man['files'].items():
                if file_sha(tmp / rel) != meta['sha256']:
                    raise SystemExit(f'{cell}/{rel}: hash mismatch while archiving')
            os.replace(tmp, target)
            copied += 1
    for name in ('collection.json', 'state.json', 'plan/lists.json'):
        if (data / name).exists():
            (dest / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(data / name, dest / name)
    for sub in ('discarded', 'truth', 'log'):
        if (data / sub).exists():
            shutil.copytree(data / sub, dest / sub, dirs_exist_ok=True)
    print(f'archived {copied} new cells to {dest}')
    return 0


def cmd_verify(a):
    from verify import verify_data  # noqa: E402 (same directory)
    return verify_data(Path(a.data), deep=a.deep, allow_open=a.allow_open)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('init')
    s.add_argument('--data', required=True)
    s.add_argument('--c1tool', required=True)
    s.add_argument('--cast', default='cast')
    s.add_argument('--roots')
    s.add_argument('--config', default=str(DEFAULT_CONFIG))
    s.add_argument('--allow-dirty', action='store_true')
    s.add_argument('--no-truth-lookups', action='store_true',
                   help='queue truth lookups without sending them (for test runs where the truth host is unreachable)')
    for name in ('run', 'status'):
        s = sub.add_parser(name)
        s.add_argument('--data', required=True)
    s = sub.add_parser('verify')
    s.add_argument('--data', required=True)
    s.add_argument('--deep', action='store_true', help='re-derive judgment records (counts only)')
    s.add_argument('--allow-open', action='store_true', help='allow --deep before the collection is complete')
    for name in ('stop', 'release'):
        s = sub.add_parser(name)
        s.add_argument('--data', required=True)
        s.add_argument('--reason', required=True)
    s = sub.add_parser('archive')
    s.add_argument('--data', required=True)
    s.add_argument('--to', required=True)
    a = p.parse_args(argv)
    return {'init': cmd_init, 'run': cmd_run, 'status': cmd_status, 'verify': cmd_verify, 'stop': cmd_stop,
            'release': cmd_release, 'archive': cmd_archive}[a.cmd](a)


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
