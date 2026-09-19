"""Keep both sides on UTC daily means and the calibrated ERA5 temperature scale."""
from pathlib import Path
from datetime import date
import json,sys,numpy as np
ROOT=Path(__file__).resolve().parents[1]

class ClimateBlocked(ValueError):
 def __init__(self,code):
  super().__init__(code)
  self.code=code

def build(sites,normal,temperature,bias):
 key=sites['siteKey'];n=len(sites['sites']);today=temperature['todayCache'];source=temperature['source']
 if any(x!=key for x in [normal['siteKey'],today['siteKey'],bias['siteKey']]):raise ValueError('Site identities differ')
 if not bias['pilotAccepted'] or normal['source']['years']!=list(range(2006,2026)) or normal['daysPerSite']!=220:raise ValueError('Unaccepted calibration or incomplete normal')
 if abs((date.fromisoformat(today['date'])-date.fromisoformat(normal['builtFor'])).days)>7:raise ClimateBlocked('seasonal-normal-expired')
 if not 1 <= (date.fromisoformat(today['date'])-date.fromisoformat(bias['lastDay'])).days <=14:raise ClimateBlocked('calibration-expired-or-overlapping')
 if source['model']!='NOAA GFS' or source['runAt']!=today['date']+'T00:00:00Z' or len(source['hours'])!=24:raise ValueError('Calibration requires matching 00 UTC GFS run and complete day')
 expected=[f"{today['date']}T{h:02}:00:00Z"for h in range(24)]
 if [h['validAt']for h in source['hours']]!=expected:raise ValueError('Missing or mixed daily hours')
 for a in [today['temps'],bias['offsetsC'],normal['meansC']]:
  if len(a)!=n or not np.isfinite(a).all():raise ValueError('Incomplete temperature vectors')
 adjusted=np.array(today['temps'])+np.array(bias['offsetsC']);anomaly=adjusted-np.array(normal['meansC'])
 if adjusted.min()< -100 or adjusted.max()>70 or np.abs(anomaly).max()>40:raise ValueError('Implausible temperature/anomaly')
 groups={}
 for i,s in enumerate(sites['sites']):groups.setdefault(s['iso3'],[]).append(i)
 climate={'byIso3':{iso:{'anomaly':round(float(anomaly[idx].mean()),2),'today':round(float(adjusted[idx].mean()),1),'low':round(float(anomaly[idx].min()),2),'high':round(float(anomaly[idx].max()),2),'sites':len(idx)}for iso,idx in groups.items()},'normalYears':20,'normalFor':normal['builtFor'],'observedFor':today['date']}
 return {'schema':1,'status':'local-candidate-not-production','publicationAllowed':False,'siteKey':key,'source':{'temperatureModel':'NOAA GFS','normalModel':'Copernicus ERA5','runAt':source['runAt'],'fetchedAt':today['fetchedAt'],'dailyHours':24,'timeZone':'UTC','normalYears':normal['source']['years'],'normalWindowDays':5,'calibration':{k:v for k,v in bias.items()if k!='offsetsC'},'interpretation':'Bias-adjusted daily forecast relative to ERA5 seasonal normal; not a station observation or climate trend estimate'},'climate':climate}
if __name__=='__main__':
 read=lambda name:json.loads((ROOT/'data'/name).read_text())
 try:
  result=build(read('sample-sites.json'),read('era5-normal-candidate.json'),read('temperature-candidate.json'),read('temperature-bias-candidate.json'))
 except ClimateBlocked as error:
  print(json.dumps({'errorCode':error.code}));sys.exit(1)
 (ROOT/'data/climate-candidate.json').write_text(json.dumps(result)+'\n')
 print(json.dumps({'countries':len(result['climate']['byIso3']),'normalYears':20,'day':result['climate']['observedFor']}))
