// One bounded local operation. No deployment, cloud scheduler or write credentials.
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {readFile,writeFile,mkdir,rename,rm} from 'node:fs/promises';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {planRun,mergeArchive} from './refresh-plan.mjs';
import {validateDirectWeather} from '../worker/weather-validator.ts';
const execute=promisify(execFile);
const project=resolve(import.meta.dirname,'..');
const flags=new Set(process.argv.slice(2));
if([...flags].some(x=>!['--run','--plan'].includes(x)))throw new Error('Only --plan or --run is accepted');
const plan=planRun();
if(!flags.has('--run')){console.log(JSON.stringify({mode:'plan-only',...plan},null,2));process.exit(0);}
const started=Date.now();
const cache=resolve(project,'.cache/ingest');await mkdir(cache,{recursive:true});
const lock=resolve(cache,'refresh.lock');
let handle;
try{handle=await import('node:fs/promises').then(fs=>fs.open(lock,'wx'));}
catch{throw new Error('Another refresh is active; inspect the lock before retrying');}
const output=resolve(cache,'candidate-'+process.pid+'.json');
try{
  let previous;
  const statePath=resolve(project,'data/weather-archive.json');
  try{previous=JSON.parse(await readFile(statePath,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}
  if(previous&&(previous.schema!==1||previous.target!=='terella-private-web-only'||!Array.isArray(previous.entries)||!previous.current))throw new Error('Invalid existing private archive');
  const planned={source:{runAt:plan.runAt},weather:{observedAt:plan.validAt}};
  const {shouldReplace}=await import('./refresh-plan.mjs');
  if(previous&&!shouldReplace(previous.current,planned)){
    console.log(JSON.stringify({mode:'unchanged',reason:'Selected cycle already present; no download',...plan}));
  }else{
  // Python must be explicitly selected; no dependency installation or surprise cloud job.
  const python=process.env.TERELLA_WEB_PYTHON;
  if(!python)throw new Error('Set TERELLA_WEB_PYTHON to an installed isolated interpreter');
  await execute(python,[resolve(project,'ingest/build_gfs_candidate.py'),'--date',plan.date,'--cycle',plan.cycle,'--step',String(plan.step),'--output',output],{cwd:project,timeout:10*60000,maxBuffer:65536});
  const raw=await readFile(output,'utf8');
  if(raw.length>65536)throw new Error('Candidate exceeds size limit');
  const candidate=JSON.parse(raw);
  if(candidate.status!=='local-candidate-not-production'||candidate.publicationAllowed!==false)throw new Error('Expected private candidate');
  validateDirectWeather({...candidate,status:'approved-direct-weather',publicationAllowed:true},Date.now());
  const state=mergeArchive(previous,candidate);
  const temp=statePath+'.part';
  await writeFile(temp,JSON.stringify(state)+'\n');
  await rename(temp,statePath); // Current and history advance atomically.
  const report={at:new Date().toISOString(),durationSeconds:(Date.now()-started)/1000,selectedBytes:candidate.source.selectedBytes,candidateBytes:Buffer.byteLength(raw),sha256:createHash('sha256').update(raw).digest('hex'),entries:state.entries.length,source:candidate.source,validAt:candidate.weather.observedAt,deployed:false,cloudJob:false};
  await writeFile(resolve(project,'data/last-refresh.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
  }
}finally{await rm(output,{force:true});await handle.close();await rm(lock,{force:true});}
