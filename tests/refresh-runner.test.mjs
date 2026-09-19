import {test} from 'node:test';
import assert from 'node:assert/strict';
import {refreshComponents} from '../ingest/refresh-runner.mjs';
const jobs=['NOAA','climate','CAMS'].map(name=>[name,name,[]]);
test('climate rejection still runs other components and publishes, but remains failed',async()=>{
  const ran=[];let published=false;
  const report=await refreshComponents(jobs,async name=>{
    ran.push(name);
    if(name==='climate')throw {stdout:'{"errorCode":"calibration-expired-or-overlapping"}',stderr:'SECRET'};
  },async()=>{published=true;});
  assert.deepEqual(ran,['NOAA','climate','CAMS']);assert.ok(published);
  assert.equal(report.status,'degraded');assert.equal(report.bundlePublished,true);
  assert.equal(report.components.climate.reason,'calibration-expired-or-overlapping');
  assert.ok(!JSON.stringify(report).includes('SECRET'));
});
test('unexpected output is not leaked and publication failure stays visible',async()=>{
  const report=await refreshComponents(jobs,async()=>{throw {stdout:'{"errorCode":"SECRET"}',stderr:'SECRET'};},async()=>{throw Error('SECRET');});
  assert.equal(report.status,'degraded');assert.equal(report.bundlePublished,false);
  assert.ok(!JSON.stringify(report).includes('SECRET'));
});
test('all successful components produce a complete report',async()=>{
  const report=await refreshComponents(jobs,async()=>{},async()=>{});
  assert.equal(report.status,'complete');assert.equal(report.bundlePublished,true);
});
