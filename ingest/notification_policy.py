"""Deduplicate known scientific blocks, never unknown operational failures.

Reports and scientific exit codes are unchanged. Only the workflow's final
notification decision compares this run with the previously published reports.
"""
import argparse
import json
import os
from pathlib import Path

FILES = {
    'refresh': ['refresh-status.json'],
    'renew': ['climate-renewal-status.json', 'temperature-quality.json'],
}


def refresh_issues(report):
    if report['bundlePublished'] is not True:
        raise ValueError('Publication failed')
    issues = set()
    components = report['components']
    if set(components) != {'NOAA', 'CAMS', 'temperature', 'climate'}:
        raise ValueError('Missing component')
    for name, component in components.items():
        if component['status'] == 'refreshed-or-unchanged':
            continue
        code = component.get('reason')
        if (name != 'climate' or component['status'] != 'failed'
                or component.get('previousDataRetained') is not True
                or code not in {'seasonal-normal-expired', 'calibration-expired-or-overlapping'}):
            raise ValueError('Operational failure')
        issues.add('climate:' + code)
    if report['status'] != ('degraded' if issues else 'complete'):
        raise ValueError('Inconsistent refresh report')
    return issues


def failed_limits(metrics, limits):
    keys = {key for key in ('countryMaeC', 'countryP95C', 'countryMaxC')
            if metrics[key] > limits[key]}
    if metrics['countryMaeC'] > metrics['rawCountryMaeC']:
        keys.add('mustImproveRaw')
    return keys


def renewal_issues(report):
    issues = set()
    if set(report['components']) != {'era5-normal-candidate.json', 'temperature-bias-candidate.json'}:
        raise ValueError('Missing renewal component')
    for name, component in report['components'].items():
        if component['status'] in {'renewed', 'not-due'}:
            continue
        if (name != 'temperature-bias-candidate.json' or component['status'] != 'rejected'
                or component.get('reason') != 'independent-validation-rejected'
                or component.get('previousDataRetained') is not True):
            raise ValueError('Incomplete renewal')
        keys = failed_limits(component['metrics'], component['limits'])
        if component['maxAbsoluteCorrectionC'] > component['limits']['maxAbsoluteCorrectionC']:
            keys.add('maxAbsoluteCorrectionC')
        if not keys:
            raise ValueError('Unexplained rejection')
        issues.update('candidate:' + key for key in keys)
    if report['status'] != ('degraded' if issues else 'complete'):
        raise ValueError('Inconsistent renewal report')
    return issues


def quality_issues(report):
    if report['status'] != 'complete':
        raise ValueError('Incomplete quality audit')
    issues = set()
    for name in ('activeBias', 'frozenHoldout', 'operationalHoldout'):
        value = report.get(name)
        if value is None or value.get('status') == 'pending':
            if name == 'activeBias':
                raise ValueError('Missing active audit')
            continue
        if value.get('passed') is True:
            continue
        if value.get('passed') is not False:
            raise ValueError('Unknown quality result')
        keys = failed_limits(value['metrics'], value['limits'])
        if not keys:
            raise ValueError('Unexplained quality failure')
        identity = name + ':' + value['biasSha256']
        issues.update(identity + ':' + key for key in keys)
        issues.update(identity + ':country:' + iso for iso in value['countriesAboveMaxLimit'])
    return issues


def decide(kind, before, after, outcomes):
    parsers = {'refresh-status.json': refresh_issues,
               'climate-renewal-status.json': renewal_issues,
               'temperature-quality.json': quality_issues}
    new, current = set(), set()
    try:
        for name in FILES[kind]:
            outcome = outcomes[name]
            if outcome == 'skipped':
                if kind != 'renew' or name != 'climate-renewal-status.json':
                    raise ValueError('Missing required step')
                continue
            if outcome not in {'success', 'failure'}:
                raise ValueError('Unknown step outcome')
            report = after[name]
            if report is None or report.get('checkedAt') == (before.get(name) or {}).get('checkedAt'):
                raise ValueError('No new report')
            issues = parsers[name](report)
            if outcome == 'failure' and not issues:
                raise ValueError('Unexplained process failure')
            try:
                previous = parsers[name](before[name])
            except (KeyError, TypeError, ValueError):
                previous = set()
            current.update(issues)
            new.update(issues - previous)
    except (KeyError, TypeError, ValueError):
        return {'alertRequired': True, 'reason': 'operational-or-unclassified-failure'}
    return {'alertRequired': bool(new),
            'reason': 'new-scientific-block' if new else ('known-scientific-block' if current else 'healthy'),
            'issueCount': len(current), 'newIssueCount': len(new)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['snapshot', 'decide'])
    parser.add_argument('kind', choices=FILES)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    snapshot = args.root / '.cache' / ('notification-' + args.kind + '.json')
    def read(name):
        path = args.root / 'data' / name
        return json.loads(path.read_text()) if path.exists() else None
    reports = {name: read(name) for name in FILES[args.kind]}
    if args.action == 'snapshot':
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(json.dumps(reports))
        return
    outcomes = dict(zip(FILES[args.kind], [os.environ.get('REFRESH_OUTCOME')] if args.kind == 'refresh'
                        else [os.environ.get('SUPPORT_OUTCOME'), os.environ.get('QUALITY_OUTCOME')]))
    decision = decide(args.kind, json.loads(snapshot.read_text()), reports, outcomes)
    print(json.dumps(decision))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('alert_required=' + str(decision['alertRequired']).lower() + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write('\n## Notification decision\n\n' + decision['reason'] +
                          '\n\nKnown scientific blocks remain in the data reports. '
                          'A successful workflow means no new alert, not scientific approval.\n')


if __name__ == '__main__':
    main()
