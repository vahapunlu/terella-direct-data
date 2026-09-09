from pathlib import Path
from datetime import datetime,timezone,timedelta
import json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
now=datetime.now(timezone.utc)
# Wait for the 00 UTC run. At the beginning of the UTC day retain the previous day's labelled result.
target=now.date() if now.hour>=5 else (now-timedelta(days=1)).date()
out=ROOT/'data/temperature-candidate.json'
if out.exists() and json.loads(out.read_text())['todayCache']['date']>=str(target):
 print('Daily temperature unchanged');sys.exit(0)
part=out.with_suffix('.part')
subprocess.run([sys.executable,str(ROOT/'ingest/build_temperature_candidate.py'),'--date',str(target),'--cycle','00','--target-day',str(target),'--output',str(part)],check=True,timeout=600)
os.replace(part,out)
