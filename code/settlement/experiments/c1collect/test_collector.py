"""Scheduler tests for the C1 collector: fake backend, virtual clock."""
import copy
import decimal
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import collector as C  # noqa: E402
from verify import verify_data  # noqa: E402

GRID = 300
T0 = 1790000100  # a grid time
OUTCOME_WORDS = ('PASS', 'FAIL', 'INCONCLUSIVE', 'verdict', 'delta')


class SimulatedKill(BaseException):
    """Stands for SIGKILL: nothing in the collector handles it."""


class FakeClock:
    def __init__(self, t):
        self.t, self.run, self.stop = float(t), 1000.0, 500.0
        self.suspend_at = []  # (wall time, seconds): suspend when a sleep crosses it

    def now(self):
        return self.t

    def running(self):
        return self.run

    def stopping(self):
        return self.stop

    def _advance(self, s):
        self.t += s
        self.run += s
        self.stop += s

    def sleep(self, s):
        for at, dur in sorted(self.suspend_at):
            if self.t <= at < self.t + s:
                self.suspend_at.remove((at, dur))
                first = at - self.t
                self._advance(first)
                self.suspend(dur)
                self._advance(s - first)
                return
        self._advance(s)

    def suspend(self, s):
        self.t += s
        self.run += s


def price(t, src):
    base = decimal.Decimal(85000) + (t // GRID) % 97
    return C.normalize_decimal(base + (decimal.Decimal('0.25') if src.startswith('gemini') else 0))


class FakeBackend:
    """Deterministic stand-in for c1tool. `stage` maps (t, source) to a
    capture outcome; `hooks` maps an event name to a callable(t)."""

    def __init__(self, clock):
        self.clock = clock
        self.stage = {}
        self.hooks = {}
        self.truth_fn = lambda t: True
        self.truth_calls = []

    def _hook(self, name, t):
        h = self.hooks.get(name)
        if h:
            h(t)

    def _summary(self, t, src, d, log, role, value=True, at=0):
        with open(log, 'a') as f:
            f.write(json.dumps({'role': role, 'source': src}) + '\n')
        stage, status = self.stage.get((t, src), ('ok', 200))
        s = {'source_id': src, 'stage': stage, 'started_unix_ms': t * 1000 + at, 'finished_unix_ms': t * 1000 + at + 300}
        if stage in ('ok', 'invalid'):
            s['http_status'] = status
            name = src.replace(':', '_') + f'-{abs(hash((t, src, role))) % 10**16:016d}.json'
            Path(d).mkdir(parents=True, exist_ok=True)
            (Path(d) / name).write_text('{}\n')
            s['object_file'] = name
            if status != 200:
                s['stage'] = 'invalid'
        if s['stage'] == 'ok' and value:
            p = decimal.Decimal(price(t, 'x'))
            if role == 'seller':
                s['value'] = price(t, src)
            else:
                s['value'] = C.normalize_decimal(p + (1 if src.startswith('coinbase') else -1))
        return s

    def start_captures(self, role, sources, d, log):
        t = int(self.clock.now() // GRID * GRID)
        if self.clock.now() % GRID > 150:
            t += GRID
        self._hook('capture:' + role, t)
        return [self._summary(t, s, d, log, role) for s in sources]

    def finish_captures(self, h, what):
        return h

    def bundle(self, t, responses):
        self._hook('bundle', t)
        return json.dumps({'cases': [{'response_id': r['response_id'], 'body': r['body'].decode()} for r in responses]}).encode()

    def start_instance(self, plan, d, log, stderr):
        return {'plan': plan, 'd': d, 'log': log}

    def finish_instance(self, h, cases, timeout):
        plan = h['plan']
        t = plan['reference_time']
        self._hook(f'instance:{plan["instance"]}', t)
        caps = []
        for k, src in enumerate(plan['order']):
            if src in plan['skip']:
                caps.append({'source_id': src, 'stage': 'skipped_429'})
                continue
            caps.append(self._summary(t, src, h['d'], h['log'], f'instance-{plan["instance"]}', value=False,
                                      at=plan['start_unix_ms'] - t * 1000 + 400 * k))
        ok = [c for c in caps if c['stage'] == 'ok']
        med = decimal.Decimal(price(t, 'x'))
        js = []
        for c in json.loads(cases)['cases']:
            try:
                x = decimal.Decimal(json.loads(c['body'])['price'])
                v = 'PASS' if abs(x - med) <= decimal.Decimal('0.0025') * med else 'FAIL'
            except (KeyError, decimal.InvalidOperation):
                v = 'FAIL'
            if len(ok) < 2:
                v = 'INCONCLUSIVE'
            js.append({'response_id': c['response_id'], 'response': c['body'], 'verdict': v, 'reason': 'fake'})
        rec = {'format': 'fairbind/experimental/c1-judgment/v1', 'plan': plan, 'captures': caps, 'judgments': js}
        return json.dumps(rec).encode() + b'\n', rec

    def abort_instance(self, h):
        pass

    def truth(self, t, d, log):
        self.truth_calls.append((t, self.clock.now()))
        with open(log, 'a') as f:
            f.write('{}\n')
        ok = self.truth_fn(t)
        return {'ok': ok, 'reference_time': t, 'pages': [{'source_id': C.TRUTH, 'stage': 'ok', 'http_status': 200}],
                'failure': None if ok else 'no trades in window'}


FAKE_TOOL = '''#!/usr/bin/env python3
import json, sys
print(json.dumps({"objects": 0, "problems": []} if sys.argv[1] == "objects" else {"judgments_rederived": 0, "problems": []}))
'''


def small_config(**over):
    cfg = json.loads(C.DEFAULT_CONFIG.read_text())
    cfg['collection']['role_list'] = {'honest': 4, 'wrong': 3}
    counts = {'D-perturb/m=1.5': 1, 'D-near/m=1.05': 1, 'D-stale/1h': 1, 'D-unit': 1, 'D-adaptive': 1,
              'D-format/missing': 1}
    for g in cfg['data_api']['wrong_answer_generators']:
        for s in g['strata']:
            s['count'] = counts.get(s['type'], 0)
            if s['type'] == 'D-stale/1h':
                s['cells_back'] = 2
    cfg['collection']['max_cells'] = 60
    for k, v in over.items():
        cfg['collection'][k] = v
    return cfg


def make_data(root, cfg):
    data = Path(root) / 'data'
    data.mkdir(parents=True)
    tool = Path(root) / 'fake-c1tool'
    tool.write_text(FAKE_TOOL)
    tool.chmod(0o755)
    lists, lsha = C.build_lists(cfg)
    col = {'format': C.FORMAT_COLLECTION, 'config': cfg, 'config_sha256': C.sha256_hex(C.canonical(cfg)),
           'lists_sha256': lsha, 'tools': {'c1tool': str(tool), 'cast': 'cast'}, 'roots': None}
    C.write_json_atomic(data / 'collection.json', col)
    C.write_json_atomic(data / 'plan' / 'lists.json', lists)
    return data


class Env:
    def __init__(self, cfg=None, start=T0 - 100):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = make_data(self.tmp.name, cfg or small_config())
        self.clock = FakeClock(start)
        self.backend = FakeBackend(self.clock)
        self.out = io.StringIO()

    def collector(self, cls=C.Collector):
        return cls(self.data, self.backend, self.clock, self.out)

    def state(self):
        return json.loads((self.data / 'state.json').read_text())

    def cells(self):
        return [t for t, _ in self.collector()._cell_dirs()]

    def controllers(self):
        return {t: json.loads((d / 'controller.json').read_text()) for t, d in self.collector()._cell_dirs()}

    def discarded(self):
        return {int(p.stem): json.loads(p.read_text()) for p in (self.data / 'discarded').glob('*.json')}

    def verify(self):
        lines = []
        rc = verify_data(self.data, out=lines.append)
        return rc, lines

    def close(self):
        self.tmp.cleanup()


class HelperTests(unittest.TestCase):
    def test_decimal_helpers(self):
        self.assertEqual(C.normalize_decimal(decimal.Decimal('64229.80000')), '64229.8')
        self.assertEqual(C.normalize_decimal(decimal.Decimal('0.50')), '0.5')
        self.assertEqual(C.normalize_decimal(decimal.Decimal('100')), '100')
        self.assertEqual(C.exponent_form('85284.45'), '8.528445e4')
        self.assertEqual(C.exponent_form('85000'), '8.5e4')
        p = decimal.Decimal('85284.45')
        self.assertEqual(C.normalize_decimal(p * (1 + -1 * decimal.Decimal('1.05') * decimal.Decimal('0.0025'))),
                         '85060.57831875')

    def test_seeded_lists_match_the_plan(self):
        cfg = json.loads(C.DEFAULT_CONFIG.read_text())
        lists, sha = C.build_lists(cfg)
        self.assertEqual(C.build_lists(cfg)[1], sha)
        for s in C.SELLERS:
            self.assertEqual(len(lists['roles'][s]), 2055)
            self.assertEqual(lists['roles'][s].count('honest'), 1500)
        self.assertNotEqual(lists['roles'][C.SELLERS[0]], lists['roles'][C.SELLERS[1]])
        want = {'D-perturb/m=1.5': 84, 'D-perturb/m=3': 83, 'D-perturb/m=10': 83, 'D-near/m=1.05': 150,
                'D-near/m=1.1': 150, 'D-near/m=1.25': 150, 'D-stale/1h': 75, 'D-stale/24h': 75, 'D-unit': 60,
                'D-adaptive': 150, 'D-format/missing': 25, 'D-format/exponent': 25}
        self.assertEqual({k: lists['types'].count(k) for k in want}, want)
        self.assertEqual(len(lists['types']), 1110)
        self.assertEqual(cfg['collection']['role_list']['wrong'] * 2, len(lists['types']))
        stale = {s['type']: s['cells_back'] for s in C.type_strata(cfg) if 'cells_back' in s}
        self.assertEqual(stale, {'D-stale/1h': 12, 'D-stale/24h': 288})

    def test_seeded_values_depend_only_on_grid_time(self):
        a, b = C.Seeds(20260928), C.Seeds(20260928)
        for t in (T0, T0 + GRID, T0 + 86400):
            for s in C.SELLERS:
                self.assertEqual(a.base_instance(t, s), b.base_instance(t, s))
                self.assertIn(a.base_instance(t, s), (1, 2, 3))
                self.assertIn(a.sigma(t, s), (1, -1))
            self.assertEqual(sorted(a.slots(t).values()), [0, 1, 2])
            for i in (1, 2, 3):
                self.assertEqual(sorted(a.reference_order(t, i)), sorted(C.REFERENCES))
        self.assertNotEqual(C.Seeds(1).h('x', T0, 'a'), a.h('x', T0, 'a'))

    def test_grid_and_resume_rule(self):
        e = Env()
        try:
            c = e.collector()
            self.assertEqual(c.next_grid_time(T0 - 11), T0)
            self.assertEqual(c.next_grid_time(T0 - 10), T0 + GRID)  # must be more than max_skew ahead
            self.assertEqual(c.next_grid_time(T0 - 10.5), T0)
            self.assertEqual(c.next_grid_time(T0 + 1), T0 + GRID)
            c.state['last_complete_t'] = T0 + 5 * GRID
            self.assertEqual(c.next_grid_time(T0), T0 + 6 * GRID)
            plans = c.instance_plans(T0)
            starts = sorted(p['start_unix_ms'] - T0 * 1000 for p in plans.values())
            self.assertTrue(all(-10000 < s < 10000 for s in starts))
            self.assertEqual(len(set(starts)), 3)
        finally:
            e.close()


class RunTests(unittest.TestCase):
    def setUp(self):
        self.e = Env()

    def tearDown(self):
        self.e.close()

    def run_to_end(self, c=None):
        return (c or self.e.collector()).run()

    def test_uninterrupted_collection_reaches_targets(self):
        reason = self.run_to_end()
        self.assertEqual(reason, 'collection_complete')
        st = self.e.state()
        self.assertEqual(st['honest'], {s: 4 for s in C.SELLERS})
        self.assertEqual(st['types_assigned'], 6)
        cells = self.e.cells()
        self.assertEqual(cells, list(range(T0, T0 + GRID * len(cells), GRID)))
        self.assertEqual(st['sessions'][-1]['end_reason'], 'collection_complete')
        rc, lines = self.e.verify()
        self.assertEqual(rc, 0, lines)
        # A finished collection does nothing on the next run.
        self.assertEqual(self.run_to_end(), 'collection_complete')
        self.assertEqual(self.e.cells(), cells)

    def test_role_and_type_lists_are_consumed_in_grid_order(self):
        self.run_to_end()
        lists = json.loads((self.e.data / 'plan' / 'lists.json').read_text())
        pos = {s: 0 for s in C.SELLERS}
        types = []
        for t, ctl in sorted(self.e.controllers().items()):
            self.assertEqual([e['source_id'] for e in ctl['captures']], C.SELLERS)
            for e in ctl['captures']:
                s = e['source_id']
                if pos[s] < len(lists['roles'][s]):
                    self.assertEqual(e['role_list_index'], pos[s])
                    self.assertEqual(e['role'], lists['roles'][s][pos[s]])
                    pos[s] += 1
                if e.get('type'):
                    types.append(e['type'])
        self.assertEqual(sorted(types), sorted(lists['types']))

    def test_kill_mid_cell_discards_and_resumes_without_duplicates(self):
        ref = Env()
        try:
            ref.collector().run()
            ref_ctl = ref.controllers()
        finally:
            ref.close()
        kills = {T0 + 2 * GRID: 'capture:seller', T0 + 5 * GRID: 'instance:2', T0 + 7 * GRID: 'bundle'}
        for t, hook in kills.items():
            def kill(at, t=t, hook=hook):
                if at == t:
                    raise SimulatedKill(hook)
            self.e.backend.hooks[hook] = kill
        runs = 0
        while True:
            runs += 1
            try:
                reason = self.e.collector().run()
                break
            except SimulatedKill:
                self.e.clock.sleep(20)  # the watchdog restarts the collector
        self.assertEqual(reason, 'collection_complete')
        self.assertEqual(runs, 4)
        disc = self.e.discarded()
        self.assertEqual(set(disc), set(kills))
        self.assertTrue(all(d['reason'] == 'interrupted' for d in disc.values()))
        self.assertGreaterEqual(disc[T0 + 5 * GRID]['http_requests'], 2)
        cells = self.e.cells()
        self.assertEqual(len(cells), len(set(cells)))
        self.assertFalse(set(cells) & set(disc))
        st = self.e.state()
        self.assertEqual(st['discarded_by_reason'], {'interrupted': 3})
        self.assertEqual(st['requests']['discarded_cells'], sum(d['http_requests'] for d in disc.values()))
        ends = [s['end_reason'] for s in st['sessions']]
        self.assertEqual(ends, ['other', 'other', 'other', 'collection_complete'])
        # Seeded values at a grid time equal those of the uninterrupted run.
        ctl = self.e.controllers()
        common = set(ctl) & set(ref_ctl)
        self.assertGreaterEqual(len(common), 5)
        for t in common:
            self.assertEqual(ctl[t]['seeded'], ref_ctl[t]['seeded'])
            self.assertEqual(ctl[t]['instance_plans'], ref_ctl[t]['instance_plans'])
        rc, lines = self.e.verify()
        self.assertEqual(rc, 0, lines)

    def test_kill_after_rename_before_state_write(self):
        target = T0 + 3 * GRID

        class Crashy(C.Collector):
            armed = True

            def save(self):
                if Crashy.armed and self.cell_dir(target).exists() and self.state['last_complete_t'] == target:
                    Crashy.armed = False
                    raise SimulatedKill('after rename')
                super().save()
        with self.assertRaises(SimulatedKill):
            self.e.collector(Crashy).run()
        self.assertNotEqual(self.e.state()['last_complete_t'], target)
        c = self.e.collector()
        self.assertEqual(c.state['last_complete_t'], target)  # adopted from the cell manifest
        self.e.clock.sleep(30)
        self.assertEqual(c.run(), 'collection_complete')
        cells = self.e.cells()
        self.assertEqual(cells.count(target), 1)
        self.assertNotIn(target, self.e.discarded())
        rc, lines = self.e.verify()
        self.assertEqual(rc, 0, lines)

    def test_sleep_inside_a_cell_discards_it(self):
        t1 = T0 + 2 * GRID
        self.e.backend.hooks['capture:seller'] = lambda t: self.e.clock.suspend(40) if t == t1 else None
        self.run_to_end()
        disc = self.e.discarded()
        self.assertEqual({t: d['reason'] for t, d in disc.items()}, {t1: 'machine_sleep'})
        st = self.e.state()
        self.assertEqual(st['sessions'][0]['end_reason'], 'machine_sleep')
        self.assertEqual(st['sessions'][0]['complete_cells'], 2)
        self.assertEqual(st['sessions'][1]['first_complete_t'], t1 + GRID)
        self.assertEqual(self.e.verify()[0], 0)

    def test_sleep_between_cells_ends_the_session(self):
        self.e.clock.suspend_at.append((T0 + GRID + 100, 3 * GRID))
        self.run_to_end()
        st = self.e.state()
        self.assertEqual(st['sessions'][0]['end_reason'], 'machine_sleep')
        self.assertEqual(st['discarded_cells'], 0)
        cells = self.e.cells()
        self.assertIn(T0 + GRID, cells)
        self.assertNotIn(T0 + 2 * GRID, cells)  # unopened while suspended
        self.assertEqual(st['sessions'][1]['first_complete_t'], cells[2])

    def test_network_outage_discards_only_when_no_response_at_all(self):
        t1, t2 = T0 + GRID, T0 + 2 * GRID
        for src in C.SELLERS + C.REFERENCES:
            self.e.backend.stage[(t1, src)] = ('connect', None)
        for src in C.SELLERS:
            self.e.backend.stage[(t2, src)] = ('connect', None)
        self.run_to_end()
        disc = self.e.discarded()
        self.assertEqual({t: d['reason'] for t, d in disc.items()}, {t1: 'network'})
        st = self.e.state()
        self.assertEqual(st['sessions'][0]['end_reason'], 'network')
        ctl = self.e.controllers()[t2]  # sellers failed, references answered: the cell counts
        self.assertTrue(all(e['role'] is None for e in ctl['captures']))
        self.assertEqual(st['availability'][C.SELLERS[0]]['attempts'] - st['availability'][C.SELLERS[0]]['ok'], 1)

    def test_429_rule_skips_next_cell_and_stops_after_three_across_sessions(self):
        src = C.SELLERS[1]
        hits = [T0, T0 + 2 * GRID, T0 + 4 * GRID]
        for t in hits:
            self.e.backend.stage[(t, src)] = ('ok', 429)
        # A restart between the second and the third 429 keeps the count.
        killed = []

        def kill(t):
            if t == T0 + 3 * GRID and not killed:
                killed.append(t)
                raise SimulatedKill()
        self.e.backend.hooks['capture:seller'] = kill
        try:
            self.e.collector().run()
        except SimulatedKill:
            pass
        self.e.clock.sleep(20)
        reason = self.e.collector().run()
        self.assertEqual(reason, '429_rule')
        ctl = self.e.controllers()
        self.assertEqual(ctl[T0 + GRID]['captures'][1]['capture']['stage'], 'skipped_429')
        st = self.e.state()
        self.assertEqual(st['stopped']['reason'], '429_rule')
        self.assertEqual(st['rate_limit']['consecutive'][src], 3)
        self.assertEqual(st['sessions'][-1]['end_reason'], '429_rule')
        n = len(self.e.cells())
        self.assertEqual(self.e.collector().run(), '429_rule')  # stays stopped
        self.assertEqual(len(self.e.cells()), n)

    def test_three_instances_hitting_429_in_one_cell_stop_at_once(self):
        self.e.backend.stage[(T0 + GRID, C.REFERENCES[0])] = ('ok', 429)
        self.assertEqual(self.e.collector().run(), '429_rule')
        self.assertEqual(self.e.cells()[-1], T0 + GRID)

    def test_max_cells_stops(self):
        e = Env(small_config(max_cells=3))
        try:
            self.assertEqual(e.collector().run(), 'collection_complete')
            self.assertEqual(len(e.cells()), 3)
            self.assertIn('3 complete cells', e.state()['stopped']['note'])
        finally:
            e.close()

    def test_stale_type_waits_for_an_eligible_capture(self):
        cfg = small_config()
        e = Env(cfg)
        try:
            lists = C.build_lists(cfg)[0]
            e.collector().run()
            ctl = e.controllers()
            cells = sorted(ctl)
            for t in cells:
                for x in ctl[t]['captures']:
                    if x.get('type') == 'D-stale/1h':
                        earlier = t - 2 * GRID
                        self.assertIn(earlier, cells)
                        prev = next(y for y in ctl[earlier]['captures'] if y['source_id'] == x['source_id'])
                        self.assertEqual(prev['capture']['stage'], 'ok')
                        self.assertEqual(x['params']['earlier_price'], prev['capture']['value'])
                        self.assertEqual(json.loads(x['response'])['price'], prev['capture']['value'])
            self.assertIn('D-stale/1h', lists['types'])
            self.assertEqual(e.state()['deferred'], [])
        finally:
            e.close()

    def test_stale_type_is_deferred_past_a_discarded_predecessor(self):
        cfg = small_config()
        lists = C.build_lists(cfg)[0]
        k = lists['types'].index('D-stale/1h')
        e = Env(cfg)
        try:
            # Discard every cell two cells after which a stale type could be used first.
            e.backend.hooks['capture:seller'] = lambda t: e.clock.suspend(5) if t in (T0, T0 + GRID) else None
            e.collector().run()
            got = [(t, x['type'], x.get('type_origin')) for t, c in sorted(e.controllers().items())
                   for x in c['captures'] if x.get('type')]
            stale = [g for g in got if g[1] == 'D-stale/1h']
            self.assertEqual(len(stale), 1)
            self.assertGreaterEqual(stale[0][0], T0 + 4 * GRID)
            self.assertEqual(e.verify()[0], 0)
            self.assertGreaterEqual(k, 0)
        finally:
            e.close()

    def test_adaptive_state_persists_and_marks_session_boundaries(self):
        cfg = small_config()
        for g in cfg['data_api']['wrong_answer_generators']:
            for s in g['strata']:
                s['count'] = 6 if s['type'] == 'D-adaptive' else 0
        e = Env(cfg)
        try:
            killed = []

            def kill(t):
                if t == T0 + 6 * GRID and not killed:
                    killed.append(t)
                    raise SimulatedKill()
            e.backend.hooks['bundle'] = kill
            try:
                e.collector().run()
            except SimulatedKill:
                pass
            before = e.state()['adaptive']
            e.clock.sleep(20)
            c = e.collector()
            self.assertEqual(c.state['adaptive'], before)
            c.run()
            params = [(t, x['source_id'], x['params']) for t, ctl in sorted(e.controllers().items())
                      for x in ctl['captures'] if x.get('type') == 'D-adaptive']
            self.assertEqual(len(params), 6)
            self.assertTrue(params[0][2]['delta_is_initial'])
            self.assertEqual(params[0][2]['delta'], '0.2')
            self.assertEqual(sum(p[2]['delta_is_initial'] for p in params), 1)
            for (_, _, p), (t_prev, _, _) in zip(params[1:], params[:-1]):
                self.assertEqual(p['previous_adaptive_t'], t_prev)
            crossed = [p for t, _, p in params if p['feedback_crossed_session']]
            after_kill = [p for t, _, p in params if t > killed[0]]
            if after_kill:
                self.assertTrue(after_kill[0]['feedback_crossed_session'])
            self.assertLessEqual(len(crossed), 2)
            self.assertNotIn(killed[0], [t for t, _, _ in params])
            st = e.state()['adaptive']
            self.assertTrue(st['initial_used'])
            self.assertGreaterEqual(decimal.Decimal(st['delta']), decimal.Decimal('0.005'))
            self.assertLessEqual(decimal.Decimal(st['delta']), decimal.Decimal('0.5'))
        finally:
            e.close()

    def test_adaptive_type_is_deferred_when_the_generator_gets_no_reference(self):
        cfg = small_config()
        e = Env(cfg)
        try:
            for k in range(40):
                for r in C.REFERENCES:
                    e.backend.stage[(T0 + k * GRID, r)] = ('ok', 503) if k < 20 else ('ok', 200)
            e.collector().run()
            got = [(t, x) for t, c in sorted(e.controllers().items()) for x in c['captures']]
            deferred = [t for t, x in got if x.get('adaptive_deferred')]
            used = [t for t, x in got if x.get('type') == 'D-adaptive']
            self.assertTrue(deferred)
            self.assertEqual(len(used), 1)
            self.assertGreater(used[0], deferred[0])
            self.assertEqual(e.verify()[0], 0)
        finally:
            e.close()

    def drain_truth(self, c, seconds=4000):
        end = self.e.clock.now() + seconds
        while self.e.clock.now() < end:
            while c.truth_step(deadline=self.e.clock.now() + 1000):
                pass
            self.e.clock.sleep(30)

    def test_truth_lookups_queue_and_retry_schedule(self):
        calls = {}

        def flaky(t):
            calls[t] = calls.get(t, 0) + 1
            return calls[t] >= 3
        self.e.backend.truth_fn = flaky
        self.run_to_end()
        self.drain_truth(self.e.collector())
        q = json.loads((self.e.data / 'truth' / 'queue.json').read_text())
        near = [t for t, ctl in self.e.controllers().items()
                if any((x.get('type') or '').startswith(('D-near', 'D-adaptive')) for x in ctl['captures'])]
        self.assertTrue(near)
        self.assertEqual(sorted(i['reference_time'] for i in q['items']), sorted(near))
        for item in q['items']:
            t = item['reference_time']
            self.assertEqual([a['ok'] for a in item['attempts']], [False, False, True])
            times = [at for tt, at in self.e.backend.truth_calls if tt == t]
            self.assertGreaterEqual(times[0], t + 10 + 30)  # never before the window has closed
            self.assertGreaterEqual(times[1], times[0] + 60)
            self.assertGreaterEqual(times[2], times[0] + 660)
            self.assertEqual(item['result'], 'ok')

    def test_truth_lookups_are_spaced_after_a_backlog(self):
        # No lookup fits between cells during the run, so every queued
        # lookup is due at once when the collector next waits.
        cfg = small_config()
        cfg['collection']['truth_lookup']['reserve_seconds'] = 10 ** 6
        self.e.close()
        self.e = Env(cfg)
        self.run_to_end()
        c = self.e.collector()
        c.col['truth_lookup']['reserve_seconds'] = 60
        self.drain_truth(c)
        times = sorted(at for _, at in self.e.backend.truth_calls)
        self.assertGreater(len(times), 1)
        for a, b in zip(times, times[1:]):
            self.assertGreaterEqual(b - a, 5)

    def test_truth_lookup_gives_up_after_four_attempts_and_survives_restart(self):
        self.e.backend.truth_fn = lambda t: False
        self.run_to_end()
        self.e.clock.sleep(3000)  # collector down; the queue waits
        self.drain_truth(self.e.collector())
        q = json.loads((self.e.data / 'truth' / 'queue.json').read_text())
        self.assertTrue(q['items'])
        for i in q['items']:
            self.assertTrue(i['done'])
            self.assertEqual(len(i['attempts']), 4)
            self.assertEqual(i['result'], 'no_truth')
        st = self.e.state()
        self.assertEqual(st['requests']['truth'], 4 * len(q['items']))

    def test_no_judgment_outcome_is_printed_or_logged(self):
        self.run_to_end()
        text = self.e.out.getvalue() + (self.e.data / 'log' / 'collector.log').read_text()
        for w in OUTCOME_WORDS:
            self.assertNotIn(w, text)
        r = subprocess.run([sys.executable, str(HERE / 'collector.py'), 'status', '--data', str(self.e.data)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)  # not running
        self.assertIn('complete cells:', r.stdout)
        for w in OUTCOME_WORDS:
            self.assertNotIn(w, r.stdout)
        lines = []
        verify_data(self.e.data, out=lines.append)
        for w in OUTCOME_WORDS:
            self.assertNotIn(w, '\n'.join(lines))

    def test_deep_verify_is_refused_while_open(self):
        e = Env(small_config(max_cells=2))
        try:
            e.collector().run()
            st = e.state()
            st['stopped'] = None
            C.write_json_atomic(e.data / 'state.json', st)
            lines = []
            self.assertEqual(verify_data(e.data, deep=True, out=lines.append), 1)
            self.assertTrue(any('--deep refused' in x for x in lines))
            lines = []
            self.assertEqual(verify_data(e.data, deep=True, allow_open=True, out=lines.append), 0, lines)
        finally:
            e.close()

    def test_verify_detects_a_duplicate_and_a_tampered_file(self):
        self.run_to_end()
        cells = self.e.collector()._cell_dirs()
        t, d = cells[1]
        (d / 'requests.log').write_text('tampered\n')
        rc, lines = self.e.verify()
        self.assertEqual(rc, 1)
        self.assertTrue(any('hash or size mismatch' in x for x in lines))
        C.write_json_atomic(self.e.data / 'discarded' / f'{t}.json',
                            {'format': C.FORMAT_DISCARD, 'reference_time': t, 'reason': 'interrupted'})
        rc, lines = self.e.verify()
        self.assertTrue(any('both complete and discarded' in x for x in lines))

    def test_user_stop_holds_until_release(self):
        C.write_json_atomic(self.e.data / 'stop-request.json', {'reason': 'machine needed for other work'})
        self.assertEqual(self.e.collector().run(), 'user_stop')
        self.assertEqual(self.e.collector().run(), 'user_stop')
        st = self.e.state()
        self.assertEqual(st['hold']['reason'], 'machine needed for other work')
        r = subprocess.run([sys.executable, str(HERE / 'collector.py'), 'release', '--data', str(self.e.data),
                            '--reason', 'back'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.e.collector().run(), 'collection_complete')


class LockTests(unittest.TestCase):
    def test_second_run_exits_at_once_and_status_reports_liveness(self):
        e = Env()
        try:
            status = [sys.executable, str(HERE / 'collector.py'), 'status', '--data', str(e.data)]
            self.assertEqual(subprocess.run(status, capture_output=True).returncode, 1)
            lock = C.Lock(e.data)
            self.assertTrue(lock.acquire())
            try:
                t = time.time()
                r = subprocess.run([sys.executable, str(HERE / 'collector.py'), 'run', '--data', str(e.data)],
                                   capture_output=True, text=True, timeout=30)
                self.assertEqual(r.returncode, 0)
                self.assertIn('already running', r.stdout)
                self.assertLess(time.time() - t, 10)
                self.assertEqual(subprocess.run(status, capture_output=True).returncode, 0)
            finally:
                lock.release()
            self.assertEqual(subprocess.run(status, capture_output=True).returncode, 1)
        finally:
            e.close()


if __name__ == '__main__':
    unittest.main()
