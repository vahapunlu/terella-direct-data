import {test} from 'node:test';
import assert from 'node:assert/strict';
import {planRun,mergeArchive,shouldReplace} from '../ingest/refresh-plan.mjs';
const c=(valid,run)=>({weather:{observedAt:valid},source:{runAt:run},publicationAllowed:false});
test('publication lag planning keeps all three-hour validity boundaries in the past',()=>{
  for(let hour=0;hour<48;hour++){
    const now=Date.parse('2026-09-08T00:30:00Z')+hour*3600000,p=planRun(now);
    assert.ok(Date.parse(p.validAt)<=now);assert.ok(now-Date.parse(p.runAt)>=4*3600000);
    assert.ok([3,6,9].includes(p.step));assert.equal(Number(p.cycle)%6,0);
  }
});
test('newer model at same validity replaces; older validity never replaces',()=>{
  const a=c('2026-09-08T21:00:00Z','2026-09-08T12:00:00Z'),b=c(a.weather.observedAt,'2026-09-08T18:00:00Z');
  assert.equal(shouldReplace(a,b),true);assert.equal(shouldReplace(b,a),false);
  assert.equal(shouldReplace(a,c('2026-09-08T18:00:00Z','2026-09-08T18:00:00Z')),false);
});
test('archive is ordered, deduplicated by validity and keeps provenance',()=>{
  const a=c('2026-09-08T18:00:00Z','2026-09-08T12:00:00Z'),b=c('2026-09-08T21:00:00Z','2026-09-08T12:00:00Z');
  const before={current:b,entries:[a,b]};const next=c(b.weather.observedAt,'2026-09-08T18:00:00Z');
  const state=mergeArchive(before,next,Date.parse('2026-09-08T22:00:00Z'));
  assert.deepEqual(state.entries,[a,next]);assert.equal(state.current,next);assert.equal(before.current,b);
  assert.equal(state.current.publicationAllowed,false);
  assert.throws(()=>mergeArchive(state,b),/older or duplicate/);
});
