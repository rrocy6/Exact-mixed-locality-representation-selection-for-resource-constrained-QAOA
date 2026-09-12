import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from make_selected_qaoa_paper_updates import targeted_effect_text, resource_completion_note


class SelectedQaoaPaperTextTests(unittest.TestCase):
    def test_windows_results_replace_previous_environment_values(self):
        row = dict(study='targeted', family='max3sat', contrast='pair_minus_cold',
                   budget_key='equal_layer_p2', mean='-6.721589693463177',
                   ci95_low='-9.142899163723387', ci95_high='-4.300280223202968')
        text = targeted_effect_text([row], 'equal_layer_p2')
        self.assertEqual(text, '$-6.7216$ (95\\% Student-t interval $[-9.1429,-4.3003]$)')
        self.assertNotIn('-6.7120', text)

    def test_missing_and_duplicate_contrasts_are_not_silently_reported(self):
        row = dict(study='targeted', family='max3sat', contrast='pair_minus_cold',
                   budget_key='equal_layer_p1', mean='-1', ci95_low='-2', ci95_high='0')
        for rows in [[], [row, row]]:
            with self.assertRaises(ValueError):
                targeted_effect_text(rows, 'equal_layer_p1')

    def test_resource_completion_requires_the_same_qaoa_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'results').mkdir()
            (root / 'results/E3_merged_runs.csv').write_bytes(b'actual input\n')
            resource = root / 'resources'
            resource.mkdir()
            audit = dict(status='E2_E5_SELECTED_UPDATE_COMPLETE',
                         QAOA_input_sha256=hashlib.sha256(b'other input\n').hexdigest(),
                         resource_rows_processed=7125, E5_primary_endpoints=272,
                         E5_additional_endpoints=324)
            (resource / 'EXECUTION_AUDIT.json').write_text(json.dumps(audit))
            with self.assertRaises(ValueError):
                resource_completion_note(root, resource)
            audit['QAOA_input_sha256'] = hashlib.sha256(b'actual input\n').hexdigest()
            (resource / 'EXECUTION_AUDIT.json').write_text(json.dumps(audit))
            self.assertIn('7125 resource rows', resource_completion_note(root, resource))

    def test_unknown_resource_status_is_not_reported_as_pending(self):
        text = resource_completion_note(Path('.'), None)
        self.assertIn('separate execution audit', text)
        self.assertNotIn('pending', text.lower())


if __name__ == '__main__':
    unittest.main()
