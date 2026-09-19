import {isDeepStrictEqual} from 'node:util';
import {validateDirectWeather} from '../worker/weather-validator.ts';
import {validateAerosols} from '../worker/aerosol-validator.mjs';
import {validateClimate} from '../worker/climate-validator.mjs';

// A dated, previously published climate result may survive a rejected renewal.
// This does not admit new stale candidates or change the consumer freshness limits.
export function composeBundle({weatherArchive, aerosolArchive, climate, sites, previous}, now=Date.now()) {
  validateDirectWeather({...weatherArchive.current,status:'approved-direct-weather',publicationAllowed:true},now);
  validateAerosols(aerosolArchive.current,now);
  let climateState='missing';
  if(climate) {
    const valid=Date.parse(climate.climate?.observedFor+'T00:00:00Z');
    const fetched=Date.parse(climate.source?.fetchedAt);
    if(!Number.isFinite(fetched) || fetched>now+300000 || fetched<valid)throw Error('Invalid climate fetch clock');
    const stale=now-valid>48*3600000;
    if(stale && !isDeepStrictEqual(climate,previous?.climate))throw Error('Cannot introduce an unpublished stale climate candidate');
    validateClimate(climate,sites,stale?Math.max(valid,fetched):now);
    climateState=stale?'stale-retained':'fresh';
  }
  return {schema:1,target:'terella-private-web-only',updatedAt:new Date(now).toISOString(),
    weatherArchive,aerosolArchive,climate,
    componentStatus:{climate:{state:climateState,observedFor:climate?.climate.observedFor??null}}};
}
