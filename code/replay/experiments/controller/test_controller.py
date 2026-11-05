import contextlib
import copy
import hashlib
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from controller import baselines as bl
from controller import faults, finiteattack, runner
from controller import operating_point as opt
from controller import profile as prof
from controller import scenario as scn
from controller import yamlsubset
from controller import worstpath
from controller.__main__ import main

SCENARIOS = runner.ROOT / 'experiments' / 'scenarios'
PROFILE = runner.ROOT / 'profiles' / 'local-evaluation-v1.json'

try:
    import yaml
except ImportError:
    yaml = None


def base_profile():
    return prof.load_profile(PROFILE, 'data-api-fast-v1')


def op_with_l_actual(blocks=None, min_blocks=None):
    """The operating point with L_actual_blocks recorded for both profiles (the D2 dry run value):
    `blocks` the largest path length, `min_blocks` the smallest (default: the same)."""
    op = opt.load()
    for name, entry in op['profiles'].items():
        value = blocks if blocks is not None else entry['caseHorizon_blocks']['value'] - 1000
        low = min_blocks if min_blocks is not None else value
        entry['L_actual_blocks'] = dict(entry['L_actual_blocks'], value=value, min=low)
    return op


def op_without_l_actual():
    """The operating point before the worst path was measured (L_actual_blocks null)."""
    op = opt.load()
    for entry in op['profiles'].values():
        entry['L_actual_blocks'] = dict(entry['L_actual_blocks'], value=None)
    return op


# The recorded measurement (contracts/test/WorstPathLength.t.sol).
L_ACTUAL_RECORDED = {'data-api-fast-v1': 29680, 'open-weights-standard-v1': 91180}
L_ACTUAL_CELLS = ('M4-worst', 'P5-over', 'P5-short-hold')


def dry_run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(['--dry-run', *args])
    return code, json.loads(out.getvalue())


class ScenarioFiles(unittest.TestCase):
    def test_all_files_validate(self):
        scenarios = scn.load_all(SCENARIOS)
        self.assertEqual([s['id'] for s in scenarios],
                         sorted(['A1', 'A2', 'C1', 'H1', 'I1', 'I2', 'I6', 'K1', 'K2', 'R2', 'D1', 'D2', 'D3', 'D5', 'E1', 'F1', 'F2', 'F3', 'F4', 'S1', 'S2', 'S3',
                                 'S4', 'S5', 'S6', 'V1', 'V2', 'V3']))

    def test_files_are_ascii_english(self):
        for path in list(SCENARIOS.glob('*.yaml')) + [SCENARIOS / 'README.md']:
            path.read_bytes().decode('ascii')

    @unittest.skipIf(yaml is None, 'PyYAML not installed')
    def test_fallback_parser_matches_pyyaml(self):
        for path in SCENARIOS.glob('*.yaml'):
            text = path.read_text()
            self.assertEqual(yamlsubset.parse_subset(text), yaml.safe_load(text), path.name)

    def test_load_without_pyyaml(self):
        saved = yamlsubset._yaml
        yamlsubset._yaml = None
        try:
            self.assertEqual(len(scn.load_all(SCENARIOS)), 28)
        finally:
            yamlsubset._yaml = saved

    def test_fallback_parser_rejects_unsupported_yaml(self):
        for text in ('a: &x 1', 'a: [1, 2]', 'a:\n- b: 1', 'a: 1\na: 2', 'a: |\n  text', 'a:\n\tb: 1'):
            with self.assertRaises(ValueError, msg=text):
                yamlsubset.parse_subset(text)
        self.assertEqual(yamlsubset.parse_subset("a:\n  b: 'x: y'\n  c:\n  - 1.5\n  - false\n  d: ''"),
                         {'a': {'b': 'x: y', 'c': [1.5, False], 'd': ''}})

    def test_invalid_scenarios_are_rejected(self):
        good = scn.load_scenario(SCENARIOS / 'V1.yaml')
        good = {k: v for k, v in good.items() if not k.startswith('_')}
        cases = {
            'property': dict(property_under_test=['X9']),
            'kind': dict(injected_fault=dict(good['injected_fault'], kind='unplug')),
            'process': dict(injected_fault=dict(good['injected_fault'], process='oracle')),
            'default': dict(parameters={'judgeBlocks': {'sweep': [1]}}),
            'metrics': dict(observed_metrics=dict(good['observed_metrics'], core=['double_settlement_rate'])),
            'language': dict(notes='\uac80\uc99d\uc790 \ud0dc\ub9cc'),
            'extra': dict(owner='someone'),
        }
        for name, change in cases.items():
            self.assertTrue(scn.validate(dict(good, **change), 'V1'), name)
        self.assertEqual(scn.validate(good, 'V1'), [])
        self.assertTrue(scn.validate(good, 'V2'))


class Resolution(unittest.TestCase):
    def test_local_profile_arithmetic(self):
        p = base_profile()
        self.assertEqual(prof.judgment_delay(p), 9380)
        self.assertEqual(prof.case_horizon(p), 58994)
        self.assertEqual(prof.penalty_floor(p), 10000 * 25)
        self.assertEqual(prof.penalty_floor(p, defer_blocks=0), 10000 * (25 + 563))
        # kappa_Sigma enters as T_catch + kappa - T_hold: a hold of L with kappa = 1000 needs the
        # same rate term as a hold of L - 1000 without keeper delay.
        self.assertEqual(prof.penalty_floor(p, defer_blocks=9380, keeper_delay_sum=1000),
                         prof.penalty_floor(p, defer_blocks=8380))
        self.assertGreater(prof.penalty_floor(p, defer_blocks=9380, keeper_delay_sum=1000), 10000 * 25)
        self.assertEqual(prof.penalty_floor(p, keeper_delay_sum=1000), 10000 * 25)
        self.assertEqual(prof.admissibility(p), [])

    def test_verifier_count_margin(self):
        p = base_profile()
        self.assertEqual(p['parameters']['minVerifiers'], 3 * p['parameters']['maxAssignments'] + 5)
        p['parameters']['minVerifiers'] -= 1
        self.assertEqual(prof.admissibility(p), ['minVerifiers >= 3 * maxAssignments + 5'])

    def test_disabled_cap_keeps_rate_condition(self):
        p = base_profile()
        prof.disable_cap(p)
        self.assertEqual(prof.admissibility(p), [])
        self.assertGreater(p['parameters']['bucketCapacity'], 10**6)

    def test_sweep_expansion(self):
        counts = {s['id']: len(scn.sweep_points(s)) for s in scn.load_all(SCENARIOS)}
        self.assertEqual((counts['F2'], counts['D1'], counts['D2'], counts['D3'], counts['S6'], counts['A1'], counts['V1']),
                         (6, 12, 6, 24, 6, 3, 6))

    GRID = {'L_min/2': 584, 'L_min': 1168, 'delta_F': 3971, '(delta_F+L)/2': 6675, 'L': 9380,
            'caseHorizon': 58994}

    def test_deferral_grid_values(self):
        sc = scn.load_scenario(SCENARIOS / 'D1.yaml')
        self.assertEqual(sc['parameters']['D_holding_blocks']['sweep'], list(self.GRID))
        base = base_profile()
        seen = {}
        for pt in scn.sweep_points(sc):
            r = scn.resolve(sc, pt, base)
            seen.setdefault(pt['D_holding_blocks'], []).append(r)
            self.assertEqual(r['unresolved'], [])
            self.assertAlmostEqual(r['parameters']['Lambda_cheater'], 4201 * 2 / 3600)
        self.assertEqual({k: v[0]['requested_D_holding_blocks'] for k, v in seen.items()}, self.GRID)
        for expr, (on, off) in seen.items():
            self.assertTrue(on['parameters']['cap_enabled'])
            self.assertFalse(off['parameters']['cap_enabled'])
            # The penalty is the floor of the deployed profile, so with the cap off it is sized
            # for the uncapped rate fields (the override build still enforces the floor).
            for r in (on, off):
                self.assertEqual(r['parameters']['P_S_reserve'], prof.penalty_floor(r['profile']))
                self.assertNotIn('sellerPenalty >= expectedPenaltyFloor', r['inadmissible'])
            self.assertEqual(off['profile']['parameters']['maxRatePpmPerBlock'], prof.UINT32_MAX)
            if on['requested_D_holding_blocks'] >= 9380:
                self.assertEqual(off['parameters']['P_S_reserve'], on['parameters']['P_S_reserve'])
            else:
                self.assertGreater(off['parameters']['P_S_reserve'], on['parameters']['P_S_reserve'])

    def test_open_weights_grid(self):
        op = opt.load()
        base = prof.load_profile(PROFILE, 'open-weights-standard-v1')
        sc = scn.load_scenario(SCENARIOS / 'D1.yaml')
        got = sorted({scn.resolve(sc, pt, base, op=op)['requested_D_holding_blocks'] for pt in scn.sweep_points(sc)})
        self.assertEqual(got, [1334, 2668, 18003, 29707, 41412, 130526])

    def test_override_lowers_only_retention_and_claim_window(self):
        base = base_profile()
        bp = base['parameters']
        for sid in ('D1', 'D2', 'D3', 'E1'):
            sc = scn.load_scenario(SCENARIOS / f'{sid}.yaml')
            for r in (scn.resolve(sc, pt, base) for pt in scn.sweep_points(sc)):
                D = r['requested_D_holding_blocks']
                p = r['profile']['parameters']
                self.assertEqual((p['failureWindowBlocks'], p['inconclusiveWindowBlocks']),
                                 (bp['failureWindowBlocks'], bp['inconclusiveWindowBlocks']), sid)
                if D < prof.case_horizon(r['profile']):
                    for field in prof.D_SWEEP_FIELDS:
                        self.assertEqual(p[field], D, field)
                    self.assertTrue(r['override_used'])
                    self.assertEqual(r['override_skipped_checks'], list(prof.OVERRIDE_SKIPPED_CHECKS))
                    self.assertEqual(r['effective_hold_period_blocks'], D)
                    self.assertTrue(set(r['inadmissible']) <= set(prof.OVERRIDE_SKIPPED_CHECKS), r['inadmissible'])
                    self.assertIn('retentionBlocks >= caseHorizon', r['inadmissible'])
                    self.assertEqual(r['blocked'], [])
                else:
                    self.assertFalse(r['override_used'])
                    self.assertEqual(r['override_skipped_checks'], [])
                    self.assertEqual(r['inadmissible'], [])
                    self.assertEqual(r['effective_hold_period_blocks'], 60000)
                    for field in prof.D_SWEEP_FIELDS:
                        self.assertEqual(p[field], bp[field])

    def test_falsifiability_points(self):
        sc = scn.load_scenario(SCENARIOS / 'D3.yaml')
        base = base_profile()
        points = [scn.resolve(sc, pt, base) for pt in scn.sweep_points(sc)]
        self.assertEqual(len(points), 24)
        for r in points:
            P, expr = r['parameters'], r['parameter_expressions']
            self.assertEqual((r['unresolved'], r['blocked']), ([], []))
            self.assertFalse(P['cap_enabled'])
            hold = r['effective_hold_period_blocks']
            if expr['Lambda_cheater'] == '1/(10*p*D)':
                # About 2.5 bad sales per hold period; first detection expected after 10 D.
                self.assertAlmostEqual(P['Lambda_cheater'] * hold, 1 / (10 * 0.04))
                self.assertAlmostEqual(1 / (0.04 * P['Lambda_cheater']), 10 * hold)
            else:
                self.assertAlmostEqual(P['Lambda_cheater'], 4201 * 2 / 3600)
            g = P['bad_sale_gain_atomic']
            self.assertIn(g, (10000, 5000))
            self.assertIsInstance(g, int)
            target = P['bond_fraction_of_g_over_p'] * g * 25
            p = r['profile']['parameters']
            self.assertEqual(int(p['sellerPenalty']), P['bond_level_realized_atomic'])
            self.assertEqual(P['bond_level_realized_atomic'], max(25, target))
            self.assertEqual(int(p['maxBadGain']), P['declared_maxBadGain'])
            self.assertNotIn('sellerPenalty >= expectedPenaltyFloor', r['inadmissible'])
            self.assertNotIn('bond_level_realized_atomic', r['directive'])
        levels = {(r['parameters']['bad_sale_gain_atomic'], r['parameters']['bond_level_realized_atomic'])
                  for r in points}
        self.assertEqual(levels, {(10000, 25), (10000, 125000), (10000, 250000),
                                  (5000, 25), (5000, 62500), (5000, 125000)})

    def test_skipped_checks_match_the_override_build(self):
        # The single list must name exactly the checks the test build guards with `strict`.
        core = (runner.ROOT / 'contracts' / 'src' / 'FairBindCore.sol').read_text()
        self.assertIn('(strict && p.deferBlocks < p.retentionBlocks)', core)
        self.assertIn('(strict && p.retentionBlocks < horizon)', core)
        self.assertIn('(strict && p.enforcementBlocks < delay)', core)
        self.assertEqual(core.count('strict &&'), 3)
        for readme in ('experiments/scenarios/README.md', 'experiments/controller/README.md'):
            self.assertIn('OVERRIDE_SKIPPED_CHECKS', (runner.ROOT / readme).read_text(), readme)

    def test_override_blocks_other_violations(self):
        sc = scn.load_scenario(SCENARIOS / 'D1.yaml')
        pt = dict(scn.sweep_points(sc)[0], P_S_reserve=1)
        r = scn.resolve(sc, pt, base_profile())
        self.assertTrue(r['override_used'])
        self.assertTrue(any('still enforces' in b and 'sellerPenalty' in b for b in r['blocked']), r['blocked'])

    def test_d_above_profile_hold_raises_fields_without_override(self):
        sc = scn.load_scenario(SCENARIOS / 'D1.yaml')
        pt = dict(scn.sweep_points(sc)[0], D_holding_blocks='2*caseHorizon')
        r = scn.resolve(sc, pt, base_profile())
        self.assertFalse(r['override_used'])
        self.assertEqual(r['effective_hold_period_blocks'], 2 * 58994)
        self.assertEqual(r['inadmissible'], [])

    def test_non_d_sweep_scenarios_keep_admissible_profile_unflagged(self):
        # S5 and S6 do not set D_holding_blocks and must be unaffected by the D-sweep transform.
        base = base_profile()
        for sid in ('S5', 'S6'):
            sc = scn.load_scenario(SCENARIOS / f'{sid}.yaml')
            for pt in scn.sweep_points(sc):
                r = scn.resolve(sc, pt, base)
                self.assertFalse(r['override_used'], sid)
                self.assertIsNone(r['requested_D_holding_blocks'], sid)

    def test_disable_cap_sets_documented_values(self):
        p = base_profile()
        prof.disable_cap(p)
        params = p['parameters']
        self.assertEqual(params['maxRatePpmPerBlock'], prof.UINT32_MAX)
        self.assertEqual(params['refillPpmPerBlock'], prof.UINT32_MAX // 2)
        self.assertGreaterEqual(params['enforcementBlocks'], prof.judgment_delay(p))
        self.assertEqual(params['bucketCapacity'],
                         min(prof.UINT32_MAX, (prof.UINT32_MAX - prof.UINT32_MAX // 2)
                             * params['enforcementBlocks'] // prof.PPM))
        self.assertEqual(prof.admissibility(p), [])

    def test_deadline_sweep_keeps_profile_admissible(self):
        sc = scn.load_scenario(SCENARIOS / 'S1.yaml')
        r = scn.resolve(sc, scn.sweep_points(sc)[-1], base_profile())
        self.assertEqual(r['profile']['parameters']['epochBlocks'], 1800)
        self.assertEqual(r['inadmissible'], [])

    def test_baselines_are_blocked(self):
        code, doc = dry_run('--only', 'D5,S6')
        blocked = {e['run_id']: e['blocked_reasons'] for e in doc['plan'] if not e['runnable']}
        self.assertEqual(len([r for r in blocked if r.startswith('D5')]), 15 * 10)
        self.assertEqual(len([r for r in blocked if r.startswith('S6')]), 0)
        _, doc = dry_run('--only', 'D5,S6', '--run-list', 'main', '--repetitions', '1')
        blocked = [e for e in doc['plan'] if not e['runnable']]
        self.assertEqual(sorted({e['arm'] for e in blocked}), ['B1', 'B4', 'B6', 'B7a', 'B7b'])
        self.assertTrue(all(e['baseline']['id'] == e['arm'] for e in blocked))


class ScenarioSemantics(unittest.TestCase):
    def resolved(self, sid, op=None):
        sc = scn.load_scenario(SCENARIOS / f'{sid}.yaml')
        return sc, [scn.resolve(sc, pt, base_profile(), op=op) for pt in scn.sweep_points(sc)]

    def test_every_point_resolves(self):
        for sc in scn.load_all(SCENARIOS):
            for pt in scn.sweep_points(sc):
                r = scn.resolve(sc, pt, base_profile())
                self.assertEqual(r['unresolved'], [], sc['id'])
                if sc['id'] != 'D5':
                    self.assertEqual(r['blocked'], [], sc['id'])

    def test_e1_uses_profile_appeal_window_and_keeps_upheld_runs(self):
        sc, points = self.resolved('E1')
        self.assertEqual(sc['parameters']['appealBlocks']['default'], 'profile_default')
        self.assertEqual(sorted({r['parameters']['second_verifier_wrong'] for r in points}), [False, True])
        for r in points:
            self.assertNotIn('deadlineConfig.appealBlocks', r['profile_overrides'])
            self.assertEqual(r['profile']['parameters']['deadlineConfig']['appealBlocks'], 1800)
            self.assertEqual(r['judgment_delay_blocks'], 9380)
        self.assertEqual(sorted({r['requested_D_holding_blocks'] for r in points}),
                         [584, 1168, 3971, 6675, 9380, 58994])
        self.assertNotIn('invalid', sc['expected_outcome'] + sc['pass_criteria'])
        self.assertIn('wrongful_final_fail_count', scn.metric_names(sc))
        self.assertIn('first_fail_to_freeze_blocks', scn.metric_names(sc))

    def test_s5_s6_run_the_admissible_profile(self):
        for sid in ('S5', 'S6'):
            sc, points = self.resolved(sid)
            self.assertNotIn('bond_regime', sc['parameters'])
            for r in points:
                self.assertFalse(r['override_used'])
                self.assertEqual(r['inadmissible'], [])
        sc, _ = self.resolved('S5')
        self.assertIn('enforcementBlocks', sc['pass_criteria'])
        self.assertIn('achieved_settlement_rate', scn.metric_names(sc))
        sc, _ = self.resolved('S6')
        self.assertIn('seller_penalty_charged == 0', sc['pass_criteria'])

    def test_v1_seller_branch_reaches_the_seller(self):
        _, doc = dry_run('--only', 'V1', '--repetitions', '1')
        values = set()
        for e in doc['plan']:
            self.assertIn('seller', e['directives'])
            values.add(e['directives']['seller']['parameters']['seller_publishes'])
        self.assertEqual(values, {True, False})

    def test_new_scenario_parameters(self):
        _, c1 = self.resolved('C1')
        bonds = {r['parameters']['bond_level_realized_atomic'] for r in c1}
        self.assertEqual(bonds, {250000, 16 * 250000})
        slow = [r['parameters']['Lambda_cheater'] for r in c1
                if r['parameter_expressions']['Lambda_cheater'] == '1/(10*p*D)']
        self.assertEqual(len(slow), 2)
        for rate in slow:
            self.assertAlmostEqual(rate, 1 / (10 * 0.04 * 60000))
        sc_k1, k1 = self.resolved('K1')
        self.assertEqual(sorted({r['parameters']['outage_blocks'] for r in k1}), [100, 1000, 9380])
        self.assertEqual({r['parameters']['variant'] for r in k1}, {'all_keepers_down', 'review_seal_delayed'})
        # The delayed review seal lands past the seal window and the 256-block blockhash window (ADR 0021).
        self.assertTrue(all(r['parameters']['review_seal_delay_blocks'] > max(256, 200) for r in k1))
        self.assertIn('review_reseal_count', scn.metric_names(sc_k1))
        _, h1 = self.resolved('H1')
        rates = sorted(round(r['parameters']['Lambda_honest'] * 1800, 6) for r in h1)
        self.assertEqual(rates, [556.8, 4201])
        self.assertEqual({(r['parameters']['alpha'], r['parameters']['c'], r['parameters']['h_honest_bond_fraction'])
                          for r in h1}, {(0.01, 0.1, 0.67)})
        _, d5 = self.resolved('D5')
        hours = sorted({round(r['parameters']['L_judgment_delay_hours'], 2) for r in d5})
        self.assertEqual(hours, [5.21, 23.01, 48, 144, 1000])
        self.assertEqual({r['parameters']['window_reading'] for r in d5},
                         {'challenge_24h', 'challenge_72h', 'refund_30d'})
        _, a2 = self.resolved('A2')
        self.assertEqual(sorted({r['parameters']['colluding_weight'] for r in a2}), [0.0, 0.1, 0.33])
        self.assertEqual(sorted({r['parameters']['dispute_count'] for r in a2}), [1, 10, 100, 1000])
        self.assertIn('buyer_deposit_loss', scn.metric_names(self.resolved('A2')[0]))
        self.assertIn('attacker_refund_gain', scn.metric_names(self.resolved('A2')[0]))
        _, r2 = self.resolved('R2')
        self.assertEqual(len(r2), 6)

    def test_i6_hold_period_grid(self):
        """The I6 cells of the V2 review: partial grids M1 to M4, P1 to P6 and the honest arm H,
        with the worst-path positive controls; every point resolves and none is blocked."""
        # Without L_actual the L_actual-relative cells are unresolved; the rest resolve.
        _, pending = self.resolved('I6', op_without_l_actual())
        self.assertEqual(sorted({r['parameters']['cell'] for r in pending if r['unresolved']}),
                         sorted(L_ACTUAL_CELLS))
        # The recorded value resolves them: M4-worst keeper delay T_hold - L_actual.
        op = opt.load()
        for name, value in L_ACTUAL_RECORDED.items():
            self.assertEqual(op['profiles'][name]['L_actual_blocks']['value'], value)
            self.assertEqual(op['profiles'][name]['L_actual_blocks']['min'], value)
            self.assertLessEqual(value, op['profiles'][name]['caseHorizon_blocks']['value']
                                 - prof.load_profile(PROFILE, name)['parameters']['marginBlocks'])
        _, recorded = self.resolved('I6')
        for r in recorded:
            self.assertEqual((r['unresolved'], r['blocked']), ([], []), r['parameters']['cell'])
            if r['parameters']['cell'] == 'M4-worst':
                self.assertEqual(r['parameters']['keeper_delay_budget_blocks'], 60000 - 29680)
        l_actual = 57000
        sc, points = self.resolved('I6', op_with_l_actual(l_actual))
        self.assertEqual(len(points), 71 + 9 + 4)
        by_cell = {}
        for r in points:
            by_cell.setdefault(r['parameters']['cell'], []).append(r)
            self.assertEqual((r['unresolved'], r['blocked']), ([], []), r['parameters']['cell'])
            self.assertNotIn('exact_hold', r['directive'])
            self.assertNotIn('cell', r['directive'])
        self.assertEqual({k: len(v) for k, v in by_cell.items()},
                         {'M1-low-admissible': 2, 'M1-low-comparison': 5, 'M1-high-admissible': 4,
                          'M1-high-comparison': 10, 'M2-low': 6, 'M2-high': 12, 'M3-low': 1, 'M3-high': 2,
                          'M4': 2, 'M4-worst': 2, 'P1-low': 2, 'P1-high': 2, 'P2-within-low': 2, 'P2-within-high': 2,
                          'P2-over-case-low': 1, 'P2-over-case-high': 1, 'P2-over-hold-low': 1,
                          'P2-over-hold-high': 1, 'P3': 2, 'P4-low': 2, 'P4-high': 2, 'P5-margin': 1,
                          'P5-over': 1, 'P5-short-hold': 1, 'P6': 1, 'H': 3,
                          'F-switch': 3, 'F-stop': 3, 'F-exit': 3, 'V-9': 1, 'V-12': 1, 'V-20': 1, 'V-40': 1})
        holds = sorted({(r['requested_D_holding_blocks'], r['override_used']) for r in points})
        self.assertEqual(holds, [(584, True), (1168, True), (3971, True), (6675, True), (9380, True),
                                 (l_actual - 100, True), (58994, False), (60000, False)])
        # M4: the admissible profile with the cap off, at the bucket rate and ten times it.
        m4 = by_cell['M4']
        for r in m4:
            self.assertFalse(r['override_used'])
            self.assertEqual(r['inadmissible'], [])
            self.assertEqual(r['profile']['parameters']['maxRatePpmPerBlock'], 4294967295)
        self.assertEqual(sorted(r['parameters']['Lambda_cheater'] for r in m4), [0.05, 0.5])
        # M4-worst: the same on the worst path, keeper delay T_hold - L_actual.
        for r in by_cell['M4-worst']:
            self.assertFalse(r['override_used'])
            self.assertEqual(r['inadmissible'], [])
            self.assertEqual(r['profile']['parameters']['maxRatePpmPerBlock'], 4294967295)
            self.assertEqual((r['parameters']['judgment_path'], r['parameters']['keeper_delay_budget_blocks']),
                             ('worst', 60000 - l_actual))
        self.assertEqual(sorted(r['parameters']['Lambda_cheater'] for r in by_cell['M4-worst']), [0.05, 0.5])
        # The positive control below the case horizon keeps the production freeze timing.
        short = by_cell['P5-short-hold'][0]
        self.assertTrue(short['override_used'])
        self.assertFalse(short['profile']['parameters']['freezeOnInitialFail'])
        self.assertEqual(short['parameters']['judgment_path'], 'worst')
        for r in points:
            if r['parameters']['cell'] != 'P5-short-hold':
                self.assertEqual(r['profile']['parameters']['freezeOnInitialFail'], r['override_used'])
        # The corner cell: scale 7 at the margin on the worst path, at 7 * r_fill.
        corner = by_cell['P6'][0]['parameters']
        self.assertEqual((corner['scale_factor'], corner['keeper_delay_budget_blocks'], corner['judgment_path']),
                         (7, 1006, 'worst'))
        self.assertAlmostEqual(corner['Lambda_cheater'], 0.35)
        self.assertEqual(by_cell['P5-over'][0]['parameters']['keeper_delay_budget_blocks'], 60000 - l_actual + 100)
        self.assertEqual(short['effective_hold_period_blocks'], l_actual - 100)
        # With a spread in the dry run the positive controls use the shortest path and
        # M4-worst the longest.
        _, spread = self.resolved('I6', op_with_l_actual(57000, 56000))
        cells = {r['parameters']['cell']: r for r in spread}
        self.assertEqual(cells['P5-over']['parameters']['keeper_delay_budget_blocks'], 60000 - 56000 + 100)
        self.assertEqual(cells['P5-short-hold']['effective_hold_period_blocks'], 56000 - 100)
        self.assertEqual(cells['M4-worst']['parameters']['keeper_delay_budget_blocks'], 60000 - 57000)
        with self.assertRaises(opt.OperatingPointError):
            opt.symbols(op_with_l_actual(56000, 57000), 'data-api-fast-v1')
        self.assertEqual(sorted(r['parameters']['keeper_delay_budget_blocks'] for r in by_cell['P2-within-low']), [503, 1006])
        # Honest arm: fixed top-up policy, three scales.
        for r in by_cell['H']:
            self.assertEqual(r['directive']['seller_role'], 'honest')
            self.assertEqual(r['directive']['honest_top_up_policy'], 'after_each_deduction_to_scale')
        self.assertEqual(sorted(r['parameters']['scale_factor'] for r in by_cell['H']), [1, 3, 7])
        g_over_p = 250000
        self.assertEqual(sorted({r['parameters']['bond_level_realized_atomic'] for r in points
                                 if r['requested_D_holding_blocks'] >= 9380}),
                         [25, g_over_p // 2, g_over_p, 16 * g_over_p // 2, 16 * g_over_p])
        # 16 * g/(2p): P3 at g = v/2 and B = k * g * ceil(1/p).
        for column in ('released_exposure', 'second_episode_exposure', 'second_episode_net_gain',
                       'post_detection_leak', 'releases_after_reentry', 'realized_detection_rate',
                       'keeper_delay_sum_max_blocks', 'honest_top_up_count', 'worst_path_case_blocks',
                       'case_path_blocks', 'case_path_minus_keeper', 'first_detection_index'):
            self.assertIn(column, scn.metric_names(sc))
        analysis = sc['analysis']
        self.assertIn('I6-F10', analysis['conditions'])
        for cid in ('I6-F11a', 'I6-F11b'):
            self.assertIn('M4-worst', analysis['conditions'][cid]['cells'])
        self.assertIn('T_case - marginBlocks', analysis['conditions']['I6-F11a']['threshold'])
        self.assertNotIn('I6-F11', analysis['conditions'])
        # The worst-path cells detect every sampled bad sale: descriptive for F10, out of its family.
        worst_cells = ['M4-worst', 'P5-margin', 'P6']
        self.assertEqual(analysis['conditions']['I6-F10']['descriptive_cells'], worst_cells)
        f10 = analysis['holm_families']['I6-F10-admissible']['cells']
        self.assertFalse(set(worst_cells) & set(f10) | set(worst_cells) & set(analysis['conditions']['I6-F10']['cells']))
        self.assertEqual(sum(len(by_cell[c]) for c in f10), 40)
        self.assertIn('27 of 30', analysis['conditions']['I6-PC']['threshold'])
        self.assertIn('every run', analysis['conditions']['I6-PC']['threshold'])
        self.assertEqual(analysis['pruning']['min_repetitions'], 60)
        for name, fam in analysis['holm_families'].items():
            if fam.get('rate_class'):
                for c in fam['cells']:
                    self.assertEqual(sc['cells'][c]['rate_class'], fam['rate_class'], name)
        # The plan: P4 runs only under the open-weights profile; cells carry their repetitions.
        _, doc = dry_run('--run-list', 'hold-period-grid', '--only', 'I6', '--repetitions', '1')
        self.assertEqual(doc['runs'], 67 + 9 + 4)
        blocked = sorted({e['cell']['name'] for e in doc['plan'] if not e['runnable']})
        self.assertEqual(blocked, [])
        # Without the recorded L_actual the cells defined relative to it are blocked.
        with tempfile.TemporaryDirectory() as tmp:
            pending_path = Path(tmp) / 'operating-point.json'
            pending_path.write_text(json.dumps(op_without_l_actual()))
            _, pending_doc = dry_run('--run-list', 'hold-period-grid', '--only', 'I6', '--repetitions', '1',
                                     '--operating-point', str(pending_path))
        blocked = sorted({e['cell']['name'] for e in pending_doc['plan'] if not e['runnable']})
        self.assertEqual(blocked, sorted(L_ACTUAL_CELLS))
        _, full = dry_run('--run-list', 'hold-period-grid', '--only', 'I6')
        expected = sum(sc['cells'][r['parameters']['cell']]['repetitions'] for r in points
                       if not r['parameters']['cell'].startswith('P4'))
        self.assertEqual(full['runs'], expected)
        _, ow = dry_run('--run-list', 'hold-period-grid', '--only', 'I6', '--repetitions', '1',
                        '--profile-name', 'open-weights-standard-v1')
        self.assertEqual(ow['runs'], 4)

    def test_worst_path_directives(self):
        """judgment_path worst gives every process on the case its worst-path directive; the
        schedule's spent terms and the unspent margin sum to the case horizon."""
        for name, horizon in (('data-api-fast-v1', 58994), ('open-weights-standard-v1', 130526)):
            p = prof.load_profile(PROFILE, name)
            s = worstpath.schedule(p)
            self.assertEqual(s['case_horizon'], horizon)
            self.assertEqual(s['margin_unspent'], p['parameters']['marginBlocks'])
            self.assertEqual(sum(t['blocks'] for t in s['terms']), s['path_budget'])
            self.assertEqual(s['path_budget'] + s['margin_unspent'], prof.case_horizon(p))
            self.assertNotIn('margin', [t['term'] for t in s['terms']])
            self.assertEqual(s['max_replaced_assignments'], p['parameters']['maxAssignments'] - 1)
        _, doc = dry_run('--run-list', 'hold-period-grid', '--only', 'I6', '--repetitions', '1')
        worst = [e for e in doc['plan'] if e['judgment_path'] == 'worst']
        self.assertEqual(sorted(e['cell']['name'] for e in worst), ['M4-worst', 'M4-worst', 'P5-margin', 'P5-over', 'P5-short-hold', 'P6',
                                                                   'V-12', 'V-20', 'V-40', 'V-9'])
        for e in worst:
            for proc in ('verifier', 'seller', 'keeper', 'buyer'):
                self.assertEqual(e['directives'][proc]['worst_path']['judgment_path'], 'worst', proc)
            self.assertEqual(e['directives']['verifier']['worst_path']['tiebreak_verdict'], 'FAIL')
            self.assertEqual(e['directives']['verifier']['worst_path']['applies_to'], 'every sampled bad sale')
            self.assertIn('timeoutEvidence', e['directives']['verifier']['worst_path']['initial_non_last_assignments'])
            self.assertFalse(e['directives']['verifier']['worst_path']['disclose_evidence_on_initial_non_last_assignments'])
            self.assertNotIn('disclose_evidence_on_initial_non_last_assignments', e['directives']['seller']['worst_path'])
            self.assertEqual(e['directives']['seller']['worst_path']['anchor_at'], 'anchor_deadline')
            # The buyer must not turn the sampled case into a dispute (openSample would revert).
            buyer = e['directives']['buyer']['worst_path']
            self.assertEqual((buyer['dispute_sampled_sale'], buyer['claim_at']), (False, 'after_case_final'))
            self.assertEqual(e['worst_path_schedule']['case_horizon'], 58994)
        # The keeper delay is a per-case budget spent on the last keeper call before the
        # confirmed failure; every other keeper call is prompt. A normal-path keeper without a
        # budget receives no block (test_i6_plan).
        for e in doc['plan']:
            if 'keeper_delay' not in e['directives']['keeper']:
                continue
            block = e['directives']['keeper']['keeper_delay']
            self.assertEqual(block['path'], e['judgment_path'])
            self.assertEqual(block['budget_blocks'], e['parameters']['keeper_delay_budget_blocks'])
            self.assertEqual(block['expected_kappa_sigma'], block['budget_blocks'])
            self.assertEqual((block['per'], block['other_calls']), ('case', 'prompt'))
            self.assertIn('last keeper call before the confirmed failure', block['spent_on'])
        with self.assertRaises(ValueError):
            worstpath.keeper_delay(-1)
        controls = [e for e in doc['plan'] if e['cell'] and e['cell']['role'] == 'positive_control']
        self.assertEqual(sorted(e['cell']['name'] for e in controls), ['P5-over', 'P5-short-hold'])
        normal = [e for e in doc['plan'] if e['judgment_path'] == 'normal']
        self.assertTrue(normal and all('worst_path' not in d for e in normal for d in e['directives'].values()))

    def test_cells_and_analysis_are_validated(self):
        sc = scn.load_scenario(SCENARIOS / 'I6.yaml')
        doc = {k: v for k, v in sc.items() if not k.startswith('_')}
        self.assertEqual(scn.validate(doc, 'I6'), [])
        import copy
        bad = copy.deepcopy(doc)
        bad['analysis']['holm_families']['I6-F1-episode1-low']['cells'].append('M4')
        self.assertTrue(any('mixes rate class' in e for e in scn.validate(bad, 'I6')))
        bad = copy.deepcopy(doc)
        bad['analysis']['conditions']['I6-F10']['cells'].append('nope')
        self.assertTrue(any('unknown cell nope' in e for e in scn.validate(bad, 'I6')))
        bad = copy.deepcopy(doc)
        bad['cells']['M4']['set']['undeclared'] = 1
        self.assertTrue(any('undeclared parameter' in e for e in scn.validate(bad, 'I6')))
        bad = copy.deepcopy(doc)
        bad['analysis']['pruning']['order'].append('M4')
        self.assertTrue(any('not a low-rate cell' in e for e in scn.validate(bad, 'I6')))
        bad = copy.deepcopy(doc)
        bad['cells']['P3']['min_repetitions'] = 200
        self.assertTrue(any('min_repetitions' in e for e in scn.validate(bad, 'I6')))

    def test_new_fault_kinds_have_mechanisms_and_ground_truth(self):
        for kind in ('false_wrong_delivery_collusion', 'verifier_always_inconclusive', 'natural_inconclusive',
                     'keeper_outage', 'seal_withholding', 'reentering_cheater', 'double_refund_attempt',
                     'honest_high_rate'):
            self.assertEqual(scn.FAULT_KINDS[kind], ('directive',))
        self.assertEqual(faults.expected_verdict('false_wrong_delivery_collusion', {}), 'PASS')
        self.assertEqual(faults.expected_verdict('honest_high_rate', {}), 'PASS')

    def test_readme_lists_every_scenario(self):
        text = (SCENARIOS / 'README.md').read_text()
        for sc in scn.load_all(SCENARIOS):
            self.assertIn(f"| {sc['id']} | {sc['name']} |", text)


class RunList(unittest.TestCase):
    def test_main_run_list(self):
        arms = runner.load_run_list('main')
        ids = {s['id'] for s in scn.load_all(SCENARIOS)}
        # The hold-period grid is planned apart and not run with the main run.
        self.assertEqual(set(arms), ids - {'I6'})
        self.assertEqual(runner.load_run_list('hold-period-grid'), {'I6': ['fairbind']})
        known = set(bl.load_all()) | {'fairbind'}
        for sid, names in arms.items():
            self.assertTrue(set(names) <= known, sid)
        self.assertIn('B7a', arms['S5'])
        self.assertIn('B7b', arms['S5'])
        self.assertIn('B7a', arms['S6'])
        self.assertEqual(arms['D5'], ['B6'])
        with self.assertRaises(ValueError):
            runner.load_run_list('nightly')

    def test_run_list_plan(self):
        _, doc = dry_run('--run-list', 'main', '--only', 'S5', '--repetitions', '1')
        by_arm = {}
        for e in doc['plan']:
            by_arm.setdefault(e['arm'], []).append(e)
        self.assertEqual(sorted(by_arm), sorted(runner.load_run_list('main')['S5']))
        self.assertTrue(all(e['runnable'] for e in by_arm['fairbind']))
        for arm, entries in by_arm.items():
            self.assertEqual(len(entries), 8)
            if arm != 'fairbind':
                self.assertTrue(all(e['run_id'].startswith(f'S5-{arm}-') for e in entries))
                self.assertTrue(all(not e['runnable'] and e['baseline']['id'] == arm for e in entries))
        seeds = [e['seed'] for e in doc['plan']]
        self.assertEqual(len(seeds), len(set(seeds)))
        b7a = by_arm['B7a'][0]['baseline']['fairbind_parameters']
        self.assertEqual(b7a['appeal']['windowBlocks'], 9380)

    def test_unknown_arm_is_rejected(self):
        sc = scn.load_scenario(SCENARIOS / 'S5.yaml')
        with self.assertRaises(ValueError):
            runner.build_plan([sc], base_profile(), arms_by_scenario={'S5': ['B9']})


class PlanFields(unittest.TestCase):
    def test_every_plan_entry_carries_the_new_fields(self):
        _, doc = dry_run('--only', 'D1,F3', '--repetitions', '1')
        for e in doc['plan']:
            for key in ('arm', 'n_seeds', 'parameter_expressions', 'operating_point', 'metric_definitions',
                        'override_used', 'override_skipped_checks', 'requested_D_holding_blocks',
                        'effective_hold_period_blocks', 'baseline'):
                self.assertIn(key, e)
            self.assertEqual(e['metric_definitions']['sha256'],
                             hashlib.sha256(scn.METRICS_FILE.read_bytes()).hexdigest())
        d1 = [e for e in doc['plan'] if e['scenario'] == 'D1']
        self.assertEqual({e['parameter_expressions']['D_holding_blocks'] for e in d1},
                         {'L_min/2', 'L_min', 'delta_F', '(delta_F+L)/2', 'L', 'caseHorizon'})

    def test_text_summary_shows_skipped_checks(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(['--dry-run', '--format', 'text', '--only', 'D2', '--repetitions', '1'])
        self.assertIn('skipped checks: retentionBlocks >= caseHorizon', out.getvalue())

    def test_symbols_for_both_profiles(self):
        t = opt.symbols(opt.load(), 'data-api-fast-v1')
        self.assertAlmostEqual(t['L_hours_data_api'], 9380 / 1800)
        self.assertAlmostEqual(t['L_hours_open_weights'], 41412 / 1800)


class Metrics(unittest.TestCase):
    def test_every_metric_is_defined_once(self):
        ids = scn.metric_ids()
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(set(scn.CORE_METRICS) <= set(ids))
        self.assertTrue(set(scn.EXTENDED_METRICS) <= set(ids))
        for name in ('cheater_net_gain', 'sales_lost_while_suspended', 'buyer_recovery_rate',
                     'honest_seller_delay_blocks', 'honest_seller_suspended_fraction', 'frozen_amount',
                     'rejected_settlement_count', 'gas_per_call', 'realized_detection_rate'):
            self.assertIn(name, ids)
        text = scn.METRICS_FILE.read_text()
        text.encode('ascii')
        for line in text.splitlines():
            if line.startswith('| `'):
                cells = [c.strip() for c in line.strip('|').split('|')]
                self.assertEqual(len(cells), 4, line)
                self.assertTrue(all(cells), line)

    def test_scenarios_reference_only_defined_metrics(self):
        ids = set(scn.metric_ids())
        for sc in scn.load_all(SCENARIOS):
            self.assertTrue(set(scn.metric_names(sc)) <= ids, sc['id'])
        good = {k: v for k, v in scn.load_scenario(SCENARIOS / 'V1.yaml').items() if not k.startswith('_')}
        bad = dict(good, observed_metrics=dict(good['observed_metrics'], scenario_specific=['defector_net_gain']))
        self.assertTrue(any('metrics.md' in e for e in scn.validate(bad, 'V1')))
        dup = dict(good, observed_metrics=dict(good['observed_metrics'], scenario_specific=['cheater_net_gain']))
        self.assertTrue(any('repeats' in e for e in scn.validate(dup, 'V1')))

    def test_net_gain_separates_lost_sales(self):
        text = scn.METRICS_FILE.read_text()
        row = next(l for l in text.splitlines() if l.startswith('| `cheater_net_gain`'))
        self.assertIn('minus seller penalties', row)
        self.assertIn('not included', row)


class Randomness(unittest.TestCase):
    def test_every_scenario_states_n_seeds(self):
        for sc in scn.load_all(SCENARIOS):
            self.assertGreaterEqual(sc['n_seeds'], 1, sc['id'])
        self.assertEqual(scn.load_scenario(SCENARIOS / 'D3.yaml')['n_seeds'], 100)
        good = {k: v for k, v in scn.load_scenario(SCENARIOS / 'V1.yaml').items() if not k.startswith('_')}
        for bad in (0, -1, 1.5, True, 'three'):
            self.assertTrue(scn.validate(dict(good, n_seeds=bad), 'V1'), bad)
        missing = {k: v for k, v in good.items() if k != 'n_seeds'}
        self.assertIn('missing field n_seeds', scn.validate(missing, 'V1'))

    def test_plan_repeats_each_point_n_seeds_times_with_distinct_seeds(self):
        sc = scn.load_scenario(SCENARIOS / 'D2.yaml')
        plan = runner.build_plan([sc], base_profile())
        self.assertEqual(len(plan), len(scn.sweep_points(sc)) * sc['n_seeds'])
        self.assertEqual({e['n_seeds'] for e in plan}, {sc['n_seeds']})
        self.assertEqual(len({e['seed'] for e in plan}), len(plan))
        again = runner.build_plan([sc], base_profile())
        self.assertEqual([e['seed'] for e in plan], [e['seed'] for e in again])
        short = runner.build_plan([sc], base_profile(), repetitions=2)
        self.assertEqual(len(short), len(scn.sweep_points(sc)) * 2)
        _, doc = dry_run('--only', 'F1', '--repetitions', '1')
        self.assertEqual(doc['runs'], len(scn.sweep_points(scn.load_scenario(SCENARIOS / 'F1.yaml'))))

    def test_buyer_directive_carries_seed_effects(self):
        plan = runner.build_plan([scn.load_scenario(SCENARIOS / f) for f in ('F1.yaml', 'A1.yaml')], base_profile())
        for e in plan:
            self.assertEqual(e['directives']['buyer']['randomness'], runner.SEED_EFFECTS)
        self.assertEqual(sorted(runner.SEED_EFFECTS), ['buyer_idempotency_key', 'intra_block_order',
                                                       'verifier_behavior_draw'])
        a1 = next(e for e in plan if e['scenario'] == 'A1')
        self.assertEqual(a1['directives']['buyer']['kind'], 'false_non_delivery_claim')

    def test_detection_summary(self):
        profile = base_profile()
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'collector.jsonl').write_text(
                '{"metric": "realized_detection_rate", "value": 0.03}\n'
                '{"metric": "realized_detection_rate", "value": 0.05}\n')
            metrics, _, _ = runner.collect_metrics(d, ['realized_detection_rate', 'realized_sample_rate'])
        s = runner.detection_summary(profile, metrics)
        self.assertEqual((s['expected_p'], s['expected_pi']), (0.04, 0.1))
        self.assertAlmostEqual(s['realized_detection_rate'], 0.04)
        self.assertIsNone(s['realized_sample_rate'])

    def test_sampled_scenarios_report_realized_rates(self):
        for sid in ('D1', 'D2', 'D3', 'E1', 'S5', 'S6', 'V2', 'V3'):
            names = scn.metric_names(scn.load_scenario(SCENARIOS / f'{sid}.yaml'))
            self.assertIn('realized_detection_rate', names, sid)
            self.assertIn('realized_sample_rate', names, sid)


class OperatingPoint(unittest.TestCase):
    def test_file_matches_both_profiles(self):
        op = opt.load()
        for name in ('data-api-fast-v1', 'open-weights-standard-v1'):
            profile = prof.load_profile(PROFILE, name)
            self.assertEqual(opt.check(op, profile), [], name)
        path = runner.ROOT / 'experiments' / 'operating-point.json'
        path.read_bytes().decode('ascii')

    def test_key_values(self):
        op = opt.load()
        t = opt.symbols(op, 'data-api-fast-v1')
        self.assertEqual((t['L'], t['delta_F'], t['L_min'], t['caseHorizon']), (9380, 3971, 1168, 58994))
        self.assertEqual((t['p'], t['pi'], t['h'], t['beta'], t['c'], t['alpha']), (0.04, 0.1, 0.67, 0.05, 0.1, 0.01))
        self.assertEqual((t['g'], t['v'], t['failureLimit'], t['g_over_p']), (10000, 10000, 16, 250000))
        t = opt.symbols(op, 'open-weights-standard-v1')
        self.assertEqual((t['L'], t['delta_F'], t['L_min'], t['caseHorizon'], t['p'], t['failureLimit']),
                         (41412, 18003, 2668, 130526, 0.02, 27))
        named = op['rates']['named']
        self.assertEqual((named['top_seller_14d_mean']['per_hour'], named['peak_hour_max']['per_hour'],
                          named['peak_hour_p99']['per_hour']), (556.8, 4201, 98))
        for entry in named.values():
            self.assertTrue(entry['source'] and entry['status'])
        self.assertEqual(op['prices']['median_price_atomic']['value'], 10000)

    def test_mismatch_is_reported(self):
        op = opt.load()
        profile = base_profile()
        profile['parameters']['deadlineConfig']['judgeBlocks'] = 700
        errors = opt.check(op, profile)
        self.assertTrue(any('L_blocks' in e for e in errors))
        with self.assertRaises(opt.OperatingPointError):
            runner.build_plan(scn.load_all(SCENARIOS)[:1], profile, op=op)

    def test_expressions(self):
        t = opt.symbols(opt.load(), 'data-api-fast-v1')
        self.assertEqual(opt.blocks('L_min/2', t), 584)
        self.assertEqual(opt.blocks('(delta_F+L)/2', t), 6675)
        self.assertEqual(opt.blocks('2*L', t), 18760)
        self.assertEqual(opt.evaluate('g/(2*p)', t), 125000)
        for bad in ('__import__("os")', 'L**2', 'x', 'L if 1 else 0'):
            with self.assertRaises(opt.OperatingPointError, msg=bad):
                opt.evaluate(bad, t)

    def test_no_scenario_carries_its_own_rate_or_old_value(self):
        for path in SCENARIOS.glob('*.yaml'):
            text = path.read_text()
            self.assertNotIn('empirical_seller_rate', text, path.name)
            for old in ('5400', '0.0731', '107.5'):
                self.assertNotIn(old, text, path.name)

    def test_baselines_resolve_from_operating_point(self):
        op = opt.load()
        arms = bl.load_all()
        self.assertEqual(sorted(arms), ['B0a', 'B0b', 'B1', 'B2', 'B4', 'B6', 'B7a', 'B7b'])
        for doc in arms.values():
            self.assertEqual(list(bl.retired_literals(doc)), [], doc['id'])
            self.assertIn('changes_from_source', doc)
            resolved = bl.resolve(doc, op, 'data-api-fast-v1')
            self.assertNotIn('op:', json.dumps(resolved['fairbind_parameters']))
        b1 = bl.resolve(arms['B1'], op, 'data-api-fast-v1')['fairbind_parameters']
        self.assertEqual((b1['retentionBlocks'], b1['sellerBond']['amount_atomic'], b1['samplePpm']), (9380, 100000, 100000))
        b2 = bl.resolve(arms['B2'], op, 'data-api-fast-v1')['fairbind_parameters']
        self.assertEqual((b2['deferExpiryBlocks'], b2['retentionBlocks']), (9380, 9380))
        readings = set()
        for vid in ('B7a', 'B7b'):
            p = bl.resolve(arms[vid], op, 'data-api-fast-v1')['fairbind_parameters']
            self.assertEqual((p['appeal']['windowBlocks'], p['sellerBond']['P_max_atomic']), (9380, 10000))
            readings.add(p['sellerBond']['E_open_reading'])
        self.assertEqual(readings, {'balance_at_check', 'window_integral'})
        b6 = arms['B6']['fairbind_parameters']
        self.assertEqual((b6['refundWindowBlocks'], b6['reserveHoldBlocks']), (1296000, 2592000))
        for path in (runner.ROOT / 'experiments' / 'baselines').iterdir():
            path.read_bytes().decode('ascii')

    def test_plan_records_operating_point_and_baseline(self):
        _, doc = dry_run('--only', 'D5,F1')
        op = opt.load()
        for e in doc['plan']:
            self.assertEqual(e['operating_point']['sha256'], op['_sha256'])
            if e['scenario'] == 'D5':
                self.assertEqual(e['baseline']['id'], 'B6')
            else:
                self.assertIsNone(e['baseline'])


class DryRun(unittest.TestCase):
    def test_plan_for_all_scenarios(self):
        code, doc = dry_run()
        self.assertEqual(code, 0)
        self.assertEqual((doc['scenarios'], doc['runs']), (28, 8179 + 900 + 4))
        # A point runs its cell's repetitions (n_seeds without cells); cells of another profile are skipped.
        self.assertEqual(doc['runs'], sum(scn.point_repetitions(s, pt) for s in scn.load_all(SCENARIOS)
                                          for pt in scn.sweep_points(s)
                                          if (scn.cell_of(s, pt) or {}).get('profile', scn.DEFAULT_CELL_PROFILE)
                                          == scn.DEFAULT_CELL_PROFILE))
        self.assertEqual(doc['base_profile_violations'], [])
        again = dry_run()[1]
        self.assertEqual(doc, again)
        seeds = [e['seed'] for e in doc['plan']]
        self.assertEqual(len(seeds), len(set(seeds)))

    def test_set_resolves_symbols(self):
        _, doc = dry_run('--only', 'D1,D2', '--set', 'Lambda_cheater=0.02')
        self.assertTrue(all(e['runnable'] for e in doc['plan']))
        self.assertTrue(all(e['parameters']['Lambda_cheater'] == 0.02 for e in doc['plan']))
        with self.assertRaises(SystemExit):
            dry_run('--only', 'F1', '--set', 'Lambda_cheater=1')
        with self.assertRaises(SystemExit):
            dry_run('--set', 'cap_enabled=false')

    def test_ground_truth_is_not_in_directives(self):
        _, doc = dry_run('--only', 'V2,F3,S4,A1')
        for e in doc['plan']:
            text = json.dumps(e['directives'])
            self.assertNotIn('expected', text)
            if e['scenario'] == 'F3':
                self.assertEqual(e['directives']['seller']['kind'], None)
                self.assertNotIn('restart_point', text)
                self.assertEqual(e['controller_actions'][0]['action'], 'kill_restart')
            if e['scenario'] == 'S4':
                self.assertNotIn('response_delay_blocks', text)
                self.assertEqual(e['controller_actions'][0]['mode'], 'delay')
        self.assertEqual(faults.expected_verdict('wrong_verdict', {'misjudgment_direction': 'false_fail'}), 'PASS')

    def test_invalid_scenario_directory_fails(self):
        with tempfile.TemporaryDirectory() as d:
            text = (SCENARIOS / 'V1.yaml').read_text().replace('- P4', '- X9')
            Path(d, 'V1.yaml').write_text(text)
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--dry-run', '--scenarios', d]), 2)
            self.assertIn('property_under_test', err.getvalue())

    def test_d_sweep_run_needs_allow_inadmissible_profile(self):
        with tempfile.TemporaryDirectory() as out:
            manifest_path = Path(out, 'manifest.json')
            manifest_path.write_text(json.dumps(example_manifest('import sys; sys.exit(0)')))
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                code = main(['--manifest', str(manifest_path), '--output', str(Path(out, 'runs')),
                             '--only', 'D2', '--allow-dirty'])
            lines = [json.loads(line) for line in captured.getvalue().splitlines()]
            self.assertEqual(len(lines), 6 * 30)  # three D below caseHorizon, two timings, n_seeds 30
            self.assertTrue(all(line['status'] == 'skipped' for line in lines))
            self.assertTrue(all(any('override_used' in reason and 'retentionBlocks >= caseHorizon' in reason
                                    for reason in line['reasons'])
                                for line in lines))
            self.assertFalse(Path(out, 'runs').exists())
            self.assertEqual(code, 0)

    def test_manifest_validation(self):
        self.assertEqual(runner.validate_manifest(json.loads(Path(__file__).with_name('local-manifest.example.json').read_text())), [])
        good = example_manifest('true')
        self.assertEqual(runner.validate_manifest(good), [])
        bad = json.loads(json.dumps(good))
        bad['rpcUrl'] = 'http://node.example:8545'
        bad['processes']['buyer']['command'].append('{secret}')
        del bad['processes']['keeper']
        errors = runner.validate_manifest(bad)
        self.assertEqual(len(errors), 2)


def example_manifest(buyer_code, seller_code='import time; time.sleep(60)'):
    py = sys.executable
    sleep = [py, '-c', 'import time; time.sleep(60)']
    procs = {name: dict(command=list(sleep)) for name in runner.LAUNCH_ORDER}
    procs['anvil']['ready'] = {'seconds': 0}
    procs['seller'] = dict(command=[py, '-c', seller_code, '{events}'])
    procs['buyer'] = dict(command=[py, '-c', buyer_code, '{observations}', '{directive}'])
    return dict(formatVersion=1, rpcUrl='http://127.0.0.1:8545', processes=procs, stopTimeoutSeconds=2,
                runTimeoutSeconds=30)


class Mechanisms(unittest.TestCase):
    def upstream(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                status = 402 if self.path == '/pay' else 200
                body = b'resource'
                self.send_response(status)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_address[1]}'

    def test_proxy_drops_paid_responses_only(self):
        truth = faults.GroundTruth(Path(tempfile.mkdtemp()) / 'gt.json', {})
        proxy = faults.ResponseProxy('127.0.0.1:0', self.upstream(), mode='drop', truth=truth).start()
        self.addCleanup(proxy.close)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(proxy.address + '/pay', timeout=5)
        self.assertEqual(ctx.exception.code, 402)
        with self.assertRaises(Exception):
            urllib.request.urlopen(proxy.address + '/resource', timeout=5).read()
        self.assertEqual([e['event'] for e in truth.doc['events']], ['response_dropped'])

    def test_proxy_delays_by_blocks(self):
        blocks = iter(range(100, 1000))
        proxy = faults.ResponseProxy('127.0.0.1:0', self.upstream(), mode='delay', delay_blocks=5,
                                     block_source=lambda: next(blocks)).start()
        self.addCleanup(proxy.close)
        self.assertEqual(urllib.request.urlopen(proxy.address + '/resource', timeout=10).read(), b'resource')
        self.assertGreaterEqual(next(blocks), 105)

    def test_collect_metrics_reports_missing(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'collector.jsonl').write_text(
                '{"metric": "double_settlement_rate", "value": 0}\n{"metric": "locked_capital", "value": null}\n')
            metrics, missing, bad = runner.collect_metrics(d, ['double_settlement_rate', 'locked_capital', 'x'])
            self.assertTrue(metrics['double_settlement_rate']['observed'])
            self.assertEqual(missing, ['locked_capital', 'x'])
            self.assertEqual(bad, ['collector.jsonl:2'])

    def test_deploy_step_receives_override_flag(self):
        # The deploy command sees the flag both in the derived profile document and in its
        # environment, so it can deploy the admission override test build for a D sweep point.
        deploy = ('import json, os, sys; doc = json.load(open(sys.argv[1]));'
                  'open(sys.argv[2], "w").write(json.dumps(dict(doc=doc.get("admissionOverride"),'
                  'env=os.environ.get("FAIRBIND_ADMISSION_OVERRIDE"))))')
        manifest = example_manifest('import sys; sys.exit(0)')
        manifest['deploy'] = dict(command=[sys.executable, '-c', deploy, '{profile}', '{proc_dir}/seen.json'])
        scenarios = [s for s in scn.load_all(SCENARIOS) if s['id'] in ('D1', 'F3')]
        plan = runner.build_plan(scenarios, base_profile())
        d1 = next(e for e in plan if e['scenario'] == 'D1')
        f3 = next(e for e in plan if e['scenario'] == 'F3')
        with tempfile.TemporaryDirectory() as out:
            for entry, expected in ((d1, (True, '1')), (f3, (False, '0'))):
                runner.execute(entry, manifest, out, block_source=lambda: 0)
                seen = json.loads(Path(out, 'runs', entry['run_id'], 'proc', 'deploy', 'seen.json').read_text())
                self.assertEqual((seen['doc'], seen['env']), expected, entry['run_id'])

    def test_execute_with_stub_processes(self):
        buyer = ('import json, sys; d = json.load(open(sys.argv[2]));'
                 'open(sys.argv[1], "w").write(json.dumps(dict(metric="double_settlement_rate", value=0,'
                 'observation_id=d["parameters"].get("buyer_retry_count"))) + "\\n")')
        manifest = example_manifest(buyer)
        manifest['processes']['buyer']['command'] = ['sh', '-c', 'sleep 1; exec "$0" "$@"',
                                                     *manifest['processes']['buyer']['command']]
        seller = ('import json, sys, time; open(sys.argv[1], "a").write(json.dumps(dict(event="before_response_generated"))'
                  ' + "\\n"); time.sleep(60)')
        manifest['processes']['seller'] = dict(command=[sys.executable, '-c', seller, '{events}'])
        scenarios = [s for s in scn.load_all(SCENARIOS) if s['id'] in ('F2', 'F3')]
        plan = runner.build_plan(scenarios, base_profile())
        f2 = next(e for e in plan if e['scenario'] == 'F2')
        f3 = next(e for e in plan if e['run_id'] == 'F3-p00-r0')
        with tempfile.TemporaryDirectory() as out:
            env = runner.execute(f3, manifest, out, block_source=lambda: 0)
            self.assertEqual(env['status'], 'completed', env['error'])
            self.assertEqual(env['processes']['seller']['starts'], 2)
            self.assertEqual(env['restart_errors'], [])
            self.assertIn('locked_capital', env['missing_metrics'])
            self.assertTrue(env['metrics']['double_settlement_rate']['observed'])
            self.assertFalse(env['override_used'])
            self.assertEqual(env['override_skipped_checks'], [])
            self.assertIsNone(env['requested_D_holding_blocks'])
            self.assertEqual(env['effective_hold_period_blocks'], 60000)
            truth_path = Path(env['ground_truth']['path'])
            self.assertNotIn(str(Path(out, 'runs')), str(truth_path))
            events = [e['event'] for e in json.loads(truth_path.read_text())['events']]
            self.assertIn('process_killed', events)
            self.assertIn('process_restarted', events)
            manifest['proxy'] = dict(listen='127.0.0.1:0', upstream='http://127.0.0.1:9')
            env = runner.execute(f2, manifest, out, block_source=lambda: 0)
            self.assertEqual(env['status'], 'completed', env['error'])
            self.assertEqual(env['metrics']['double_settlement_rate']['observations'][0]['observation_id'], 1)
            for key in ('revision', 'dirty', 'upstreams', 'parameters', 'seed', 'created_at', 'started_at',
                        'finished_at', 'scenario_sha256', 'profile_overrides', 'override_used', 'override_skipped_checks',
                        'requested_D_holding_blocks', 'effective_hold_period_blocks', 'operating_point',
                        'randomness', 'detection', 'metric_definitions'):
                self.assertIn(key, env)
            self.assertEqual(env['randomness']['seed_changes'], runner.SEED_EFFECTS)
            self.assertEqual(env['detection']['expected_p'], 0.04)
            self.assertIsNone(env['detection']['realized_detection_rate'])
            saved = json.loads(Path(out, 'results', f2['run_id'] + '.json').read_text())
            self.assertEqual(saved['seed'], f2['seed'])
            with self.assertRaises(FileExistsError):
                runner.execute(f2, manifest, out, block_source=lambda: 0)


class FiniteAttack(unittest.TestCase):
    def test_directive_block(self):
        self.assertEqual(finiteattack.directive(3, 'stop_selling'),
                         dict(cheat_sales=3, after='stop_selling', counts=finiteattack.COUNTS))
        for bad in ((0, 'stop_selling'), (True, 'stop_selling'), (2.5, 'serve_honestly'), (1, 'vanish')):
            with self.assertRaises(ValueError):
                finiteattack.directive(*bad)
        self.assertEqual(finiteattack.ground_truth(['a', 'b', 'c', 'd'], 2), ['a', 'b'])

    def test_plan_gives_the_block_to_the_seller_only(self):
        sc = copy.deepcopy(scn.load_scenario(SCENARIOS / 'S1.yaml'))
        sc['parameters']['finite_attack_cheat_sales'] = dict(default=3, unit='count')
        sc['parameters']['finite_attack_after'] = dict(default='serve_honestly',
                                                       sweep=list(finiteattack.AFTER), unit='mode')
        plan = runner.build_plan([sc], base_profile(), repetitions=1)
        afters = sorted(e['finite_attack']['after'] for e in plan if e['finite_attack'])
        self.assertEqual(afters, sorted(finiteattack.AFTER * (len(plan) // 3)))
        for e in plan:
            self.assertEqual(e['directives']['seller']['finite_attack']['cheat_sales'], 3)
            for proc, d in e['directives'].items():
                if proc != 'seller':
                    self.assertNotIn('finite_attack', d)
                self.assertNotIn('finite_attack_after', d.get('parameters', {}))
        sc['parameters']['finite_attack_cheat_sales'] = dict(default=0, unit='count')
        plan = runner.build_plan([sc], base_profile(), repetitions=1)
        self.assertTrue(all(e['finite_attack'] is None and not e['runnable'] for e in plan))

    def sale(self, settled, state, outcome=None, **blocks):
        return dict(settled_block=settled, value=10000, financial_state=state, case_outcome=outcome, **blocks)

    def test_detected_episode(self):
        sales = {'a': self.sale(10, 'REFUNDED', 'FAIL', repaid_block=40010),
                 'b': self.sale(20, 'REFUNDED', repaid_block=40100),
                 'c': self.sale(30, 'RELEASED', released_block=600030),
                 'h': self.sale(50, 'RELEASED', released_block=600050)}
        r = finiteattack.episode(sales, ['a', 'b', 'c'], run_end_block=700000, confirmed_failure_block=30000)
        self.assertEqual(r['finite_attack_detection'], 'with_detection')
        self.assertEqual(r['detected_by'], ['a'])
        self.assertEqual((r['seller_gain_released'], r['buyer_refund_amount'], r['buyer_refund_owed']),
                         (10000, 20000, 0))
        self.assertEqual(r['buyer_refund_blocks'], [40000, 40080])
        self.assertEqual(r['buyer_refund_blocks_max'], 40080)
        self.assertEqual(r['episode_end_block'], 600030)
        self.assertEqual([row['metric'] for row in finiteattack.rows('run', r)],
                         ['finite_attack_detection', 'seller_gain_released', 'buyer_refund_amount',
                          'buyer_refund_blocks'])

    def test_undetected_episode_releases_everything(self):
        sales = {n: self.sale(i, 'RELEASED', 'PASS' if n == 'b' else None, released_block=60000 + i)
                 for i, n in enumerate('abc')}
        r = finiteattack.episode(sales, ['a', 'b', 'c'], run_end_block=70000)
        self.assertEqual(r['finite_attack_detection'], 'without_detection')
        self.assertEqual((r['seller_gain_released'], r['buyer_refund_amount']), (30000, 0))
        self.assertEqual(r['buyer_refund_blocks'], [])
        self.assertIsNone(r['buyer_refund_blocks_max'])

    def test_open_episode_and_owed_refunds(self):
        sales = {'a': self.sale(10, 'FROZEN_CLAIMABLE', 'FAIL'), 'b': self.sale(20, 'DEFERRED')}
        r = finiteattack.episode(sales, ['a', 'b'], run_end_block=35000, confirmed_failure_block=30000)
        # A confirmed failure during an open episode is a detection.
        self.assertEqual(r['finite_attack_detection'], 'with_detection')
        self.assertEqual((r['buyer_refund_amount'], r['buyer_refund_owed']), (0, 10000))
        r = finiteattack.episode({'a': self.sale(10, 'DEFERRED')}, ['a'], run_end_block=35000)
        self.assertEqual(r['finite_attack_detection'], 'open')
        with self.assertRaises(ValueError):
            finiteattack.episode({}, ['a'], run_end_block=1)

    def test_failure_after_the_episode_is_not_its_detection(self):
        sales = {'a': self.sale(10, 'RELEASED', 'FAIL', released_block=60010)}
        r = finiteattack.episode(sales, ['a'], run_end_block=90000, confirmed_failure_block=70000)
        self.assertEqual(r['finite_attack_detection'], 'without_detection')
        self.assertEqual(r['seller_gain_released'], 10000)


if __name__ == '__main__':
    unittest.main()
