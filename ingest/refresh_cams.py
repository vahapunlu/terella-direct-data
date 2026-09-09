"""Refresh one complete CAMS bundle, retaining the last successful archive."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,os
import cdsapi
from credentials import read_key
from build_cams_candidate import convert
from cams_plan import load_constraints, select_run
ROOT=Path(__file__).resolve().parents[1]

def merge_archive(previous,result,now):
 def clocks(c):return (datetime.fromisoformat(c['aerosols']['observedAt']),datetime.fromisoformat(c['source']['runAt']))
 if previous and clocks(result)<=clocks(previous['current']):raise ValueError('Reject older or duplicate CAMS model')
 entries={}
 for item in [*(previous or {}).get('entries',[]),result]:
  valid,run=clocks(item)
  if valid<now-timedelta(hours=48) or valid>now+timedelta(minutes=5):continue
  key=item['aerosols']['observedAt']
  if key not in entries or clocks(item)>clocks(entries[key]):entries[key]=item
 revisions={}
 for item in [*(previous or {}).get('superseded',[]),*(previous or {}).get('entries',[])]:
  key=item['aerosols']['observedAt'];winner=entries.get(key)
  if winner and winner['source']['runAt']!=item['source']['runAt']:
   revisions[key+'/'+item['source']['runAt']]=item
 return {'schema':1,'target':'terella-private-web-only','current':result,
         'entries':[entries[k]for k in sorted(entries)][-17:],'superseded':list(revisions.values())[-17:]}

def main():
 now=datetime.now(timezone.utc)
 request=json.loads((ROOT/'ingest/cams-request.json').read_text())
 plan=select_run(now,load_constraints(),request['variable'])
 run,step,valid=plan['run'],plan['step'],plan['valid']
 print(json.dumps({'selectedRunAt':run.isoformat(),'validAt':valid.isoformat(),
                   'preferredRunAt':plan['preferredRun'].isoformat(),'catalogueDeferred':plan['catalogueDeferred']}),flush=True)
 path=ROOT/'data/aerosol-archive.json'
 previous=json.loads(path.read_text())if path.exists() else None
 if previous:
  old=previous['current']
  if (datetime.fromisoformat(old['aerosols']['observedAt']),datetime.fromisoformat(old['source']['runAt'])) >= (valid,run):
   print('CAMS unchanged; selected cycle already archived');return
 request.update(date=f'{run:%Y-%m-%d}/{run:%Y-%m-%d}',time=[f'{run:%H}:00'],leadtime_hour=[str(step)])
 raw=ROOT/'.cache/ingest/cams-refresh.grib';raw.parent.mkdir(parents=True,exist_ok=True)
 c=cdsapi.Client(url='https://ads.atmosphere.copernicus.eu/api',key=read_key('ads'),timeout=60,retry_max=2,quiet=True,debug=False)
 c.retrieve('cams-global-atmospheric-composition-forecasts',request,str(raw))
 fetched=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
 result=convert(raw,fetched)
 if datetime.fromisoformat(result['aerosols']['observedAt'])!=valid or datetime.fromisoformat(result['source']['runAt'])!=run or result['source']['forecastHour']!=step:raise ValueError('CAMS returned wrong model run or valid time')
 archive=merge_archive(previous,result,now)
 part=path.with_suffix('.part');part.write_text(json.dumps(archive)+'\n');os.replace(part,path)
 # Keep a compatibility current file for the manually deployed pilot.
 (ROOT/'data/aerosol-candidate.json').write_text(json.dumps(result)+'\n')
 raw.unlink()
 print(json.dumps({'source':'CAMS','validAt':result['aerosols']['observedAt'],'entries':len(archive['entries'])}))
if __name__=='__main__':main()
