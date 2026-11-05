"""chain_inputs.py: the joined list, the reference aggregates and the conditions file of another chain.
"""
import gzip
import json
import random
import tempfile

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import chain_inputs  # noqa: E402
import d2_report  # noqa: E402
import inputs  # noqa: E402


def write_daily(directory, days, rng, addresses, manifest=True, tamper=None):
    """Writes daily gz files with the Base columns; returns the rows in order."""
    directory.mkdir(parents=True, exist_ok=True)
    records, entries = [], []
    block = 5_000
    for d, date in enumerate(days):
        rows = []
        for _ in range(rng.randrange(40, 80)):
            block += rng.randrange(0, 4)
            rec = rng.choice(addresses)
            rows.append([block, f'{date} 00:{rng.randrange(60):02d}:{rng.randrange(60):02d}', f'tx{len(records) + len(rows):06d}',
                         len(rows), '', rec, 'payer', rng.choice((1000, 10_000, 250_000)), 'fac'])
        text = 'block_number,block_time_utc,tx_hash,tx_index,trace_address,recipient,payer,value_atomic,facilitator\n'
        text += ''.join(','.join(str(x) for x in r) + '\n' for r in rows)
        path = directory / f'settlements_{date}.csv.gz'
        with gzip.open(path, 'wt', newline='') as f:
            f.write(text)
        entries.append(dict(file=path.name, date=date, rows=len(rows), value_sum_atomic=str(sum(r[7] for r in rows)),
                            sha256_gz=inputs.sha256_file(path)))
        records += rows
    if manifest:
        if tamper:
            entries[tamper[0]][tamper[1]] = tamper[2]
        (directory / 'manifest.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in entries))
    return records


class ChainInputs(unittest.TestCase):
    ADDRESSES = ['Cv' + 'x' * 10 + 'AA', 'cv' + 'x' * 10 + 'aa', 'Bd2xS189uhhn', 'D2gmY6xa5uft', '7LXPEzVevioa', 'Zz9']

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        rng = random.Random(3)
        days = ['2026-09-08', '2026-09-09', '2026-09-10']
        cls.records = write_daily(cls.root / 'win', days, rng, cls.ADDRESSES)
        prior_days = ['2026-08-25', '2026-08-26']
        write_daily(cls.root / 'prior', prior_days, random.Random(4), cls.ADDRESSES)
        cls.report = chain_inputs.build('solana', cls.root / 'win', cls.root / 'out', cls.root / 'prior')

    @classmethod
    def tearDownClass(cls):
        inputs.set_address_case('lower')
        cls.tmp.cleanup()

    def test_the_list_is_the_days_in_order_and_hashes_match(self):
        out = self.root / 'out' / 'settlements_solana_2026-09-08_2026-09-10.csv'
        lines = out.read_text().splitlines()
        self.assertEqual(len(lines) - 1, len(self.records))
        self.assertEqual(lines[1].split(',')[2], self.records[0][2])
        self.assertEqual(lines[-1].split(',')[2], self.records[-1][2])
        self.assertEqual(self.report['list']['sha256'], inputs.sha256_file(out))
        self.assertEqual(self.report['list']['rows'], len(self.records))
        self.assertEqual(self.report['list']['value_sum_atomic'], sum(r[7] for r in self.records))
        self.assertTrue(self.report['checks_pass'])
        self.assertTrue(self.report['list']['manifest_checked'])
        self.assertEqual(self.report['list']['files'], 3)

    def test_addresses_that_differ_in_case_stay_apart(self):
        counts = {}
        for r in self.records:
            counts[r[5]] = counts.get(r[5], 0) + 1
        ref = d2_report.read_csv(self.root / 'out' / 'ref' / 'sellers_solana_all.csv')
        self.assertEqual({r['recipient']: int(r['settlements']) for r in ref}, counts)
        self.assertIn(self.ADDRESSES[0], counts)
        self.assertIn(self.ADDRESSES[1], counts)
        self.assertEqual(len(ref), 6)
        counts_sorted = [int(r['settlements']) for r in ref]
        self.assertEqual(counts_sorted, sorted(counts_sorted, reverse=True))

    def test_conditions_are_those_of_the_list(self):
        cond = json.loads((self.root / 'out' / 'conditions_solana.json').read_text())
        rp = cond['inputs']['replay_period']
        out = self.root / 'out' / 'settlements_solana_2026-09-08_2026-09-10.csv'
        span = self.records[-1][0] - self.records[0][0] + 1
        self.assertEqual((rp['rows'], rp['first_block'], rp['last_block'], rp['sha256']),
                         (len(self.records), self.records[0][0], self.records[-1][0], inputs.sha256_file(out)))
        self.assertEqual((cond['rate_blocks'], cond['window_blocks']), (span, span))
        self.assertEqual(cond['inputs']['prior_period']['rows'], self.report['prior']['rows'])
        self.assertNotIn('expected_scales', cond)
        self.assertEqual(cond['groups']['A']['ranks'], [1, 1])                  # 1% of 6 addresses, at least one
        self.assertEqual(cond['groups']['all400']['ranks'], [1, 6])
        self.assertEqual(cond['run_conditions'], [1])
        loaded = inputs.load_conditions(self.root / 'out' / 'conditions_solana.json')
        self.assertEqual(loaded['kind'], 'fairbind-settlement-replay-conditions')

    def test_group_sizes_follow_one_percent(self):
        self.assertEqual(chain_inputs.group_spec(4400), (44, 400, 48))                  # the registered Base groups
        self.assertEqual(chain_inputs.group_spec(357), (4, 357, 8))
        self.assertEqual(chain_inputs.group_spec(90), (1, 90, 5))
        self.assertEqual(chain_inputs.group_spec(1), (1, 1, 5))

    def test_a_manifest_mismatch_a_gap_and_a_bad_header_are_caught(self):
        rng = random.Random(9)
        days = ['2026-09-08', '2026-09-09']
        d = self.root / 'bad_rows'
        write_daily(d, days, rng, self.ADDRESSES, tamper=(1, 'rows', 3))
        r = chain_inputs.build('solana', d, self.root / 'bad_rows_out')
        self.assertFalse(r['checks_pass'])
        self.assertTrue(any('manifest' in p for p in r['list']['manifest_problems']))
        d = self.root / 'bad_sha'
        write_daily(d, days, rng, self.ADDRESSES, tamper=(0, 'sha256_gz', '0' * 64))
        self.assertFalse(chain_inputs.build('solana', d, self.root / 'bad_sha_out')['checks_pass'])
        d = self.root / 'gap'
        write_daily(d, ['2026-09-08', '2026-09-10'], rng, self.ADDRESSES)
        with self.assertRaises(ValueError):
            chain_inputs.build('solana', d, self.root / 'gap_out')
        d = self.root / 'header'
        write_daily(d, ['2026-09-08'], rng, self.ADDRESSES, manifest=False)
        path = d / 'settlements_2026-09-08.csv.gz'
        text = gzip.open(path, 'rt').read().replace('value_atomic', 'value')
        with gzip.open(path, 'wt', newline='') as f:
            f.write(text)
        with self.assertRaises(ValueError):
            chain_inputs.build('solana', d, self.root / 'header_out')

    def test_order_violations_are_counted(self):
        d = self.root / 'order'
        d.mkdir()
        header = 'block_number,block_time_utc,tx_hash,tx_index,trace_address,recipient,payer,value_atomic,facilitator\n'
        for date, blocks in (('2026-09-08', (10, 11)), ('2026-09-09', (9, 12))):
            with gzip.open(d / f'settlements_{date}.csv.gz', 'wt', newline='') as f:
                f.write(header + ''.join(f'{b},{date} 00:00:00,tx{b},0,,AA,P,100,F\n' for b in blocks))
        r = chain_inputs.build('solana', d, self.root / 'order_out')
        self.assertEqual(r['list']['block_order_violations'], 1)       # 11 -> 9 across the file boundary
        self.assertFalse(r['checks_pass'])


if __name__ == '__main__':
    unittest.main()
