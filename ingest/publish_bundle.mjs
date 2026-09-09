import {readFile,writeFile,rename} from 'node:fs/promises';
import {validateDirectWeather} from '../worker/weather-validator.ts';
import {validateAerosols} from '../worker/aerosol-validator.mjs';
const path=name=>new URL('../data/'+name,import.meta.url);
const read=async name=>JSON.parse(await readFile(path(name),'utf8'));
const weatherArchive=await read('weather-archive.json');
const aerosolArchive=await read('aerosol-archive.json');
validateDirectWeather({...weatherArchive.current,status:'approved-direct-weather',publicationAllowed:true},Date.now());
validateAerosols(aerosolArchive.current);
const {validateClimate}=await import('../worker/climate-validator.mjs');
const sites=await read('sample-sites.json');
let climate=null;
try {climate=await read('climate-candidate.json');} catch(e) {if(e.code!=='ENOENT')throw e;}
if(climate)validateClimate(climate,sites);
const body=JSON.stringify({schema:1,target:'terella-private-web-only',updatedAt:new Date().toISOString(),weatherArchive,aerosolArchive,climate});
if(Buffer.byteLength(body)>2_000_000)throw Error('Private data bundle exceeds size budget');
await writeFile(path('current.part'),body+'\n');await rename(path('current.part'),path('current.json'));
console.log(JSON.stringify({bundleBytes:Buffer.byteLength(body),climateReady:!!climate,weatherAt:weatherArchive.current.weather.observedAt,aerosolsAt:aerosolArchive.current.aerosols.observedAt}));
