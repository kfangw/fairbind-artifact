"""Recipient addresses of case-sensitive chains (base58) keep their case; hex addresses are still lowered."""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import engine  # noqa: E402
import inputs  # noqa: E402

COLUMNS = ['block_number', 'block_time_utc', 'tx_hash', 'tx_index', 'trace_address', 'recipient', 'payer',
           'value_atomic', 'facilitator']


class AddressCase(unittest.TestCase):
    def tearDown(self):
        inputs.set_address_case('lower')

    def test_default_is_lower_case(self):
        self.assertEqual(inputs.normalize('0xABcd'), '0xabcd')
        self.assertEqual(inputs.list_hash(['0xAB', '0xcd']), inputs.list_hash(['0xab', '0xCD']))

    def test_keep_leaves_the_address_unchanged(self):
        inputs.set_address_case('keep')
        self.assertEqual(inputs.normalize('CvX23FNQ'), 'CvX23FNQ')
        self.assertNotEqual(inputs.list_hash(['AbC']), inputs.list_hash(['abc']))
        with self.assertRaises(ValueError):
            inputs.set_address_case('upper')

    def test_reference_files_and_loading_follow_the_mode(self):
        with tempfile.TemporaryDirectory() as d:
            ref = Path(d) / 'all.csv'
            ref.write_text('recipient,settlements\nAbC,5\nabc,3\n')
            lst = Path(d) / 'list.csv'
            rows = [[1, '2026-09-08 00:00:00', 'h1', 0, '', 'AbC', 'p', 10, 'f'],
                    [2, '2026-09-08 00:00:01', 'h2', 0, '', 'abc', 'p', 20, 'f'],
                    [3, '2026-09-08 00:00:02', 'h3', 0, '', 'AbC', 'p', 30, 'f']]
            with open(lst, 'w', newline='') as f:
                w = csv.writer(f, lineterminator='\n')
                w.writerow(COLUMNS)
                w.writerows(rows)
            self.assertEqual(inputs.load_all_addresses(ref), [('abc', 5), ('abc', 3)])           # hex mode collides them
            data = engine.load(lst, COLUMNS, ['abc'], inputs.iter_rows, inputs.utc_seconds)
            self.assertEqual(len(data.per['abc'][0]), 3)
            inputs.set_address_case('keep')
            self.assertEqual(inputs.load_all_addresses(ref), [('AbC', 5), ('abc', 3)])
            data = engine.load(lst, COLUMNS, ['AbC', 'abc'], inputs.iter_rows, inputs.utc_seconds, norm=inputs.normalize)
            self.assertEqual(data.per['AbC'][1].tolist(), [10, 30])
            self.assertEqual(data.per['abc'][1].tolist(), [20])
            self.assertEqual(data.total_rows, 3)


if __name__ == '__main__':
    unittest.main()
