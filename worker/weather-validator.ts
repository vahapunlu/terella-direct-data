// Validation copy for the isolated web trial; never imported by the mobile Worker.
type WeatherCell = [number, number, number, number, number];
type JetCell = [number, number, number, number];
type WeatherField = any;

const HOUR = 3_600_000;
const object = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('direct-weather: expected object');
  return v as Record<string, unknown>;
};
const number = (v: unknown, low: number, high: number): number => {
  if (typeof v !== 'number' || !Number.isFinite(v) || v < low || v > high) {
    throw new Error('direct-weather: invalid numeric field');
  }
  return v;
};
const clock = (v: unknown): number => {
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(v)) {
    throw new Error('direct-weather: invalid UTC clock');
  }
  const ms = Date.parse(v);
  // Python emits microseconds; JS stores milliseconds. Preserve original
  // strings, comparing only representable precision for calendar validation.
  const fraction = (v.includes('.') ? v.split('.')[1].slice(0, -1) : '').padEnd(3, '0').slice(0, 3);
  if (!Number.isFinite(ms) || new Date(ms).toISOString() !== `${v.slice(0, 19)}.${fraction}Z`) {
    throw new Error('direct-weather: invalid calendar date');
  }
  return ms;
};

/** Private staging is not trusted merely because it is valid JSON.
 * Approval is a separate upstream release step; local candidates stay blocked.
 * This function never changes a source clock or infers missing values as zero.
 */
export function validateDirectWeather(input: unknown, now: number, previous?: WeatherField): WeatherField {
  const envelope = object(input);
  if (envelope.schema !== 1 || envelope.status !== 'approved-direct-weather' || envelope.publicationAllowed !== true) {
    throw new Error('direct-weather: candidate is not approved for publication');
  }
  const source = object(envelope.source);
  if (source.model !== 'NOAA GFS' || source.sourceGridDegrees !== 0.25) {
    throw new Error('direct-weather: unverified source or resolution');
  }
  const run = clock(source.runAt);
  const step = number(source.forecastHour, 3, 120);
  if (!Number.isInteger(step) || step % 3 || run % (6 * HOUR)) throw new Error('direct-weather: invalid model step');
  if (!Array.isArray(source.rainWindowHours) || source.rainWindowHours.length !== 2 ||
      source.rainWindowHours[0] !== step - 3 || source.rainWindowHours[1] !== step) {
    throw new Error('direct-weather: rain is not the preceding three-hour window');
  }
  const weather = object(envelope.weather);
  const valid = clock(weather.observedAt);
  const fetched = clock(weather.fetchedAt);
  if (!Number.isFinite(now) || valid !== run + step * HOUR || valid > now + 5 * 60_000 ||
      now - valid > 12 * HOUR || run > now || now - run > 48 * HOUR || fetched < run || fetched > now + 5 * 60_000) {
    throw new Error('direct-weather: stale, future or inconsistent model clocks');
  }
  if (previous && valid < clock(previous.observedAt)) throw new Error('direct-weather: cannot regress observation time');
  const jet = object(weather.jet);
  const rain = object(weather.rain);
  for (const field of [jet, rain]) {
    if (clock(field.observedAt) !== valid || clock(field.fetchedAt) !== fetched) {
      throw new Error('direct-weather: mixed sibling clocks');
    }
  }
  if (jet.levelHpa !== 250 || jet.approximateAltitudeKm !== 10.4) throw new Error('direct-weather: wrong jet level');
  if (rain.width !== 48 || rain.height !== 24 || rain.stepDegrees !== 7.5 || rain.scaleMm !== 25 ||
      typeof rain.grid !== 'string' || rain.grid.length !== 1536 || !/^[A-Za-z0-9+/]+$/.test(rain.grid) ||
      atob(rain.grid).length !== 1152) throw new Error('direct-weather: malformed rain grid');
  const readCells = (value: unknown, length: 4 | 5): number[][] => {
    if (!Array.isArray(value) || value.length !== 264) throw new Error('direct-weather: incomplete global cells');
    return value.map((row: unknown, index) => {
      if (!Array.isArray(row) || row.length !== length || row[0] !== -75 + Math.floor(index / 24) * 15 ||
          row[1] !== -180 + (index % 24) * 15) throw new Error('direct-weather: wrong coordinate ordering');
      const result = [row[0] as number, row[1] as number, number(row[2], -250, 250), number(row[3], -250, 250)];
      if (length === 5) result.push(number(row[4], 0, 10_000));
      return result;
    });
  };
  const observedAt = weather.observedAt as string;
  const fetchedAt = weather.fetchedAt as string;
  return {
    cells: readCells(weather.cells, 5) as WeatherCell[], observedAt, fetchedAt,
    jet: { cells: readCells(jet.cells, 4) as JetCell[], levelHpa: 250, approximateAltitudeKm: 10.4, observedAt, fetchedAt },
    rain: { grid: rain.grid, width: 48, height: 24, stepDegrees: 7.5, scaleMm: 25, observedAt, fetchedAt },
  };
}
