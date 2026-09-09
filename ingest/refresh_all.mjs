import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const run=promisify(execFile),root=new URL('../',import.meta.url).pathname;
const python=process.env.TERELLA_WEB_PYTHON;
if(!python)throw Error('Explicit interpreter required');
const jobs=[['NOAA',process.execPath,['ingest/refresh.mjs','--run']],['CAMS',python,['ingest/refresh_cams.py']],['temperature',python,['ingest/refresh_temperature.py']],['climate',python,['ingest/build_climate_candidate.py']]];
let failed=false;
for(const [name,program,args]of jobs){
 try{await run(program,args,{cwd:root,timeout:10*60000,maxBuffer:65536});console.log(name+': refreshed or unchanged');}
 catch{failed=true;console.error(name+': refresh failed; previous successful data retained');}
}
await run(process.execPath,['ingest/publish_bundle.mjs'],{cwd:root,timeout:30000,maxBuffer:65536});
if(failed)process.exitCode=1;
