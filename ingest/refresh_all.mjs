import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {writeFile,rename,appendFile} from 'node:fs/promises';
import {refreshComponents} from './refresh-runner.mjs';
const run=promisify(execFile),root=new URL('../',import.meta.url).pathname;
const python=process.env.TERELLA_WEB_PYTHON;
if(!python)throw Error('Explicit interpreter required');
const jobs=[['NOAA',process.execPath,['ingest/refresh.mjs','--run']],['CAMS',python,['ingest/refresh_cams.py']],['temperature',python,['ingest/refresh_temperature.py']],['climate',python,['ingest/build_climate_candidate.py']]];
const report=await refreshComponents(jobs,
 (program,args)=>run(program,args,{cwd:root,timeout:10*60000,maxBuffer:65536}),
 ()=>run(process.execPath,['ingest/publish_bundle.mjs'],{cwd:root,timeout:30000,maxBuffer:65536}));
await writeFile(root+'data/refresh-status.part',JSON.stringify(report)+'\n');
await rename(root+'data/refresh-status.part',root+'data/refresh-status.json');
console.log(JSON.stringify(report));
if(process.env.GITHUB_STEP_SUMMARY)await appendFile(process.env.GITHUB_STEP_SUMMARY,
 '# Direct data refresh\n\n'+Object.entries(report.components).map(([name,c])=>`- ${name}: ${c.status}${c.reason?' ('+c.reason+')':''}`).join('\n')+
 `\n\nBundle published: ${report.bundlePublished}. Failed components retain their original data dates.\n`);
if(report.status!=='complete')process.exitCode=1;
