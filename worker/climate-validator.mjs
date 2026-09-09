export function validateClimate(c, sites, now = Date.now()) {
  if (c?.schema !== 1 || c.status !== 'local-candidate-not-production' || c.publicationAllowed !== false || c.siteKey !== sites.siteKey) throw Error('Invalid private climate provenance');
  const s=c.source, v=c.climate, valid=Date.parse(v?.observedFor+'T00:00:00Z'),normal=Date.parse(v?.normalFor+'T00:00:00Z');
  if (s?.temperatureModel !== 'NOAA GFS' || s.normalModel !== 'Copernicus ERA5' || s.dailyHours !== 24 || s.timeZone !== 'UTC' || s.normalWindowDays !== 5 || v.normalYears !== 20 || s.normalYears?.length !== 20) throw Error('Incompatible climate basis');
  if (![valid,normal].every(Number.isFinite) || valid>now || now-valid>48*3600000 || Math.abs(valid-normal)>7*86400000 || s.runAt!==v.observedFor+'T00:00:00Z') throw Error('Invalid climate clocks');
  if (!s.calibration?.pilotAccepted || !s.calibration.countryValidation?.passed || s.calibration.countryValidation.scope !== 'Country means only; per-site extremes are not certified') throw Error('Climate country validation missing');
  const counts={};for(const p of sites.sites)counts[p.iso3]=(counts[p.iso3]??0)+1;
  if (Object.keys(v.byIso3??{}).length!==Object.keys(counts).length)throw Error('Climate countries incomplete');
  for(const [iso,count] of Object.entries(counts)){
    const r=v.byIso3[iso];
    if (!r || r.sites!==count || ![r.today,r.anomaly,r.low,r.high].every(Number.isFinite) || r.today< -100 || r.today>70 || r.low>r.anomaly+.01 || r.high<r.anomaly-.01 || r.low< -40 || r.high>40) throw Error('Invalid climate country values');
  }
  return v;
}
