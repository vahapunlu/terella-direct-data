// Standalone public-source collector. No application code, cloud credentials or dependencies.
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

export const LAUNCH_SOURCE = 'https://ll.thespacedevs.com/2.3.0/launches/';
export const OCEAN_SOURCE = 'https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21NrtAgg.csv';
const HOUR = 3600000, DAY = 24 * HOUR;

export function oceanDates(now) {
  const midnight = Date.parse(new Date(now).toISOString().slice(0, 10) + 'T00:00:00Z');
  return [1, 2, 3].map(d => new Date(midnight - d * DAY).toISOString().slice(0, 10) + 'T12:00:00Z');
}

export function validateLaunches(body) {
  if (!Array.isArray(body?.results) || body.results.length > 100) throw Error('Invalid launch results');
  const valid = body.results.filter(r => r && r.pad?.latitude != null && r.pad.longitude != null &&
    String(r.pad.latitude).trim() && String(r.pad.longitude).trim() &&
    Number.isFinite(Number(r.pad.latitude)) && Math.abs(Number(r.pad.latitude)) <= 90 &&
    Number.isFinite(Number(r.pad.longitude)) && Math.abs(Number(r.pad.longitude)) <= 180 &&
    typeof r.net === 'string' && Number.isFinite(Date.parse(r.net)));
  if (body.results.length && !valid.length) throw Error('No valid launch coordinates/dates');
  return body;
}

export function validateOcean(csv, observedAt) {
  if (typeof csv !== 'string') throw Error('Invalid ocean CSV');
  const rows = csv.trim().split(/\r?\n/);
  if (rows.shift() !== 'time,zlev,latitude,longitude,anom' ||
      rows.shift() !== 'UTC,m,degrees_north,degrees_east,degree_C' || rows.length !== 648) {
    throw Error('Invalid ocean units/shape');
  }
  const expected = new Set(Array.from({ length: 18 }, (_, y) =>
    Array.from({ length: 36 }, (_, x) => `${-84.875 + y * 10},${5.125 + x * 10}`)).flat());
  let valid = 0;
  for (const row of rows) {
    const parts = row.split(',');
    const [time, depth, lat, lon, value] = parts;
    if (parts.length !== 5 || time !== observedAt || depth !== '0.0' ||
        !lat.trim() || !lon.trim() || !expected.delete(`${Number(lat)},${Number(lon)}`) ||
        !value.trim() || (value !== 'NaN' && (!Number.isFinite(Number(value)) || Math.abs(Number(value)) > 12))) {
      throw Error('Invalid ocean time/coordinate/measurement');
    }
    if (value !== 'NaN') valid++;
  }
  if (expected.size || !valid) throw Error('Incomplete ocean field');
  return csv;
}

async function readJson(path) {
  try { return JSON.parse(await readFile(path, 'utf8')); }
  catch (e) { if (e.code === 'ENOENT') return null; throw e; }
}
async function save(path, value) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path + '.tmp', JSON.stringify(value) + '\n');
  await rename(path + '.tmp', path);
}
async function fetchText(url, fetchImpl, timeoutMs) {
  let r;
  try {
    r = await fetchImpl(url, { signal: AbortSignal.timeout(timeoutMs), headers: { Accept: 'application/json,text/csv' } });
  } catch (error) {
    throw Error(`Source transport ${error.cause?.code ?? error.code ?? error.name}`);
  }
  if (!r.ok) throw Error(`Source HTTP ${r.status}`);
  const reader = r.body.getReader();
  const chunks = []; let size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > 1000000) throw Error('Source response exceeds 1 MB');
      chunks.push(value);
    }
  } finally { await reader.cancel().catch(() => {}); }
  return Buffer.concat(chunks).toString('utf8');
}

export async function refreshSideFeeds({ root, now = Date.now(), fetchImpl = fetch }) {
  const output = resolve(root, 'data/mobile-side-feeds');
  const checkedAt = new Date(now).toISOString();
  const status = { checkedAt, components: {} };
  const launchFile = resolve(output, 'launches.json');
  const previousLaunch = await readJson(launchFile);
  if (previousLaunch && now - Date.parse(previousLaunch.fetchedAt) >= 0 &&
      now - Date.parse(previousLaunch.fetchedAt) < 55 * 60000) {
    status.components.launches = { state: 'retained-fresh', fetchedAt: previousLaunch.fetchedAt };
  } else {
    try {
      const url = new URL(LAUNCH_SOURCE);
      url.search = new URLSearchParams({
        net__gte: new Date(now - 2 * DAY).toISOString().replace(/\.\d+Z$/, 'Z'),
        net__lte: new Date(now + 14 * DAY).toISOString().replace(/\.\d+Z$/, 'Z'),
        mode: 'normal', ordering: 'net', limit: '40', format: 'json',
      });
      const payload = validateLaunches(JSON.parse(await fetchText(url, fetchImpl, 25000)));
      // Use completion time, never rewrite the date on a retained last-good file.
      const fetchedAt = new Date().toISOString();
      await save(launchFile, { schema: 1, source: LAUNCH_SOURCE, fetchedAt, payload });
      status.components.launches = { state: 'updated', fetchedAt, count: payload.results.length };
    } catch (e) {
      status.components.launches = { state: previousLaunch ? 'stale-retained' : 'unavailable',
        fetchedAt: previousLaunch?.fetchedAt ?? null, error: String(e).slice(0, 400) };
    }
  }
  const oceanFile = resolve(output, 'ocean.json');
  const previousOcean = await readJson(oceanFile);
  const dates = oceanDates(now);
  if (previousOcean?.observedAt === dates[0] && now - Date.parse(previousOcean.fetchedAt) >= 0 &&
      now - Date.parse(previousOcean.fetchedAt) < 12 * HOUR) {
    status.components.ocean = { state: 'retained-fresh', fetchedAt: previousOcean.fetchedAt, observedAt: previousOcean.observedAt };
  } else {
    const errors = [];
    for (const observedAt of dates) {
      if (previousOcean && Date.parse(observedAt) < Date.parse(previousOcean.observedAt)) continue;
      try {
        const url = `${OCEAN_SOURCE}?anom%5B(${observedAt})%5D%5B(0.0)%5D%5B(-84.875):40:(85.125)%5D%5B(5.125):40:(355.125)%5D`;
        const payload = validateOcean(await fetchText(url, fetchImpl, 20000), observedAt);
        const fetchedAt = new Date().toISOString();
        await save(oceanFile, { schema: 1, source: OCEAN_SOURCE, observedAt, fetchedAt, payload });
        status.components.ocean = { state: 'updated', observedAt, fetchedAt };
        break;
      } catch (e) { errors.push(`${observedAt}: ${String(e).slice(0, 180)}`); }
    }
    if (!status.components.ocean) status.components.ocean = {
      state: previousOcean ? 'stale-retained' : 'unavailable', fetchedAt: previousOcean?.fetchedAt ?? null,
      observedAt: previousOcean?.observedAt ?? null, errors,
    };
  }
  await save(resolve(output, 'status.json'), status);
  return status;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = resolve(process.argv[2] ?? '.');
  const status = await refreshSideFeeds({ root });
  console.log(JSON.stringify(status, null, 2));
}
