const HOUR=3600000;
export function planRun(now=Date.now()) {
  if (!Number.isFinite(now)) throw new Error('Invalid clock');
  // Allow four hours for GFS publication; never select a future valid time.
  const run=Math.floor((now-4*HOUR)/(6*HOUR))*6*HOUR;
  const step=Math.floor((now-run)/(3*HOUR))*3;
  const at=new Date(run).toISOString();
  return {date:at.slice(0,10),cycle:at.slice(11,13),step,runAt:at,validAt:new Date(run+step*HOUR).toISOString()};
}
export function shouldReplace(previous,next) {
  if (!previous) return true;
  const oldValid=Date.parse(previous.weather.observedAt),newValid=Date.parse(next.weather.observedAt);
  if(newValid!==oldValid) return newValid>oldValid;
  return Date.parse(next.source.runAt)>Date.parse(previous.source.runAt);
}
export function mergeArchive(previous,next,now=Date.now()) {
  if(!shouldReplace(previous?.current,next)) throw new Error('Reject older or duplicate NOAA model run');
  const map=new Map();
  for(const entry of [...(previous?.entries??[]),...(previous?.current?[previous.current]:[]),next]){
    const valid=Date.parse(entry.weather.observedAt);
    if(valid<now-48*HOUR || valid>now+5*60000)continue;
    const key=entry.weather.observedAt;
    if(!map.has(key)||shouldReplace(map.get(key),entry))map.set(key,entry);
  }
  const entries=[...map.values()].sort((a,b)=>Date.parse(a.weather.observedAt)-Date.parse(b.weather.observedAt)).slice(-17);
  // An open client may still hold an immutable name from an earlier model
  // revision at the same validity. Retain those bytes through the history window.
  const revisions=new Map();
  for(const entry of [...(previous?.superseded??[]),...(previous?.entries??[])]) {
    const valid=Date.parse(entry.weather.observedAt),winner=map.get(entry.weather.observedAt);
    if(valid>=now-48*HOUR && winner && winner.source.runAt!==entry.source.runAt) {
      revisions.set(entry.weather.observedAt+'/'+entry.source.runAt,entry);
    }
  }
  return {schema:1,target:'terella-private-web-only',updatedAt:new Date(now).toISOString(),current:next,entries,superseded:[...revisions.values()].slice(-17)};
}
