import assert from 'node:assert/strict';
import test from 'node:test';
import { mkdtemp, readFile, writeFile, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { oceanDates, validateOcean, validateLaunches, refreshSideFeeds } from '../ingest/mobile-side-feeds.mjs';

const now = Date.now(), time = oceanDates(now)[0];
const csv = [
  'time,zlev,latitude,longitude,anom', 'UTC,m,degrees_north,degrees_east,degree_C',
  ...Array.from({ length: 648 }, (_, i) =>
    `${time},0.0,${-84.875 + Math.floor(i / 36) * 10},${5.125 + i % 36 * 10},${i === 0 ? 'NaN' : '6.21'}`),
].join('\n');
const launches = { results: [{ net: new Date(now).toISOString(), pad: { latitude: '28.5', longitude: '-80.5' } }] };

test('collector pins completed UTC days across year boundaries', () => {
  assert.deepEqual(oceanDates(Date.parse('2026-01-01T01:00Z')), [
    '2025-12-31T12:00:00Z', '2025-12-30T12:00:00Z', '2025-12-29T12:00:00Z',
  ]);
});
test('collector validates actual NOAA dates, units, grid, missing mask and raw anomalies', () => {
  assert.equal(validateOcean(csv, time), csv);
  for (const value of [csv.replace('degree_C', 'K'), csv.replace(time, '2000-01-01T12:00:00Z'),
    csv.replace('-84.875,5.125', '-74.875,5.125'), csv.replace(',6.21', ',99'),
    csv.replaceAll(',6.21', ',NaN'), csv.split('\n').slice(0, -1).join('\n')]) {
    assert.throws(() => validateOcean(value, time));
  }
});
test('collector refuses broken launch schemas and missing pad coordinates', () => {
  assert.equal(validateLaunches(launches), launches);
  assert.throws(() => validateLaunches({ error: 'upstream error' }));
  assert.throws(() => validateLaunches({ results: [{ net: new Date(now).toISOString(), pad: { latitude: null, longitude: null } }] }));
});
test('collector publishes original payloads and retains each last-good file after independent failures', async () => {
  const root = await mkdtemp(join(tmpdir(), 'terella-side-feeds-'));
  try {
    const status = await refreshSideFeeds({ root, now, fetchImpl: async url =>
      new Response(String(url).startsWith('https://ll.') ? JSON.stringify(launches) : csv) });
    assert.equal(status.components.launches.state, 'updated');
    assert.equal(status.components.ocean.state, 'updated');
    const folder = join(root, 'data/mobile-side-feeds');
    const launchBefore = await readFile(join(folder, 'launches.json'), 'utf8');
    const oceanBefore = await readFile(join(folder, 'ocean.json'), 'utf8');
    assert.deepEqual(JSON.parse(launchBefore).payload, launches);
    assert.equal(JSON.parse(oceanBefore).payload, csv);
    const later = now + 13 * 3600000;
    const failed = await refreshSideFeeds({ root, now: later, fetchImpl: async () => new Response('refused', { status: 429 }) });
    assert.equal(failed.components.launches.state, 'stale-retained');
    assert.equal(failed.components.ocean.state, 'stale-retained');
    assert.equal(await readFile(join(folder, 'launches.json'), 'utf8'), launchBefore);
    assert.equal(await readFile(join(folder, 'ocean.json'), 'utf8'), oceanBefore);
  } finally { await rm(root, { recursive: true }); }
});
test('ocean is not regressed to an older day when the newest source fails', async () => {
  const root = await mkdtemp(join(tmpdir(), 'terella-side-feeds-'));
  try {
    const folder = join(root, 'data/mobile-side-feeds');
    await mkdir(folder, { recursive: true });
    const previous = { schema: 1, source: '', observedAt: time, fetchedAt: new Date(now - 13 * 3600000).toISOString(), payload: csv };
    await writeFile(join(folder, 'ocean.json'), JSON.stringify(previous));
    let oceanCalls = 0;
    await refreshSideFeeds({ root, now, fetchImpl: async url => {
      if (String(url).startsWith('https://ll.')) return Response.json(launches);
      oceanCalls++; return new Response('missing', { status: 404 });
    } });
    assert.equal(oceanCalls, 1);
    assert.deepEqual(JSON.parse(await readFile(join(folder, 'ocean.json'), 'utf8')), previous);
  } finally { await rm(root, { recursive: true }); }
});
