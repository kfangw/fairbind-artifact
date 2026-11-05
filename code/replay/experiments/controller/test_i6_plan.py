"""Plan of the hold-period harness (I6): cell counts, directive blocks, k and the harness block.

The directive fixtures under services/internal/directive/testdata/i6 are generated from this plan
(one file per process and distinct block shape). Regenerate them after a plan change with

    FAIRBIND_WRITE_I6_FIXTURES=1 make i6-check
"""
import collections
import contextlib
import copy
import io
import json
import os
import sys
import unittest
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controller import operating_point as opt  # noqa: E402
from controller import profile as prof  # noqa: E402
from controller import runner  # noqa: E402
from controller import scenario as scn  # noqa: E402
from controller.__main__ import main  # noqa: E402

SCENARIO = runner.ROOT / 'experiments' / 'scenarios' / 'I6.yaml'
PROFILE = runner.ROOT / 'profiles' / 'local-evaluation-v1.json'
FIXTURES = runner.ROOT / 'services' / 'internal' / 'directive' / 'testdata' / 'i6'
DATA, OPEN_WEIGHTS = 'data-api-fast-v1', 'open-weights-standard-v1'
SEED = runner.PLAN_BASE_SEEDS['I6']
# Blocks whose values are the same for every run shape; a fixture differs from another only in the
# other blocks.
VALUE_BLOCKS = ('seed', 'parameters', 'randomness')


def plan(profile_name=DATA, repetitions=None, op=None, profile=None):
    sc = scn.load_scenario(SCENARIO)
    base = profile or prof.load_profile(PROFILE, profile_name)
    return runner.build_plan([sc], base, base_seed=SEED, repetitions=repetitions, op=op)


def cell_class(entry):
    role = entry['cell']['role']
    return {'cheater': 'deviator', 'positive_control': 'deviator', 'finite': 'F', 'honest': 'H',
            'availability': 'V'}[role]


def directive_file(entry, proc):
    """The directive file the runner writes for one process (runner.execute)."""
    return dict(seed=entry['seed'], **entry['directives'][proc])


def _shape(value):
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return 'number'
    if isinstance(value, list):
        return [_shape(v) for v in value]
    return sorted((k, _shape(v)) for k, v in value.items())


def fixtures(entries):
    """One directive file per process and distinct block shape, named <cell>-<process>.json."""
    out, seen = {}, set()
    for e in entries:
        for proc in sorted(e['directives']):
            doc = directive_file(e, proc)
            sig = (proc, repr(_shape({k: v for k, v in doc.items() if k not in VALUE_BLOCKS})))
            if sig in seen:
                continue
            seen.add(sig)
            stem = f"{e['cell']['name'].lower()}-{proc}"
            name, n = f'{stem}.json', 2
            while name in out:
                name, n = f'{stem}-{n}.json', n + 1
            out[name] = json.dumps(doc, indent=2, sort_keys=True) + '\n'
    return out


# Directive processes; a file in FIXTURES whose name starts with one of these or with `invalid-` is
# a hand-written Go fixture (testdata/i6/README.md) and is not generated here.
GO_FIXTURE_PREFIXES = ('invalid-', 'verifier-', 'seller-', 'keeper-', 'buyer-')


def generated(path):
    return not path.name.startswith(GO_FIXTURE_PREFIXES)


def expected_fixtures():
    return fixtures(plan(DATA, repetitions=1) + plan(OPEN_WEIGHTS, repetitions=1))


def with_k(k):
    """The data profile and the operating point with failureLimit k (the two must agree)."""
    base = prof.load_profile(PROFILE, DATA)
    base['parameters']['failureLimit'] = k
    op = opt.load()
    op['profiles'][DATA]['failureLimit'] = dict(op['profiles'][DATA]['failureLimit'], value=k)
    return base, op


class Counts(unittest.TestCase):
    def test_planned_runs_per_cell_class(self):
        data, ow = plan(DATA), plan(OPEN_WEIGHTS)
        for entries in (data, ow):
            self.assertEqual([e['run_id'] for e in entries if not e['runnable']], [])
        by_class = collections.Counter(cell_class(e) for e in data)
        self.assertEqual(dict(by_class), {'deviator': 3580 - 260, 'F': 900, 'H': 30, 'V': 4})
        self.assertEqual(len(data), 3580 - 260 + 900 + 30 + 4)
        self.assertEqual(collections.Counter(e['cell']['name'] for e in ow), {'P4-low': 200, 'P4-high': 60})
        self.assertEqual(by_class['deviator'] + len(ow), 3580)
        cells = collections.Counter((e['cell']['name'], e['parameters'].get('finite_attack_cheat_sales'))
                                    for e in data if cell_class(e) in ('F', 'V'))
        for strategy in ('F-switch', 'F-stop', 'F-exit'):
            for m in (1, 5, 25):
                self.assertEqual(cells[(strategy, m)], 100)
        for n in (9, 12, 20, 40):
            self.assertEqual(cells[(f'V-{n}', 'none')], 1)

    def test_cli_dry_run_has_no_blocked_run(self):
        for name in (DATA, OPEN_WEIGHTS):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(['--dry-run', '--run-list', 'hold-period-grid', '--profile-name', name,
                             '--seed', str(SEED)])
            doc = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(doc['runs'], doc['runnable'], name)
            self.assertFalse(any('base seed' in n for e in doc['plan'] for n in e['notes']))

    def test_other_base_seed_is_noted(self):
        sc = scn.load_scenario(SCENARIO)
        entries = runner.build_plan([sc], prof.load_profile(PROFILE, DATA), base_seed=0, repetitions=1)
        self.assertTrue(all(any('--seed 20260928' in n for n in e['notes']) for e in entries))
        self.assertTrue(all(e['runnable'] for e in entries))


class FiniteAttackCells(unittest.TestCase):
    def test_finite_cells(self):
        entries = [e for e in plan(DATA, repetitions=1) if cell_class(e) == 'F']
        after = {'F-switch': 'serve_honestly', 'F-stop': 'stop_selling', 'F-exit': 'request_exit'}
        r_m = opt.rate_per_block(opt.load(), 'mean_14d_p99_top400')
        for e in entries:
            p = e['parameters']
            self.assertEqual((p['judgment_path'], p['keeper_delay_budget_blocks'], p['scale_factor']),
                             ('normal', 0, 1))
            self.assertAlmostEqual(p['Lambda_cheater'], r_m)
            self.assertEqual(e['effective_hold_period_blocks'], 60000)
            self.assertFalse(e['override_used'])
            self.assertEqual(e['finite_attack'], dict(cheat_sales=p['finite_attack_cheat_sales'],
                                                      after=after[e['cell']['name']], counts=runner.finiteattack.COUNTS))
            self.assertEqual(e['directives']['seller']['seller_policy']['reentry'], 'none')
            self.assertTrue(e['harness']['cheatBody'])
            self.assertEqual(e['directives']['buyer']['workload']['end'],
                             dict(rule='finite_attack', m=p['finite_attack_cheat_sales'], hold_blocks=60000,
                                  case_horizon=58994))
            self.assertNotIn('keeper_delay', e['directives']['keeper'])

    def test_role_rules_are_validated(self):
        sc = scn.load_scenario(SCENARIO)
        doc = {k: v for k, v in sc.items() if not k.startswith('_')}
        self.assertEqual(scn.validate(doc, 'I6'), [])
        cases = [
            (('F-stop', 'set', 'judgment_path', 'worst'), 'normal path'),
            (('F-stop', 'set', 'Lambda_cheater', 'bucket_max'), 'sells at'),
            (('F-stop', 'set', 'keeper_delay_budget_blocks', 100), 'prompt keeper'),
            (('F-stop', 'set', 'injection', 'honest_error_off'), 'turns the honest error off'),
            (('M4', 'set', 'injection', 'honest_error_off'), 'turns the honest error off'),
            (('M4', 'set', 'finite_attack_cheat_sales', 3), 'only a finite-attack cell'),
            (('V-9', 'set', 'judgment_path', 'normal'), 'worst path'),
            (('H', 'set', 'injection', 'off'), 'injection must be one of'),
        ]
        for (cell, part, key, value), message in cases:
            bad = copy.deepcopy(doc)
            bad['cells'][cell].setdefault(part, {})[key] = value
            self.assertTrue(any(message in err for err in scn.validate(bad, 'I6')), (cell, key, value))
        bad = copy.deepcopy(doc)
        del bad['cells']['F-exit']['sweep']
        self.assertTrue(any('finite_attack_cheat_sales' in err for err in scn.validate(bad, 'I6')))

    def test_unresolved_finite_values_block_the_run(self):
        sc = scn.load_scenario(SCENARIO)
        base = prof.load_profile(PROFILE, DATA)
        point = next(pt for pt in scn.sweep_points(sc) if pt['cell'] == 'F-stop')
        for key, value in (('finite_attack_after', 'none'), ('finite_attack_cheat_sales', 0),
                           ('assignable_verifiers', 0), ('injection', 'off')):
            r = scn.resolve(sc, dict(point, **{key: value}), base)
            self.assertIn(key, r['unresolved'])
        r = scn.resolve(sc, dict(next(pt for pt in scn.sweep_points(sc) if pt['cell'] == 'M4'),
                                 finite_attack_after='stop_selling'), base)
        self.assertIn('finite_attack_after', r['unresolved'])


class DirectiveBlocks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = plan(DATA, repetitions=1)
        cls.all = cls.data + plan(OPEN_WEIGHTS, repetitions=1)

    def test_honest_error_off_only_in_f_switch(self):
        op = opt.load()
        for e in self.all:
            block = e['directives']['verifier']['judgment_injection']
            t = opt.symbols(op, e['operating_point']['profile'])
            self.assertEqual(sorted(block), ['alpha', 'applies_to', 'beta', 'c', 'draw', 'h', 'honest_error_off'])
            self.assertEqual((block['h'], block['beta']), (t['h'], t['beta']))
            self.assertEqual(block['draw'], runner.INJECTION_DRAW)
            self.assertEqual(block['applies_to'], 'every assignment')
            if e['cell']['name'] == 'F-switch':
                self.assertEqual((block['alpha'], block['c'], block['honest_error_off']), (0, 0, True))
            else:
                self.assertEqual((block['alpha'], block['c'], block['honest_error_off']), (t['alpha'], t['c'], False))
                self.assertGreater(block['alpha'], 0)
                self.assertGreater(block['c'], 0)
        self.assertEqual(sum(e['directives']['verifier']['judgment_injection']['honest_error_off'] for e in self.data), 3)

    def test_keeper_delay_only_on_worst_path_or_positive_budget(self):
        seen = collections.Counter()
        for e in self.all:
            keeper = e['directives']['keeper']
            kappa = e['parameters']['keeper_delay_budget_blocks']
            path = e['judgment_path']
            if path == 'normal' and kappa == 0:
                self.assertNotIn('keeper_delay', keeper, e['run_id'])
                seen['none'] += 1
                continue
            block = keeper['keeper_delay']
            self.assertEqual((block['path'], block['budget_blocks'], block['expected_kappa_sigma']),
                             (path, kappa, kappa))
            seen[(path, kappa > 0)] += 1
            self.assertEqual(e['directives']['buyer']['clock']['kappa'], kappa)
        self.assertEqual(set(seen), {'none', ('normal', True), ('worst', True), ('worst', False)})

    def test_seller_policy_by_role(self):
        want = {
            'cheater': ('top_up_to_scale_then_reinstate', 'before_reentry_to_scale'),
            'positive_control': ('top_up_to_scale_then_reinstate', 'before_reentry_to_scale'),
            'availability': ('top_up_to_scale_then_reinstate', 'before_reentry_to_scale'),
            'honest': ('top_up_to_scale_then_reinstate', 'after_each_deduction_to_scale'),
            'finite': ('none', 'none'),
        }
        for e in self.all:
            policy = e['directives']['seller']['seller_policy']
            role = e['cell']['role']
            self.assertEqual(policy['role'], e['parameters']['seller_role'])
            self.assertEqual(policy['role'], {'positive_control': 'cheater', 'availability': 'cheater'}.get(role, role))
            self.assertIs(policy['appeal_initial_fail'], True)
            self.assertEqual(policy['scale_factor'], e['parameters']['scale_factor'])
            self.assertEqual((policy['reentry'], policy['top_up']), want[role])

    def test_workload_and_clock(self):
        for e in self.all:
            w = e['directives']['buyer']['workload']
            role, worst = e['cell']['role'], e['judgment_path'] == 'worst'
            self.assertEqual(sorted(w), ['appeal_initial_pass', 'claim', 'dispute_sampled_sale', 'end', 'max_blocks',
                                         'rate_per_block', 'scale_factor'])
            self.assertEqual(w['rate_per_block'], e['parameters']['Lambda_cheater'])
            self.assertEqual(w['scale_factor'], e['parameters']['scale_factor'])
            self.assertIs(w['dispute_sampled_sale'], False)
            self.assertIs(w['appeal_initial_pass'], role == 'honest')
            self.assertEqual(w['claim'], 'after_case_final' if worst else 'when_claimable')
            self.assertIsNone(w['max_blocks'])
            rule = {'finite': 'finite_attack', 'honest': 'honest_windows', 'availability': 'worst_path_cases'}
            self.assertEqual(w['end']['rule'], rule.get(role, 'episodes'))
            if role == 'honest':
                self.assertEqual(w['end'], dict(rule='honest_windows', windows=5, window_blocks=60000, start_offset=60000))
            if role == 'availability':
                self.assertEqual(w['end'], dict(rule='worst_path_cases', count=30))
            if rule.get(role) is None:
                self.assertEqual(w['end'], dict(rule='episodes', count=2))
            c = e['directives']['buyer']['clock']
            self.assertEqual(c['progress'], ['keeper', 'verifier', 'seller'])
            self.assertEqual(c['stop_offsets'], [-1, 0])

    def test_blocks_stay_out_of_other_scenarios_and_parameters(self):
        for e in self.all:
            for proc, d in e['directives'].items():
                for key in ('injection', 'assignable_verifiers', 'finite_attack_cheat_sales', 'finite_attack_after'):
                    self.assertNotIn(key, d.get('parameters', {}), proc)
        others = runner.build_plan([scn.load_scenario(runner.ROOT / 'experiments' / 'scenarios' / 'D3.yaml')],
                                   prof.load_profile(PROFILE, DATA), repetitions=1)
        for e in others:
            self.assertIsNone(e['harness'])
            for d in e['directives'].values():
                for block in ('judgment_injection', 'seller_policy', 'workload', 'clock'):
                    self.assertNotIn(block, d)

    def test_seed_effects(self):
        self.assertIn('fairbind/seed/verifier', runner.SEED_EFFECTS['verifier_behavior_draw'])
        for e in self.data:
            self.assertEqual(e['directives']['buyer']['randomness'], runner.SEED_EFFECTS)
            self.assertEqual(e['base_seed'], SEED)


class OperatingPointK(unittest.TestCase):
    def test_bond_follows_k(self):
        """k is read from the operating point: two values of failureLimit give B = k * g * ceil(1/p)."""
        g_over_p = 250000
        for k in (19, 31):
            base, op = with_k(k)
            entries = plan(repetitions=1, op=op, profile=base)
            self.assertTrue(all(e['runnable'] for e in entries))
            for e in entries:
                self.assertEqual(e['operating_point_k']['value'], k)
                self.assertEqual(e['operating_point']['k'], e['operating_point_k'])
                self.assertIn('profiles.data-api-fast-v1.failureLimit', e['operating_point_k']['source'])
                self.assertEqual(runner.envelope_fields(e)['operating_point_k'], e['operating_point_k'])
                if e['parameter_expressions']['bond_fraction_of_g_over_p'] == 'failureLimit' \
                        and e['parameter_expressions']['bad_sale_gain_atomic'] == 'v':
                    self.assertEqual(e['parameters']['bond_level_realized_atomic'], k * g_over_p, e['run_id'])
                    self.assertEqual(e['profile_overrides']['sellerPenalty'], str(k * g_over_p))
            for name in ('F-switch', 'F-stop', 'F-exit', 'V-9', 'H', 'M1-high-admissible'):
                self.assertTrue(any(e['cell']['name'] == name
                                    and e['parameters']['bond_level_realized_atomic'] == k * g_over_p for e in entries))
            # M2 fixes B as a multiple of g/p that does not follow k.
            m2 = {e['parameters']['bond_level_realized_atomic'] for e in entries if e['cell']['name'] == 'M2-high'}
            self.assertEqual(m2, {25, g_over_p // 2, g_over_p})

    def test_k_must_agree_with_the_profile(self):
        base, op = with_k(19)
        base['parameters']['failureLimit'] = 20
        with self.assertRaises(opt.OperatingPointError):
            plan(repetitions=1, op=op, profile=base)


class Harness(unittest.TestCase):
    def test_assignable_bond_floor(self):
        self.assertEqual(prof.assignable_bond_floor(prof.load_profile(PROFILE, DATA)), 3_020_000)
        self.assertEqual(prof.assignable_bond_floor(prof.load_profile(PROFILE, OPEN_WEIGHTS)), 50_000_000)

    def test_harness_blocks(self):
        entries = plan(DATA, repetitions=1) + plan(OPEN_WEIGHTS, repetitions=1)
        for e in entries:
            h = e['harness']
            self.assertEqual(sorted(h), ['assignableVerifiers', 'buyerPurchases', 'cheatBody', 'pollMs',
                                         'registeredVerifiers', 'sellerBondScale', 'spareVerifiers',
                                         'verifierBondAtomic'])
            self.assertEqual(h['buyerPurchases'], runner.expected_purchases(
                e['cell']['role'], e['parameters'], e['_profile'], e['directives']['buyer']['workload']['end']))
            self.assertGreaterEqual(h['buyerPurchases'], 100)
            self.assertEqual(h['sellerBondScale'], e['parameters']['scale_factor'])
            self.assertIs(h['cheatBody'], True)
            self.assertEqual(h['verifierBondAtomic'], e['_profile']['parameters']['verifierBondCap'])
            n = int(e['cell']['name'][2:]) if e['cell']['role'] == 'availability' else 40
            self.assertEqual((h['assignableVerifiers'], h['registeredVerifiers']), (n, max(n, 14)))
            if e['cell']['role'] == 'availability':
                # 30 worst-path cases strike 7 verifiers each, three strikes remove one.
                self.assertEqual(h['spareVerifiers'], 70)
            else:
                self.assertEqual(h['spareVerifiers'], h['registeredVerifiers'])

    def test_data_profiles_use_the_experimental_predicate(self):
        for e in plan(DATA, repetitions=1):
            self.assertEqual(e['_profile']['parameters']['predicateId'], runner.EXPERIMENTAL_DATA_PREDICATE)
            self.assertEqual(e['profile_overrides']['predicateId'], runner.EXPERIMENTAL_DATA_PREDICATE)
        base = prof.load_profile(PROFILE, DATA)
        self.assertNotEqual(base['parameters']['predicateId'], runner.EXPERIMENTAL_DATA_PREDICATE)
        for e in plan(OPEN_WEIGHTS, repetitions=1):
            self.assertNotIn('predicateId', e['profile_overrides'])

    def test_expected_purchases(self):
        data = prof.load_profile(PROFILE, DATA)
        horizon = prof.case_horizon(data)
        # H n = 7: rate 0.35 over the hold period and five windows, doubled.
        end = dict(rule='honest_windows', windows=5, window_blocks=60000, start_offset=60000)
        self.assertEqual(runner.expected_purchases('honest', dict(Lambda_cheater=0.35), data, end),
                         int(2 * 0.35 * 360000) + 100)
        end = dict(rule='finite_attack', m=25, hold_blocks=60000, case_horizon=horizon)
        self.assertEqual(runner.expected_purchases('finite', dict(Lambda_cheater=0.05), data, end),
                         int(2 * (25 + 0.05 * (60000 + horizon))) + 100)
        # Cheater: ten times 1/p (p = 0.04) plus a case horizon of sales, per episode.
        end = dict(rule='episodes', count=2)
        self.assertEqual(runner.expected_purchases('cheater', dict(Lambda_cheater=0.0), data, end), 2 * 2 * 250 + 100)
        end = dict(rule='worst_path_cases', count=30)
        self.assertEqual(runner.expected_purchases('availability', dict(Lambda_cheater=0.05), data, end),
                         2 * 3000 + 100)

    def test_harness_violations(self):
        ow = prof.load_profile(PROFILE, OPEN_WEIGHTS)
        # At the open-weights bonds a verifier at minVerifierBond is assignable, so fewer assignable
        # verifiers than minVerifiers cannot be registered.
        self.assertTrue(any('would be assignable' in v for v in prof.harness_violations(ow, prof.harness(ow, 1, 9))))
        self.assertEqual(prof.harness_violations(ow, prof.harness(ow, 1, 40)), [])
        data = prof.load_profile(PROFILE, DATA)
        low = dict(prof.harness(data, 1, 9), verifierBondAtomic='3019999')
        self.assertTrue(any('below the assignable floor' in v for v in prof.harness_violations(data, low)))
        self.assertTrue(prof.harness_violations(data, dict(prof.harness(data, 1, 40), sellerBondScale=0)))


class Analysis(unittest.TestCase):
    def test_finite_and_availability_analysis(self):
        sc = scn.load_scenario(SCENARIO)
        a = sc['analysis']
        fam = a['holm_families']['I6-F12a-finite']
        self.assertEqual((fam['condition'], fam['episode']), ('I6-F12a', 1))
        points = [pt for pt in scn.sweep_points(sc) if pt['cell'] in fam['cells']]
        self.assertEqual(len(points), 9)
        self.assertEqual(a['conditions']['I6-F12b']['cells'], ['F-exit'])
        self.assertEqual(a['conditions']['I6-V']['descriptive_cells'], ['V-9', 'V-12', 'V-20', 'V-40'])
        self.assertNotIn('cells', a['conditions']['I6-V'])
        threshold = a['conditions']['I6-F8']['threshold']
        self.assertIn('p <= W*1e-6', threshold)
        self.assertIn('p <= 0.001', threshold)
        # The F cells stay out of the F1, F4, F5 and F10 families.
        for name, f in a['holm_families'].items():
            if f['condition'] in ('I6-F1', 'I6-F4', 'I6-F5', 'I6-F10'):
                self.assertFalse({'F-switch', 'F-stop', 'F-exit'} & set(f['cells']), name)


class Fixtures(unittest.TestCase):
    def test_directive_fixtures_are_in_sync(self):
        want = expected_fixtures()
        if os.environ.get('FAIRBIND_WRITE_I6_FIXTURES') == '1':
            FIXTURES.mkdir(parents=True, exist_ok=True)
            for stale in filter(generated, FIXTURES.glob('*.json')):
                if stale.name not in want:
                    stale.unlink()
            for name, text in want.items():
                (FIXTURES / name).write_text(text)
        have = {p.name: p.read_text() for p in filter(generated, FIXTURES.glob('*.json'))}
        self.assertEqual(sorted(have), sorted(want), 'regenerate with FAIRBIND_WRITE_I6_FIXTURES=1 make i6-check')
        for name in want:
            self.assertEqual(have[name], want[name], f'{name}: regenerate with FAIRBIND_WRITE_I6_FIXTURES=1')

    def test_fixture_names_carry_their_process(self):
        """The Go test reads each generated file for the process that ends its name."""
        for name, text in expected_fixtures().items():
            self.assertTrue(generated(Path(name)), name)
            proc = name[:-len('.json')].rsplit('-', 1)[1]
            self.assertIn(proc, ('verifier', 'seller', 'keeper', 'buyer'), name)
            for other in ('verifier', 'seller', 'keeper', 'buyer'):
                if other != proc:
                    self.assertNotIn({'verifier': 'judgment_injection', 'seller': 'seller_policy',
                                      'keeper': 'keeper_delay', 'buyer': 'workload'}[other], json.loads(text), name)

    def test_fixtures_cover_every_block_shape(self):
        names = expected_fixtures()
        docs = {n: json.loads(t) for n, t in names.items()}
        blocks = collections.Counter(b for d in docs.values() for b in d)
        for block in ('judgment_injection', 'seller_policy', 'keeper_delay', 'workload', 'clock', 'worst_path',
                      'finite_attack'):
            self.assertIn(block, blocks)
        rules = {d['workload']['end']['rule'] for d in docs.values() if 'workload' in d}
        self.assertEqual(rules, {'episodes', 'finite_attack', 'honest_windows', 'worst_path_cases'})
        self.assertEqual({d['seller_policy']['role'] for d in docs.values() if 'seller_policy' in d},
                         {'cheater', 'honest', 'finite'})
        self.assertEqual({(d['seller_policy']['reentry'], d['seller_policy']['top_up'])
                          for d in docs.values() if 'seller_policy' in d},
                         {('top_up_to_scale_then_reinstate', 'before_reentry_to_scale'),
                          ('top_up_to_scale_then_reinstate', 'after_each_deduction_to_scale'), ('none', 'none')})
        self.assertEqual({d['keeper_delay']['path'] for d in docs.values() if 'keeper_delay' in d},
                         {'normal', 'worst'})
        self.assertEqual({d['judgment_injection']['honest_error_off'] for d in docs.values()
                          if 'judgment_injection' in d}, {True, False})


if __name__ == '__main__':
    unittest.main()
