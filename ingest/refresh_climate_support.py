"""Renew the seasonal normal and bias without replacing a good result on failure.

No scheduler is installed here. --plan is offline; --run explicitly downloads
public model fields. Small sampled progress can survive ephemeral data runners.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import os
import subprocess
import sys

import numpy as np
from era5_daily import sample_daily
from build_temperature_bias import fit
from credentials import read_key
from verify_temperature_bias import evaluate

ROOT = Path(__file__).resolve().parents[1]
YEARS = list(range(2006, 2026))
SCOPE = 'Country means only; per-site extremes are not certified'


class BiasRejected(ValueError):
    def __init__(self, report):
        super().__init__('Independent calibration validation failed')
        self.report = report


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix('.part')
    part.write_text(json.dumps(value, separators=(',', ':'), allow_nan=False) + '\n')
    os.replace(part, path)


def normal_days(target, year):
    # Explicit leap-day policy: center on February 28 for non-leap baseline years.
    try:
        center = date(year, target.month, target.day)
    except ValueError:
        if (target.month, target.day) != (2, 29):
            raise
        center = date(year, 2, 28)
    return [center + timedelta(days=i) for i in range(-5, 6)]


def calibration_days(target):
    # ERA5 daily data has publication latency. Reserve seven complete UTC days.
    # The final three days are later than, and excluded from, all fitting days.
    end = target - timedelta(days=7)
    days = [end - timedelta(days=i) for i in range(16, -1, -1)]
    return days[:14], days[14:]


def plan(target, normal, bias):
    training, holdout = calibration_days(target)
    normal_age = (target - date.fromisoformat(normal['builtFor'])).days if normal else None
    bias_age = (target - date.fromisoformat(bias['lastDay'])).days if bias else None
    return {
        'target': str(target),
        'normalDue': normal_age is None or not 0 <= normal_age < 4,
        'biasDue': bias_age is None or not 1 <= bias_age < 12,
        'normalAgeDays': normal_age, 'biasAgeDays': bias_age,
        'trainingDays': [str(d) for d in training],
        'holdoutDays': [str(d) for d in holdout],
        'baselineYears': YEARS, 'era5LagDays': 7,
    }


def build_normal(target, manifest, get_era5):
    total = np.zeros(len(manifest['sites']))
    for year in YEARS:
        rows = get_era5(normal_days(target, year))
        if rows.shape != (11, len(total)) or not np.isfinite(rows).all():
            raise ValueError('Incomplete seasonal normal year')
        total += rows.sum(axis=0)
    return {
        'schema': 1, 'status': 'local-candidate-not-production', 'publicationAllowed': False,
        'builtFor': str(target), 'siteKey': manifest['siteKey'],
        'siteCount': len(total), 'daysPerSite': 220, 'meansC': (total / 220).tolist(),
        'source': {
            'model': 'Copernicus ERA5', 'dataset': 'derived-era5-single-levels-daily-statistics',
            'years': YEARS, 'windowDays': 5, 'dailyStatistic': 'mean',
            'hourlyFrequency': 1, 'timeZone': 'UTC', 'sourceGridDegrees': .25,
            'interpolation': 'bilinear',
            'leapDayPolicy': 'February 28 center in non-leap baseline years',
        },
    }


def build_bias(target, manifest, get_era5, get_gfs):
    training_days, holdout_days = calibration_days(target)
    all_days = training_days + holdout_days
    observations = get_era5(all_days)
    records = [{'day': str(day), 'era5': row.tolist(), 'gfs': get_gfs(day)}
               for day, row in zip(all_days, observations)]
    if len(records) != 17:
        raise ValueError('Incomplete calibration period')
    candidate = {'schema': 1, 'siteKey': manifest['siteKey'],
                 **fit(records[:14], len(manifest['sites']))}
    metrics, accepted = evaluate(records[14:], manifest['sites'], candidate['offsetsC'])
    if not accepted or max(abs(x) for x in candidate['offsetsC']) > 15:
        raise BiasRejected({
            'reason': 'independent-validation-rejected',
            'trainingLastDay': candidate['lastDay'],
            'holdoutDays': [str(d) for d in holdout_days],
            'metrics': metrics,
            'limits': {'countryMaeC': 1, 'countryP95C': 2, 'countryMaxC': 4,
                       'mustImproveRaw': True, 'maxAbsoluteCorrectionC': 15},
            'maxAbsoluteCorrectionC': max(abs(x) for x in candidate['offsetsC']),
        })
    candidate['samplePilotAccepted'] = candidate['pilotAccepted']
    candidate['pilotAccepted'] = True
    candidate['countryValidation'] = {
        'days': [str(d) for d in holdout_days], **metrics,
        'passed': True, 'scope': SCOPE,
    }
    candidate['regionalCaution'] = (
        f"Local sample maximum error {metrics['sampleMaxC']:.2f} C; "
        'country aggregation does not certify local accuracy.')
    return candidate


class SampleStore:
    def __init__(self, root, manifest):
        self.root, self.manifest = root, manifest
        self.path = root / 'data/climate-support-cache.json'
        self.value = json.loads(self.path.read_text()) if self.path.exists() else {
            'schema': 1, 'siteKey': manifest['siteKey'], 'era5': {}, 'gfs': {}}
        if self.value['schema'] != 1 or self.value['siteKey'] != manifest['siteKey']:
            raise ValueError('Sample cache identity mismatch')
        # Seed previously downloaded, scientifically validated pilot pairs.
        for name in ['temperature-calibration-pairs.json', 'temperature-independent-pairs.json']:
            path = root / 'data' / name
            if not path.exists():
                continue
            pairs = json.loads(path.read_text())
            if pairs['siteKey'] != manifest['siteKey']:
                raise ValueError('Pilot pair identity mismatch')
            for row in pairs['records']:
                for kind in ['era5', 'gfs']:
                    self.value[kind].setdefault(row['day'], row[kind])

    def vector(self, values):
        result = np.array(values, dtype=float)
        if result.shape != (len(self.manifest['sites']),) or not np.isfinite(result).all():
            raise ValueError('Sample vector incomplete')
        if result.min() < -100 or result.max() > 70:
            raise ValueError('Sample vector outside Celsius bounds')
        return result

    def era5(self, days):
        import cdsapi
        groups = {}
        for day in days:
            if str(day) not in self.value['era5']:
                groups.setdefault((day.year, day.month), []).append(day)
        for (year, month), selected in sorted(groups.items()):
            selected = sorted(set(selected))
            raw = self.root / f'.cache/ingest/era5-support-{selected[0]}-{selected[-1]}.nc'
            raw.parent.mkdir(parents=True, exist_ok=True)
            if not raw.exists():
                client = cdsapi.Client(url='https://cds.climate.copernicus.eu/api',
                                      key=read_key('cds'), timeout=60, retry_max=2,
                                      quiet=True, debug=False)
                part = raw.with_suffix('.download')
                client.retrieve('derived-era5-single-levels-daily-statistics', {
                    'product_type': 'reanalysis', 'variable': ['2m_temperature'],
                    'year': str(year), 'month': [f'{month:02}'],
                    'day': [f'{d.day:02}' for d in selected],
                    'daily_statistic': 'daily_mean', 'time_zone': 'utc+00:00',
                    'frequency': '1_hourly',
                }, str(part))
                os.replace(part, raw)
            values = sample_daily(raw, [str(d) for d in selected], self.manifest['sites'])
            for day, row in zip(selected, values):
                self.value['era5'][str(day)] = self.vector(row).round(6).tolist()
            atomic_json(self.path, self.value)
            raw.unlink()
            print(json.dumps({'era5SamplesSaved': len(selected), 'lastDay': str(selected[-1])}), flush=True)
        return np.array([self.vector(self.value['era5'][str(day)]) for day in days])

    def gfs(self, day):
        if str(day) not in self.value['gfs']:
            out = self.root / f'.cache/ingest/gfs-temperature-{day}.json'
            if not out.exists():
                subprocess.run([sys.executable, str(self.root / 'ingest/build_temperature_candidate.py'),
                                '--date', str(day), '--cycle', '00', '--target-day', str(day),
                                '--output', str(out)], check=True, timeout=600, stdout=subprocess.DEVNULL)
            candidate = json.loads(out.read_text())
            cache, source = candidate['todayCache'], candidate['source']
            hours = [f'{day}T{h:02}:00:00Z' for h in range(24)]
            if (cache['siteKey'] != self.manifest['siteKey'] or cache['date'] != str(day)
                    or source['model'] != 'NOAA GFS' or source['runAt'] != f'{day}T00:00:00Z'
                    or [h['validAt'] for h in source['hours']] != hours):
                raise ValueError('GFS daily sample identity/time mismatch')
            self.value['gfs'][str(day)] = self.vector(cache['temps']).round(6).tolist()
            atomic_json(self.path, self.value)
        return self.vector(self.value['gfs'][str(day)]).tolist()

    def prune(self, target):
        wanted = {str(d) for y in YEARS for d in normal_days(target, y)}
        for kind in ['era5', 'gfs']:
            self.value[kind] = {d: row for d, row in self.value[kind].items()
                                if 0 <= (target - date.fromisoformat(d)).days <= 30
                                or (kind == 'era5' and d in wanted)}
        atomic_json(self.path, self.value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan', action='store_true')
    mode.add_argument('--run', action='store_true')
    args = parser.parse_args()
    target = datetime.now(timezone.utc).date()
    read = lambda name: json.loads((ROOT / 'data' / name).read_text()) if (ROOT / 'data' / name).exists() else None
    normal, bias = read('era5-normal-candidate.json'), read('temperature-bias-candidate.json')
    selected = plan(target, normal, bias)
    print(json.dumps({'mode': 'run' if args.run else 'plan-only', **selected}), flush=True)
    if not args.run:
        return
    manifest = read('sample-sites.json')
    samples = SampleStore(ROOT, manifest)
    failures = []
    report = {'schema': 1, 'checkedAt': datetime.now(timezone.utc).isoformat(),
              'targetDay': str(target), 'status': 'complete', 'components': {}}
    # Each component is committed only after complete scientific acceptance.
    for name, due, build in [
        ('era5-normal-candidate.json', selected['normalDue'], lambda: build_normal(target, manifest, samples.era5)),
        ('temperature-bias-candidate.json', selected['biasDue'], lambda: build_bias(target, manifest, samples.era5, samples.gfs)),
    ]:
        if due:
            try:
                atomic_json(ROOT / 'data' / name, build())
                report['components'][name] = {'status': 'renewed'}
            except Exception as error:
                failures.append(name)
                report['status'] = 'degraded'
                report['components'][name] = {
                    'status': 'rejected' if isinstance(error, BiasRejected) else 'incomplete',
                    'previousDataRetained': True,
                    **(error.report if isinstance(error, BiasRejected) else {'reason': 'renewal-incomplete'}),
                }
                # Never serialize clients, request headers or credential-bearing exceptions.
                print(name + ': renewal failed; previous accepted component retained', file=sys.stderr)
        else:
            report['components'][name] = {'status': 'not-due'}
    atomic_json(ROOT / 'data/climate-renewal-status.json', report)
    print(json.dumps(report), flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write('# Climate support renewal\n\n```json\n' + json.dumps(report, indent=2) + '\n```\n')
    if failures:
        raise SystemExit(1)
    samples.prune(target)


if __name__ == '__main__':
    main()
