"""Paired bias estimate with a chronological holdout; no quality claim from training fit."""
from pathlib import Path
import json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]

def fit(records,site_count):
 if len(records)!=14:raise ValueError('Exactly fourteen paired days required')
 days=[r['day']for r in records]
 if days!=sorted(set(days)):raise ValueError('Repeated/unordered calibration days')
 if any((np.datetime64(b)-np.datetime64(a)).astype(int)!=1 for a,b in zip(days,days[1:])):raise ValueError('Missing calibration day')
 obs=np.array([r['era5']for r in records]);raw=np.array([r['gfs']for r in records])
 if obs.shape!=(14,site_count) or raw.shape!=obs.shape or not np.isfinite(obs).all() or not np.isfinite(raw).all():raise ValueError('Incomplete paired sample matrix')
 if min(obs.min(),raw.min())< -100 or max(obs.max(),raw.max())>70:raise ValueError('Invalid Celsius range')
 # Days 1–11 estimate the correction; days 12–14 measure unseen-day error.
 train_bias=(obs[:11]-raw[:11]).mean(axis=0)
 corrected=raw[11:]+train_bias;error=corrected-obs[11:];before=raw[11:]-obs[11:]
 metrics={'holdoutDays':days[11:],'rawMaeC':float(np.abs(before).mean()),'correctedMaeC':float(np.abs(error).mean()),'correctedP95C':float(np.quantile(np.abs(error),.95)),'correctedMaxC':float(np.abs(error).max()),'maxAbsoluteCorrectionC':float(np.abs(train_bias).max())}
 # Private pilot acceptance limits, explicitly not a meteorological certification.
 passed=metrics['correctedMaeC']<=1.5 and metrics['correctedP95C']<=3 and metrics['correctedMaxC']<=8 and metrics['correctedMaeC']<=metrics['rawMaeC'] and metrics['maxAbsoluteCorrectionC']<=15
 # Once evaluated, use all fourteen complete pairs to estimate the operational offset.
 return {'method':'additive per-site paired daily-mean bias, GFS 00 UTC f000–f023 to ERA5 24-hour UTC daily means','firstDay':days[0],'lastDay':days[-1],'validation':metrics,'pilotAccepted':passed,'offsetsC':(obs-raw).mean(axis=0).tolist()}

if __name__=='__main__':
 pairs=json.loads((ROOT/'data/temperature-calibration-pairs.json').read_text());sites=json.loads((ROOT/'data/sample-sites.json').read_text())
 if pairs['siteKey']!=sites['siteKey']:raise ValueError('Site key mismatch')
 result={'schema':1,'siteKey':sites['siteKey'],**fit(pairs['records'],len(sites['sites']))}
 (ROOT/'data/temperature-bias-candidate.json').write_text(json.dumps(result)+'\n')
 print(json.dumps(result['validation']|{'pilotAccepted':result['pilotAccepted']}))
