export function validateAerosols(c, now = Date.now()) {
  if (c?.schema !== 1 || c.publicationAllowed !== false || c.status !== 'local-candidate-not-production' ||
      c.source?.model !== 'Copernicus CAMS' || c.source.sourceGridDegrees !== .4 || c.source.modelLevel !== 137 ||
      c.source.aodWavelengthNm !== 550 || c.source.pm10Unit !== 'ug/m3') throw Error('Invalid CAMS provenance');
  const a = c.aerosols, valid = Date.parse(a?.observedAt), fetched = Date.parse(a?.fetchedAt), run = Date.parse(c.source.runAt);
  if (![valid,fetched,run].every(Number.isFinite) || valid > now + 300000 || now-valid > 24*3600000 || fetched > now+300000 || fetched < run || run % (12*3600000) || valid-run !== c.source.forecastHour*3600000 || c.source.forecastHour < 0 || c.source.forecastHour > 120) throw Error('Invalid CAMS clocks');
  if (!Array.isArray(a.cells) || a.cells.length !== 264) throw Error('Incomplete CAMS grid');
  a.cells.forEach((r,i) => {
    if (!Array.isArray(r) || r.length !== 5 || r[0] !== -75+Math.floor(i/24)*15 || r[1] !== -180+i%24*15 ||
      !r.slice(2).every(Number.isFinite) || r[2]<0 || r[2]>100000 || r[3]<0 || r[3]>100000 || r[4]<0 || r[4]>30) throw Error('Invalid CAMS values');
  });
  return a;
}
