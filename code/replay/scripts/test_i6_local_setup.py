"""Deploy step of the hold-period harness (scripts/local_setup.py) without a chain.

The configuration functions are pure; `setup` runs against FakeChain, which answers the RPC and
cast calls the setup makes and records every transaction. The digest in NoHarness pins the run
directory that local_setup.py wrote before the harness block existed (same fake chain, same
inputs), so a document without a harness block still yields byte-identical files.
"""
import argparse
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import local_setup as ls

ROOT = ls.ROOT
sys.path.insert(0, str(ROOT / 'experiments'))
from controller import profile as prof  # noqa: E402

PROFILE_DOC = ROOT / 'profiles' / 'local-evaluation-v1.json'
DATA = 'data-api-fast-v1'
CAST = '/opt/foundry/bin/cast'
NOW = '2026-09-30T00:00:00Z'
# sha256 of the normalized run directory (see run_digest) written by local_setup.py at 12ced24 for
# profiles/local-evaluation-v1.json on FakeChain.
NO_HARNESS_DIGEST = '00ea3b29acabf2d4e8d24b724b6cec2ff3f098fb00e19e9c380cdf30df6fab15'


class FakeChain(ls.Chain):
    """Answers the setup's RPC and cast calls; keys and addresses are deterministic stand-ins."""

    def __init__(self):
        super().__init__('http://127.0.0.1:8545', 'cast')
        self.block, self.sends, self.next = 1, [], {'registerVerifier': 1, 'registerBond': 1, 'registerSeller': 1}

    @staticmethod
    def key(index):
        return '0x%064x' % (index + 1)

    @staticmethod
    def address(key):
        return '0x' + hashlib.sha256(key.encode()).hexdigest()[:40]

    def rpc(self, method, params):
        if method == 'eth_accounts':
            return [self.address(self.key(i)) for i in range(10)]
        if method == 'eth_blockNumber':
            return hex(self.block)
        if method == 'anvil_mine':
            self.block += int(params[0], 16)
            return None
        if method == 'eth_chainId':
            return hex(31337)
        raise AssertionError(method)

    def cast(self, *args):
        if args[0] == 'keccak':
            return '0x' + hashlib.sha3_256(bytes.fromhex(args[1][2:])).hexdigest()
        if args[:2] == ('wallet', 'private-key'):
            return self.key(int(args[args.index('--mnemonic-index') + 1]))
        if args[:2] == ('wallet', 'address'):
            return self.address(args[args.index('--private-key') + 1])
        if args[:2] == ('wallet', 'import'):
            d = Path(args[args.index('--keystore-dir') + 1])
            d.mkdir(parents=True, exist_ok=True)
            (d / args[2]).write_text(json.dumps({'fake': args[args.index('--private-key') + 1]}))
            return ''
        if args[0] == 'call':
            return str(self.next[args[6].split('(')[0]]) + ' [x]'
        if args[0] == 'send':
            sender, to, sig, rest = args[6], args[7], args[8], args[9:]
            name = sig.split('(')[0]
            if name in self.next:
                self.next[name] += 1
            self.sends.append((sender, to, name, rest))
            self.block += 1
            return json.dumps({'status': '0x1', 'transactionHash': '0x%064x' % len(self.sends)})
        raise AssertionError(args)

    def cast_location(self):
        return CAST


def fake_report(chain):
    acc = chain.rpc('eth_accounts', [])
    mods = {n: {'address': '0x%040x' % (i + 1), 'transaction': '0x%064x' % (i + 1)}
            for i, n in enumerate(['MockEIP3009Token', 'FairBindRegistry', 'FairBindBond', 'FairBind'])}
    return {'commit': 'c' * 40, 'dirty': False, 'build': 'production', 'anvil': 'anvil 1.5.1',
            'admission_override': False, 'deployments': mods, 'router': mods['FairBind']['address'],
            'token': mods['MockEIP3009Token']['address'],
            'roles': {'governance': acc[0], 'guardian': acc[1], 'penalty_treasury': acc[2],
                      'verifier_reward_pool': acc[3]}}


def data_doc(harness=None):
    doc = json.loads(PROFILE_DOC.read_text())
    out = {'formatVersion': 1, 'profiles': [p for p in doc['profiles'] if p['name'] == DATA]}
    if harness is not None:
        out['harness'] = harness
    return out


def controller_harness(scale, assignable):
    """The block the controller writes (experiments/controller/profile.py)."""
    return prof.harness(prof.load_profile(PROFILE_DOC, DATA), scale, assignable)


def run_setup(tmp, doc, verifiers=0):
    tmp = Path(tmp)
    chain = FakeChain()
    (tmp / 'report.json').write_text(json.dumps(fake_report(chain)))
    (tmp / 'profile.json').write_text(json.dumps(doc))
    a = argparse.Namespace(report=str(tmp / 'report.json'), profile=str(tmp / 'profile.json'),
                           run_dir=str(tmp / 'run'), rpc_url=chain.url, cast='cast', verifiers=verifiers,
                           seller_profile=0, base_port=18400, inference_model_dir='', inference_config_dir='',
                           python='python3')
    ls.setup(a, chain, now=NOW)
    run = tmp / 'run'
    return chain, run, json.loads((run / 'deployment.json').read_text())


def run_digest(tmp):
    """sha256 over the run directory's files (path and bytes), with the temporary directory and the
    repository root replaced by placeholders."""
    tmp = Path(tmp)
    h = hashlib.sha256()
    for f in sorted(p for p in (tmp / 'run').rglob('*') if p.is_file()):
        data = f.read_bytes().replace(str(tmp).encode(), b'<tmp>').replace(str(ROOT).encode(), b'<root>')
        h.update(str(f.relative_to(tmp)).encode() + b'\0' + data + b'\0')
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


class PureFunctions(unittest.TestCase):
    params = [p['parameters'] for p in data_doc()['profiles']]

    def test_controller_block_parses(self):
        for assignable in (9, 12, 14, 40):
            h = ls.parse_harness(data_doc(controller_harness(2, assignable)), self.params)
            self.assertEqual(h['verifierBondAtomic'], 100_000_000)
            self.assertEqual(h['registeredVerifiers'], max(assignable, 14))

    def test_rejected_blocks(self):
        good = controller_harness(1, 40)
        bad = [dict(good, extra=1), {k: v for k, v in good.items() if k != 'pollMs'},
               dict(good, assignableVerifiers=41), dict(good, registeredVerifiers=13, assignableVerifiers=9),
               dict(good, verifierBondAtomic='999999'), dict(good, sellerBondScale=0),
               dict(good, sellerBondScale=True), dict(good, cheatBody='yes'), dict(good, pollMs=0),
               dict(good, buyerPurchases=0)]
        for block in bad:
            with self.assertRaises(ls.HarnessError, msg=block):
                ls.parse_harness(data_doc(block), self.params)
        with self.assertRaises(ls.HarnessError):
            ls.parse_harness(data_doc(good), self.params, verifiers_flag=14)
        self.assertIsNone(ls.parse_harness(data_doc(), self.params))

    def test_verifier_bonds_forty(self):
        h = ls.parse_harness(data_doc(controller_harness(1, 40)), self.params)
        self.assertEqual(ls.verifier_bonds(self.params, h), [(100_000_000, True)] * 40)

    def test_verifier_bonds_v9(self):
        h = ls.parse_harness(data_doc(controller_harness(1, 9)), self.params)
        bonds = ls.verifier_bonds(self.params, h)
        self.assertEqual(bonds, [(100_000_000, True)] * 9 + [(1_000_000, False)] * 5)
        # The minimum bond stays below the assignment floor, the atomic bond above it.
        floor = prof.assignable_bond_floor(prof.load_profile(PROFILE_DOC, DATA))
        self.assertLess(1_000_000, floor)
        self.assertGreaterEqual(100_000_000, floor)

    def test_verifier_bonds_without_harness(self):
        self.assertEqual(ls.verifier_bonds(self.params, None), [(100_000_000, None)] * 14)
        self.assertEqual(len(ls.verifier_bonds(self.params, None, 20)), 20)
        with self.assertRaises(ls.HarnessError):
            ls.verifier_bonds(self.params, None, 13)

    def test_spare_indexes(self):
        h = ls.parse_harness(data_doc(controller_harness(1, 9)), self.params)
        spares = ls.spare_key_indexes(h)
        self.assertEqual(spares, list(range(24, 24 + h['spareVerifiers'])))
        self.assertEqual(spares, ls.spare_key_indexes(copy.deepcopy(h)))
        self.assertFalse(set(spares) & set(range(ls.VERIFIER_KEY_BASE, ls.VERIFIER_KEY_BASE + 14)))
        self.assertEqual(ls.spare_key_indexes(None), [])

    def test_seller_bond_and_appeal_funding(self):
        p = self.params[0]
        h = ls.parse_harness(data_doc(controller_harness(3, 40)), self.params)
        self.assertEqual(ls.seller_bond_amount(p, h), 3 * 10_000_000)
        self.assertEqual(ls.seller_bond_amount(p, None), 10_000_000)
        self.assertEqual(ls.appeal_funding(p, h), ls.APPEAL_DEPOSITS * 5_000_000)
        self.assertEqual(ls.appeal_funding(p, None), 0)
        # The honest arm at n = 7 appeals every initial PASS of about 126,000 purchases' sampled cases.
        self.assertEqual(ls.appeal_funding(p, dict(h, buyerPurchases=252_100)), 252_100 * 5_000_000)

    def test_buyer_funding(self):
        p = self.params[0]
        h = ls.parse_harness(data_doc(controller_harness(1, 40)), self.params)
        base = 1_000 * int(p['maxPurchaseValue']) + 4 * int(p['disputeDeposit'])
        self.assertEqual(ls.buyer_funding(p, None), base)
        self.assertEqual(ls.buyer_funding(p, dict(h, buyerPurchases=10)), base)
        self.assertEqual(ls.buyer_funding(p, dict(h, buyerPurchases=250_000)),
                         250_000 * int(p['maxPurchaseValue']) + 4 * int(p['disputeDeposit']))

    def test_poll_fields(self):
        h = dict(pollMs=500)
        self.assertEqual(ls.poll_fields(h, False), {'keeper': {'pollIntervalMs': 500}, 'tick': {'tickSeconds': 1},
                                                    'seller': {'tickMs': 500},
                                                    'verifier': {'pollIntervalSeconds': 1}})
        self.assertEqual(ls.poll_fields(None, False)['seller'], {'tickSeconds': 1})
        self.assertEqual(ls.poll_fields(h, True)['verifier'], {'pollIntervalMs': 500})
        self.assertEqual(ls.poll_fields(dict(pollMs=2500), False)['tick'], {'tickSeconds': 3})
        self.assertEqual(ls.poll_fields(None, True)['verifier'], {'pollIntervalSeconds': 1})

    def test_verifier_poll_ms_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / 'services' / 'verifier' / 'config.go'
            cfg.parent.mkdir(parents=True)
            cfg.write_text('PollIntervalSeconds int `json:"pollIntervalSeconds"`\n')
            self.assertFalse(ls.verifier_accepts_poll_ms(Path(tmp)))
            cfg.write_text('PollIntervalMs int `json:"pollIntervalMs,omitempty"`\n')
            self.assertTrue(ls.verifier_accepts_poll_ms(Path(tmp)))
        self.assertFalse(ls.verifier_accepts_poll_ms(Path('/nonexistent')))


class HarnessSetup(unittest.TestCase):
    def check_common(self, chain, run, dep, block):
        h = dep['harness']
        self.assertEqual(sorted(h), sorted(ls.HARNESS_KEYS + ('appealFunding', 'verifierPollMs')))
        verifiers, spares = dep['verifiers'], dep['spares']
        self.assertEqual(len(verifiers), block['registeredVerifiers'])
        self.assertEqual(len(spares), block['spareVerifiers'])
        self.assertEqual([v['verifierId'] for v in verifiers], list(range(1, len(verifiers) + 1)))
        # Registrations, then the checkpoint; spares are never registered.
        names = [s[2] for s in chain.sends]
        regs = [s for s in chain.sends if s[2] == 'registerVerifier']
        self.assertEqual(len(regs), block['registeredVerifiers'])
        self.assertGreater(names.index('checkpointVerifierTree'), max(i for i, n in enumerate(names)
                                                                       if n == 'registerVerifier'))
        registered_keys = {v['signingKey'] for v in verifiers}
        self.assertEqual({r[3][1] for r in regs}, registered_keys)
        spare_keys = [s['signingKey'] for s in spares]
        self.assertEqual(len(set(spare_keys)), len(spare_keys))
        self.assertFalse(set(spare_keys) & registered_keys)
        self.assertFalse(set(spare_keys) & {r['address'] for r in dep['roles'].values()})
        for s in spares:
            self.assertEqual(s['bond'], str(block['verifierBondAtomic']))
            self.assertIs(s['registered'], False)
            self.assertTrue(Path(s['keystore']).is_file())
            cfg = load(s['config'])
            self.assertEqual(cfg['verifierId'], 0)
            self.assertEqual(cfg['keystore'], s['keystore'])
        for v in verifiers:
            self.assertTrue(Path(v['config']).parent.joinpath('keystore', f'verifier-{v["verifierId"]}').is_file())
            self.assertEqual(load(v['config'])['verifierId'], v['verifierId'])
        # Verifier token funding covers exactly the registered bonds.
        mint = next(s for s in chain.sends if s[2] == 'mint' and s[0] == dep['roles']['verifier']['address'])
        self.assertEqual(int(mint[3][1]), sum(int(v['bond']) for v in verifiers))
        # Seller bond, appeal funding and polling.
        penalty = int(data_doc()['profiles'][0]['parameters']['sellerPenalty'])
        self.assertEqual(dep['bond']['amount'], str(block['sellerBondScale'] * penalty))
        bond_reg = next(s for s in chain.sends if s[2] == 'registerBond')
        self.assertEqual(int(bond_reg[3][1]), block['sellerBondScale'] * penalty)
        funding = int(h['appealFunding'])
        seller, buyer = dep['roles']['seller']['address'], dep['roles']['buyer']['address']
        self.assertIn((seller, dep['token'], 'mint', (seller, str(funding))), chain.sends)
        self.assertIn((buyer, dep['token'], 'mint', (buyer, str(funding))), chain.sends)
        self.assertIn((seller, dep['token'], 'approve', (dep['contract'], str(2**256 - 1))), chain.sends)
        self.assertEqual(load(dep['services']['keeper'])['pollIntervalMs'], block['pollMs'])
        seller_cfg = load(dep['services']['seller'])
        self.assertEqual((seller_cfg['tickMs'], 'tickSeconds' in seller_cfg), (block['pollMs'], False))
        vcfg = load(verifiers[0]['config'])
        if h['verifierPollMs']:
            self.assertEqual((vcfg['pollIntervalMs'], 'pollIntervalSeconds' in vcfg), (block['pollMs'], False))
        else:
            self.assertEqual((vcfg['pollIntervalSeconds'], 'pollIntervalMs' in vcfg), (1, False))
        # Cheat body: same preimage, same fields, a price outside the tolerance.
        route = seller_cfg['routes'][0]
        good, bad = load(route['bodyFile']), load(route['cheatBodyFile'])
        self.assertEqual(sorted(good), sorted(bad))
        self.assertEqual(good['symbol'], bad['symbol'])
        self.assertGreater(abs(float(good['price']) - float(bad['price'])), 5 + 0.001 * float(good['price']))

    def test_forty_verifiers(self):
        block = controller_harness(2, 40)
        with tempfile.TemporaryDirectory() as tmp:
            chain, run, dep = run_setup(tmp, data_doc(block))
            self.check_common(chain, run, dep, block)
            self.assertTrue(all(v['assignable'] and v['bond'] == '100000000' for v in dep['verifiers']))
            self.assertEqual([s['mnemonicIndex'] for s in dep['spares']], list(range(50, 90)))

    def test_v9(self):
        block = controller_harness(1, 9)
        with tempfile.TemporaryDirectory() as tmp:
            chain, run, dep = run_setup(tmp, data_doc(block))
            self.check_common(chain, run, dep, block)
            self.assertEqual([(v['assignable'], v['bond']) for v in dep['verifiers']],
                             [(True, '100000000')] * 9 + [(False, '1000000')] * 5)

    def test_spares_deterministic(self):
        block = controller_harness(1, 12)
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            s1 = run_setup(t1, data_doc(block))[2]['spares']
            s2 = run_setup(t2, data_doc(block))[2]['spares']
        strip = lambda s: [{k: v for k, v in e.items() if k not in ('keystore', 'config')} for e in s]  # noqa: E731
        self.assertEqual(strip(s1), strip(s2))

    def test_no_cheat_body(self):
        block = dict(controller_harness(1, 40), cheatBody=False)
        with tempfile.TemporaryDirectory() as tmp:
            _, run, dep = run_setup(tmp, data_doc(block))
            self.assertNotIn('cheatBodyFile', load(dep['services']['seller'])['routes'][0])
            self.assertFalse((run / 'services' / 'seller' / 'cheat-quote.json').exists())


class NoHarness(unittest.TestCase):
    def test_unchanged_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            chain, run, dep = run_setup(tmp, json.loads(PROFILE_DOC.read_text()))
            self.assertNotIn('harness', dep)
            self.assertNotIn('spares', dep)
            self.assertTrue(all('assignable' not in v for v in dep['verifiers']))
            self.assertFalse((run / 'services' / 'seller' / 'cheat-quote.json').exists())
            self.assertEqual(run_digest(tmp), NO_HARNESS_DIGEST)


if __name__ == '__main__':
    unittest.main()
