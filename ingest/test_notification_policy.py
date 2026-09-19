import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from notification_policy import decide, FILES

ROOT = Path(__file__).resolve().parents[1]


class NotificationPolicyTest(unittest.TestCase):
    def setUp(self):
        metrics = {'countryMaeC': .44, 'countryP95C': 1.21, 'countryMaxC': 4.02,
                   'rawCountryMaeC': .81}
        limits = {'countryMaeC': 1, 'countryP95C': 2, 'countryMaxC': 4,
                  'maxAbsoluteCorrectionC': 15}
        self.before = {
            'refresh-status.json': {'checkedAt': '2026-09-19T00:00:00Z', 'status': 'degraded',
                'bundlePublished': True, 'components': {
                    **{name: {'status': 'refreshed-or-unchanged'} for name in ('NOAA', 'CAMS', 'temperature')},
                    'climate': {'status': 'failed', 'reason': 'calibration-expired-or-overlapping',
                                'previousDataRetained': True}}},
            'climate-renewal-status.json': {'checkedAt': '2026-09-19T00:00:00Z', 'status': 'degraded',
                'components': {'era5-normal-candidate.json': {'status': 'not-due'},
                    'temperature-bias-candidate.json': {'status': 'rejected',
                        'reason': 'independent-validation-rejected', 'previousDataRetained': True,
                        'metrics': metrics, 'limits': limits, 'maxAbsoluteCorrectionC': 5.8}}},
            'temperature-quality.json': {'checkedAt': '2026-09-19T00:00:00Z', 'status': 'complete',
                'activeBias': {'passed': False, 'metrics': copy.deepcopy(metrics), 'limits': limits,
                               'biasSha256': 'fixed-test-bias', 'countriesAboveMaxLimit': ['KAS']},
                'frozenHoldout': {'status': 'pending'}, 'operationalHoldout': {'status': 'pending'}},
        }
        self.after = copy.deepcopy(self.before)
        for value in self.after.values():
            value['checkedAt'] = '2030-01-01T00:00:00Z'

    def decision(self, kind='refresh', **overrides):
        outcomes = {name: 'failure' for name in FILES[kind]}
        outcomes.update(overrides)
        return decide(kind, self.before, self.after, outcomes)

    def test_same_known_expiry_does_not_alert(self):
        self.assertFalse(self.decision()['alertRequired'])
        self.assertEqual(self.after['refresh-status.json']['status'], 'degraded')

    def test_new_expiry_reason_alerts(self):
        self.after['refresh-status.json']['components']['climate']['reason'] = 'seasonal-normal-expired'
        self.assertTrue(self.decision()['alertRequired'])

    def test_no_history_alerts(self):
        self.before = {}
        self.assertTrue(self.decision()['alertRequired'])

    def test_operational_failures_always_alert_even_if_repeated(self):
        for report in (self.before, self.after):
            report['refresh-status.json']['components']['NOAA'] = {
                'status': 'failed', 'reason': 'component-refresh-failed'}
        self.assertTrue(self.decision()['alertRequired'])

    def test_publication_failure_always_alerts(self):
        self.after['refresh-status.json']['bundlePublished'] = False
        self.assertTrue(self.decision()['alertRequired'])

    def test_missing_or_unchanged_report_cannot_hide_crash(self):
        self.after = copy.deepcopy(self.before)
        self.assertTrue(self.decision()['alertRequired'])
        self.after['refresh-status.json'] = None
        self.assertTrue(self.decision()['alertRequired'])

    def test_recovery_clears_incident_and_recurrence_alerts(self):
        recovered = self.after['refresh-status.json']
        recovered['status'] = 'complete'
        recovered['components']['climate'] = {'status': 'refreshed-or-unchanged'}
        self.assertFalse(self.decision(**{'refresh-status.json': 'success'})['alertRequired'])
        failed = self.before['refresh-status.json']
        self.before['refresh-status.json'] = copy.deepcopy(recovered)
        self.after['refresh-status.json'] = copy.deepcopy(failed)
        self.after['refresh-status.json']['checkedAt'] = '2030-01-02T00:00:00Z'
        self.assertTrue(self.decision()['alertRequired'])

    def test_daily_known_rejections_do_not_repeat_alert(self):
        self.assertFalse(self.decision('renew')['alertRequired'])
        component = self.after['climate-renewal-status.json']['components']['temperature-bias-candidate.json']
        component['metrics']['countryMaxC'] += 0.001
        self.assertFalse(self.decision('renew')['alertRequired'])

    def test_new_failed_region_or_threshold_alerts(self):
        quality = self.after['temperature-quality.json']['activeBias']
        quality['countriesAboveMaxLimit'].append('TUR')
        self.assertTrue(self.decision('renew')['alertRequired'])

    def test_newly_completed_failed_frozen_window_alerts(self):
        self.after['temperature-quality.json']['frozenHoldout'] = {
            **copy.deepcopy(self.after['temperature-quality.json']['activeBias']), 'status': 'complete'}
        self.assertTrue(self.decision('renew')['alertRequired'])

    def test_incomplete_quality_audit_alerts(self):
        self.after['temperature-quality.json']['status'] = 'incomplete'
        self.assertTrue(self.decision('renew')['alertRequired'])

    def test_audit_only_can_skip_renewal_but_not_quality(self):
        self.assertFalse(self.decision('renew', **{'climate-renewal-status.json': 'skipped'})['alertRequired'])
        self.assertTrue(self.decision('renew', **{'temperature-quality.json': 'skipped'})['alertRequired'])

    def test_cli_snapshot_decision_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            path = root / 'data/refresh-status.json'
            path.write_text(json.dumps(self.before['refresh-status.json']))
            cli = [sys.executable, str(ROOT / 'ingest/notification_policy.py')]
            subprocess.run(cli + ['snapshot', 'refresh', '--root', directory], check=True)
            path.write_text(json.dumps(self.after['refresh-status.json']))
            env = {**os.environ, 'REFRESH_OUTCOME': 'failure',
                   'GITHUB_OUTPUT': str(root / 'output'), 'GITHUB_STEP_SUMMARY': str(root / 'summary')}
            result = subprocess.run(cli + ['decide', 'refresh', '--root', directory], env=env,
                                    check=True, capture_output=True, text=True)
            self.assertFalse(json.loads(result.stdout)['alertRequired'])
            self.assertEqual((root / 'output').read_text(), 'alert_required=false\n')
            self.assertIn('not scientific approval', (root / 'summary').read_text())


if __name__ == '__main__':
    unittest.main()
