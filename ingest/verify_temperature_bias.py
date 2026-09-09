"""Second, disjoint validation set at the actual country aggregation used by the UI."""
from pathlib import Path
import json,numpy as np
ROOT=Path(__file__).resolve().parents[1]

def evaluate(records,sites,offsets):
 o=np.array([r['era5']for r in records]);g=np.array([r['gfs']for r in records]);offsets=np.array(offsets)
 if o.shape!=(3,len(sites)) or g.shape!=o.shape or offsets.shape!=(len(sites),) or not np.isfinite(o).all() or not np.isfinite(g).all():raise ValueError('Incomplete independent matrix')
 errors=g+offsets-o;raw=g-o;groups={}
 for i,s in enumerate(sites):groups.setdefault(s['iso3'],[]).append(i)
 country=np.array([errors[:,idx].mean(1)for idx in groups.values()]);country_raw=np.array([raw[:,idx].mean(1)for idx in groups.values()])
 metrics={'countryMaeC':float(np.abs(country).mean()),'countryP95C':float(np.quantile(np.abs(country),.95)),'countryMaxC':float(np.abs(country).max()),'rawCountryMaeC':float(np.abs(country_raw).mean()),'sampleMaxC':float(np.abs(errors).max())}
 # Fixed before examining this separate dataset: verify the map's country means.
 accepted=metrics['countryMaeC']<=1 and metrics['countryP95C']<=2 and metrics['countryMaxC']<=4 and metrics['countryMaeC']<=metrics['rawCountryMaeC']
 return metrics,accepted

if __name__=='__main__':
 read=lambda name:json.loads((ROOT/'data'/name).read_text())
 bias=read('temperature-bias-candidate.json');independent=read('temperature-independent-pairs.json');training=read('temperature-calibration-pairs.json');sites=read('sample-sites.json')
 if len(independent['records'])!=3 or set(r['day']for r in independent['records']) & set(r['day']for r in training['records']):raise ValueError('Independent validation overlaps fitting days')
 if any(x['siteKey']!=sites['siteKey']for x in [bias,independent,training]):raise ValueError('Validation sites differ')
 metrics,accepted=evaluate(independent['records'],sites['sites'],bias['offsetsC'])
 bias['samplePilotAccepted']=bias['pilotAccepted']
 bias['countryValidation']={'days':[r['day']for r in independent['records']],**metrics,'passed':accepted,'scope':'Country means only; per-site extremes are not certified'}
 bias['pilotAccepted']=accepted
 bias['regionalCaution']='Polar local sample uncertainty: first holdout maximum 8.98 C in Antarctica; country aggregation does not remove local uncertainty.'
 (ROOT/'data/temperature-bias-candidate.json').write_text(json.dumps(bias)+'\n')
 print(json.dumps(bias['countryValidation']))
