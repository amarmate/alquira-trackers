"""Checks for the decompile metrics (design spec section 8) on a hand-written export.

Run: .venv/bin/python -m unittest discover -s tools -p 'test_*.py'
"""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent / 'ghidra'))
from metrics import measure, read_export  # noqa: E402

FIRST = '''// ---- FUN_88000400 @ 88000400 ----

void FUN_88000400(void)
{
  code *UNRECOVERED_JUMPTABLE;
  func_0x81e015f0(4);
  func_0x81c01be8();
  func_0x8200031c();
  func_0x82020000();
  (*UNRECOVERED_JUMPTABLE)();
  (*UNRECOVERED_JUMPTABLE)();
}

'''
SECOND = '''// ---- sms_apn_handle @ 881b4f3c ----

void sms_apn_handle(char *param_1)
{
  FUN_88000400("sms_apn_handle error");
  FUN_88000400("sms_apn_handle error");
  FUN_88000400("say \\"hi\\"", '"');
  func_0x81e015f0(4);
}

// ---- thunk_FUN_88000400 @ 881b5000 ----
// DECOMPILE FAILED: timeout
'''


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.result = measure(FIRST + SECOND)

    def test_counts_functions_and_names(self):
        self.assertEqual(self.result['functions'], 3)
        self.assertEqual(self.result['named'], 1)

    def test_string_literals_are_distinct_and_survive_quotes(self):
        self.assertEqual(self.result['string_literals'], 2)

    def test_unrecovered_counts_bodies_not_occurrences(self):
        self.assertEqual(self.result['unrecovered_returns'], 1)

    def test_failed_decompiles(self):
        self.assertEqual(self.result['decompile_failed'], 1)

    def test_missing_targets_by_region(self):
        self.assertEqual(self.result['missing_targets'], 4)
        self.assertEqual(self.result['missing_by_region'],
                         {'rom': 1, 'sram': 1, 'ram': 1, 'ram_packed': 1})

    def test_spot_check_lists_absent_names(self):
        self.assertEqual(self.result['spot_check_missing'],
                         ['get_apn_handle', 'set_url_port'])

    def test_reads_only_the_build_files_of_a_directory_in_address_order(self):
        with tempfile.TemporaryDirectory() as folder:
            pathlib.Path(folder, '881b0000.c').write_text(SECOND)
            pathlib.Path(folder, '88000000.c').write_text(FIRST)
            pathlib.Path(folder, 'index.tsv').write_text('not C\n')
            pathlib.Path(folder, 'v24_code.c').write_text(FIRST)
            self.assertEqual(read_export(folder), FIRST + SECOND)

    def test_reads_a_single_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder, 'v24_code.c')
            path.write_text(FIRST)
            self.assertEqual(read_export(path), FIRST)


if __name__ == '__main__':
    unittest.main()
