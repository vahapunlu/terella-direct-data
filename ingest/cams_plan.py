"""Select a complete model run from the official ADS availability catalogue."""
from datetime import datetime, timedelta
import json
import ssl
import urllib.request
import certifi

CATALOGUE_URL = 'https://ads.atmosphere.copernicus.eu/api/catalogue/v1/collections/cams-global-atmospheric-composition-forecasts/constraints.json'
MODEL_VARIABLES = {'temperature', 'specific_humidity',
                   'dust_aerosol_0.03-0.55um_mixing_ratio',
                   'dust_aerosol_0.55-0.9um_mixing_ratio',
                   'dust_aerosol_0.9-20um_mixing_ratio'}


def load_constraints():
    # Public metadata, no API credential or account data is sent.
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(CATALOGUE_URL, timeout=30, context=context) as response:
        raw = response.read(4_000_001)
    if len(raw) > 4_000_000:
        raise ValueError('CAMS catalogue exceeds size limit')
    rows = json.loads(raw)
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2000:
        raise ValueError('Invalid CAMS availability catalogue')
    return rows


def date_available(day, ranges):
    for value in ranges:
        parts = value.split('/')
        if len(parts) not in (1, 2):
            raise ValueError('Unexpected catalogue date interval')
        start, end = parts[0], parts[-1]
        datetime.strptime(start, '%Y-%m-%d')
        datetime.strptime(end, '%Y-%m-%d')
        if start <= day <= end:
            return True
    return False


def available(rows, variable, run, step):
    for row in rows:
        if variable not in row.get('variable', []) or 'forecast' not in row.get('type', []):
            continue
        if 'pressure_level' in row:
            continue
        if variable in MODEL_VARIABLES:
            if '137' not in row.get('model_level', []):
                continue
        elif 'model_level' in row:
            continue
        if (run.strftime('%H:00') in row.get('time', [])
                and str(step) in row.get('leadtime_hour', [])
                and date_available(run.strftime('%Y-%m-%d'), row.get('date', []))):
            return True
    return False


def select_run(now, rows, variables):
    lagged = now - timedelta(hours=8)
    preferred = lagged.replace(hour=(lagged.hour // 12) * 12, minute=0, second=0, microsecond=0)
    run = preferred
    while now - run <= timedelta(hours=48):
        step = int((now - run).total_seconds() // 10800) * 3
        if 0 <= step <= 120 and all(available(rows, var, run, step) for var in variables):
            return {'run': run, 'step': step, 'valid': run + timedelta(hours=step),
                    'preferredRun': preferred, 'catalogueDeferred': run != preferred}
        run -= timedelta(hours=12)
    raise ValueError('No complete CAMS run available within 48 hours; retain last-good data')
