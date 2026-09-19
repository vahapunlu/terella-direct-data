import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {composeBundle} from '../ingest/bundle.mjs';

const read=name=>JSON.parse(readFileSync(new URL('../data/'+name,import.meta.url),'utf8'));
function fixture() {
  const base=read('current.json');
  const now=Date.parse(base.weatherArchive.current.weather.fetchedAt);
  // Make only climate stale, retaining its internally consistent source dates.
  const climate=structuredClone(base.climate);
  const day=new Date(now-5*86400000).toISOString().slice(0,10);
  climate.climate.observedFor=day;climate.climate.normalFor=day;
  climate.source.runAt=day+'T00:00:00Z';climate.source.fetchedAt=day+'T08:00:00Z';
  return {args:{weatherArchive:base.weatherArchive,aerosolArchive:base.aerosolArchive,
    climate,sites:read('sample-sites.json'),previous:{climate:structuredClone(climate)}},
    now:Math.max(now,Date.parse(base.aerosolArchive.current.aerosols.fetchedAt))};
}
test('previously published stale climate cannot block fresh weather and keeps its date',()=>{
  const {args,now}=fixture();const before=JSON.stringify(args.climate);
  const result=composeBundle(args,now);
  assert.equal(result.componentStatus.climate.state,'stale-retained');
  assert.equal(JSON.stringify(result.climate),before);
  assert.equal(result.weatherArchive,args.weatherArchive);
});
test('new or modified stale candidates cannot be published',()=>{
  const {args,now}=fixture();
  assert.throws(()=>composeBundle({...args,previous:null},now),/unpublished stale/);
  args.climate.climate.byIso3.TUR.today+=1;
  assert.throws(()=>composeBundle(args,now),/unpublished stale/);
});
test('retained climate still requires scientific integrity and nonfuture clocks',()=>{
  const {args,now}=fixture();
  args.climate.source.calibration.countryValidation.passed=false;
  args.previous.climate=structuredClone(args.climate);
  assert.throws(()=>composeBundle(args,now),/validation missing/);
  args.climate.source.fetchedAt=new Date(now+86400000).toISOString();
  assert.throws(()=>composeBundle(args,now),/fetch clock/);
});
test('stale weather is still rejected; climate retention does not relax other limits',()=>{
  const {args,now}=fixture();
  assert.throws(()=>composeBundle(args,now+3*86400000),/stale/);
});
