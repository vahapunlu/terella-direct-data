"""Daily fixed-policy accuracy audit, separate from freshness and fitting.

Copies of this module run in the isolated public data repository. This module
never replaces a bias, edits thresholds, removes sites, or publishes mobile data.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


LIMITS = {'countryMaeC': 1.0, 'countryP95C': 2.0, 'countryMaxC': 4.0,
          'mustImproveRaw': True}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def evaluate_bias(records, manifest, bias):
    from verify_temperature_bias import evaluate
    days=[r['day'] for r in records]
    if len(days)!=3 or days!=sorted(set(days)) or any(
            (date.fromisoformat(b)-date.fromisoformat(a)).days!=1 for a,b in zip(days,days[1:])):
        raise ValueError('Three complete consecutive validation days required')
    if manifest['siteKey']!=bias['siteKey'] or bias['lastDay']>=days[0]:
        raise ValueError('Validation identity mismatch or overlap with fitting')
    metrics,passed=evaluate(records,manifest['sites'],bias['offsetsC'])
    raw=np.array([r['gfs'] for r in records])-np.array([r['era5'] for r in records])
    corrected=raw+np.array(bias['offsetsC'])
    if not np.isfinite(corrected).all() or abs(np.array(bias['offsetsC'])).max()>15:
        raise ValueError('Invalid calibration offsets')
    groups={}
    for i,s in enumerate(manifest['sites']):groups.setdefault(s['iso3'],[]).append(i)
    rows=[]
    for country,indices in groups.items():
        for day,error in zip(days,corrected[:,indices].mean(axis=1)):
            rows.append({'iso3':country,'day':day,'sites':len(indices),'differenceC':float(error)})
    worst_point=np.unravel_index(np.abs(corrected).argmax(),corrected.shape)
    t,i=map(int,worst_point)
    return {'passed':bool(passed),'days':days,'metrics':metrics,'limits':LIMITS,
            'biasSha256':digest(bias),'trainingLastDay':bias['lastDay'],
            'countryCount':len(groups),'siteCount':len(manifest['sites']),
            'countriesAboveMaxLimit':sorted({r['iso3'] for r in rows if abs(r['differenceC'])>4}),
            'worstCountries':sorted(rows,key=lambda r:abs(r['differenceC']),reverse=True)[:10],
            'worstPoint':{'day':days[t],'siteIndex':i,**manifest['sites'][i],
                          'rawDifferenceC':float(raw[t,i]),'correctedDifferenceC':float(corrected[t,i])}}


def operational_records(plan, archive, observations, manifest):
    if digest(archive)!=plan['operationalGfsSha256']:
        raise ValueError('Frozen operational forecasts changed')
    rows=archive['records']
    if [r['day'] for r in rows]!=plan['operationalDays'] or any(
            r['siteKey']!=manifest['siteKey'] for r in rows):
        raise ValueError('Operational forecast days/sites changed')
    if len(observations)!=len(rows):
        raise ValueError('Incomplete operational reference')
    return [{'day':r['day'],'gfs':r['gfs'],'era5':list(o)} for r,o in zip(rows,observations)]


def make_report(root, target, fetch=False):
    from refresh_climate_support import SampleStore, atomic_json
    read=lambda name:json.loads((root/'data'/name).read_text())
    manifest=read('sample-sites.json'); bias=read('temperature-bias-candidate.json')
    end=target-timedelta(days=7)
    days=[end-timedelta(days=i) for i in (2,1,0)]
    samples=SampleStore(root,manifest)
    if fetch:
        era5=samples.era5(days)
        gfs=[samples.gfs(d) for d in days]
    else:
        era5=[samples.value['era5'][str(d)] for d in days]
        gfs=[samples.value['gfs'][str(d)] for d in days]
    records=[{'day':str(d),'era5':list(o),'gfs':list(g)} for d,o,g in zip(days,era5,gfs)]
    result={'schema':1,'checkedAt':datetime.now(timezone.utc).isoformat(),'targetDay':str(target),
            'status':'complete','reference':'ERA5 daily UTC mean; not station observations',
            'scope':'Country-mean reference agreement; local extremes remain visible',
            'activeBiasEvaluationType':'Retrospective check of current coefficients, not a replay of historical deployments',
            'activeBias':evaluate_bias(records,manifest,bias),'mobileMigrationApproved':False,
            'researchAccuracyCertified':False,'removedSites':0,'changedCoefficients':False}
    plan_path=root/'data/temperature-validation-plan.json'
    if plan_path.exists():
        plan=json.loads(plan_path.read_text()); frozen=read('validation-reference-bias.json')
        if digest(frozen)!=plan['biasSha256'] or manifest['siteKey']!=plan['siteKey']:
            raise ValueError('Frozen validation reference changed')
        if plan['earliestEvaluationDay']>str(target):
            result['frozenHoldout']={'status':'pending','days':plan['days'],
                                     'earliestEvaluationDay':plan['earliestEvaluationDay']}
        else:
            frozen_days=[date.fromisoformat(d) for d in plan['days']]
            if fetch:
                observations=samples.era5(frozen_days)
                forecasts=[samples.gfs(d) for d in frozen_days]
            else:
                observations=[samples.value['era5'][str(d)] for d in frozen_days]
                forecasts=[samples.value['gfs'][str(d)] for d in frozen_days]
            frozen_records=[{'day':str(d),'era5':list(o),'gfs':list(g)}
                            for d,o,g in zip(frozen_days,observations,forecasts)]
            result['frozenHoldout']={'status':'complete',**evaluate_bias(frozen_records,manifest,frozen)}
        if 'operationalDays' in plan:
            if plan['operationalEarliestDay']>str(target):
                result['operationalHoldout']={'status':'pending','days':plan['operationalDays'],
                                              'earliestEvaluationDay':plan['operationalEarliestDay']}
            else:
                operational_days=[date.fromisoformat(d) for d in plan['operationalDays']]
                observations=(samples.era5(operational_days) if fetch else
                              [samples.value['era5'][str(d)] for d in operational_days])
                actual=operational_records(plan,read('validation-operational-gfs.json'),observations,manifest)
                result['operationalHoldout']={'status':'complete',
                                              **evaluate_bias(actual,manifest,frozen)}
    atomic_json(root/'data/temperature-quality.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--target-day',default=str(datetime.now(timezone.utc).date()))
    p.add_argument('--fetch',action='store_true')
    args=p.parse_args(); root=args.root.resolve(); sys.path.insert(0,str(root/'ingest'))
    target=date.fromisoformat(args.target_day)
    from refresh_climate_support import atomic_json
    try:
        result=make_report(root,target,args.fetch)
    except Exception as error:
        # No exception text/traceback: HTTP objects may contain credentials.
        result={'schema':1,'checkedAt':datetime.now(timezone.utc).isoformat(),
                'targetDay':str(target),'status':'incomplete','failureType':type(error).__name__,
                'mobileMigrationApproved':False,'researchAccuracyCertified':False}
        atomic_json(root/'data/temperature-quality.json',result)
        print(json.dumps(result)); return 1
    print(json.dumps(result))
    # A frozen historical baseline is an experiment, not a permanent veto on
    # a different, later active calibration. Report both results separately.
    return 0 if result['activeBias']['passed'] else 1


if __name__=='__main__':
    sys.exit(main())
