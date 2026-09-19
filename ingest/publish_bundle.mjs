import {readFile,writeFile,rename} from 'node:fs/promises';
import {composeBundle} from './bundle.mjs';
const path=name=>new URL('../data/'+name,import.meta.url);
const read=async name=>JSON.parse(await readFile(path(name),'utf8'));
const weatherArchive=await read('weather-archive.json');
const aerosolArchive=await read('aerosol-archive.json');
const sites=await read('sample-sites.json');
let climate=null;
try {climate=await read('climate-candidate.json');} catch(e) {if(e.code!=='ENOENT')throw e;}
let previous=null;
try {previous=await read('current.json');} catch(e) {if(e.code!=='ENOENT')throw e;}
const bundle=composeBundle({weatherArchive,aerosolArchive,climate,sites,previous});
const body=JSON.stringify(bundle);
if(Buffer.byteLength(body)>2_000_000)throw Error('Private data bundle exceeds size budget');
await writeFile(path('current.part'),body+'\n');await rename(path('current.part'),path('current.json'));
console.log(JSON.stringify({bundleBytes:Buffer.byteLength(body),climateState:bundle.componentStatus.climate.state,weatherAt:weatherArchive.current.weather.observedAt,aerosolsAt:aerosolArchive.current.aerosols.observedAt}));
