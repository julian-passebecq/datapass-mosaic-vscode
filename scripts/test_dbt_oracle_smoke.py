"""Evidence freshness checks for the real-dbt oracle; no dbt process executes."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb
from dbt_oracle_smoke import comparable, run_dbt, tables, validate_statuses


class DbtEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dbt-evidence-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.results = self.folder / 'target' / 'run_results.json'
        self.results.parent.mkdir()
        self.write_result('success')

    def write_result(self, status):
        self.results.write_text(json.dumps({'results': [
            {'unique_id': 'test.project.orders_unique.hash', 'status': status}
        ]}), encoding='utf-8')

    def invoke(self, code, write=None):
        def completed(*args, **kwargs):
            self.assertFalse(self.results.exists(), 'previous artifact must be removed before invocation')
            if write:
                self.write_result(write)
            return subprocess.CompletedProcess(args[0], code, stdout='', stderr='fixture')
        with patch('dbt_oracle_smoke.subprocess.run', side_effect=completed):
            return run_dbt(['fake-dbt'], self.folder, {'command': 'build'})

    def test_failed_command_cannot_reuse_previous_artifact(self):
        with self.assertRaisesRegex(RuntimeError, 'no run_results'):
            self.invoke(1)

    def test_zero_exit_without_current_artifact_is_not_evidence(self):
        with self.assertRaisesRegex(RuntimeError, 'no run_results'):
            self.invoke(0)

    def test_dbt_test_failure_has_valid_comparison_evidence(self):
        self.assertEqual(self.invoke(1, 'fail'), {'orders_unique': 'fail'})

    def test_crash_exit_is_rejected_even_with_new_artifact(self):
        with self.assertRaisesRegex(RuntimeError, 'exited unexpectedly'):
            self.invoke(2, 'success')

    def test_null_and_literal_none_are_distinct(self):
        table = {'columns': [('value', 'VARCHAR')], 'kind': 'BASE TABLE'}
        self.assertNotEqual(comparable({**table, 'rows': [(None,)]}, []),
                            comparable({**table, 'rows': [('None',)]}, []))

    def test_relation_kind_is_part_of_comparison(self):
        with duckdb.connect() as connection:
            connection.execute('CREATE SCHEMA silver; CREATE TABLE silver.t AS SELECT 1 AS n; '
                               'CREATE VIEW silver.v AS SELECT * FROM silver.t')
            relations = tables(connection)
        self.assertNotEqual(comparable(relations['silver.t'], []), comparable(relations['silver.v'], []))

    def test_matching_errors_cannot_pass(self):
        with self.assertRaisesRegex(RuntimeError, 'Unexpected node'):
            validate_statuses({'model': 'error'})

    def test_empty_selection_requires_explicit_scope(self):
        with self.assertRaisesRegex(RuntimeError, 'No nodes'):
            validate_statuses({})
        validate_statuses({}, allow_empty=True)

    def test_expected_test_failures_remain_comparable(self):
        validate_statuses({'test': 'fail', 'warning': 'warn', 'downstream': 'skipped'})


if __name__ == '__main__':
    unittest.main()
