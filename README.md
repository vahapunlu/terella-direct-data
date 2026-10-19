# Terella direct model processing

Standalone NOAA GFS and Copernicus CAMS/ERA5 processors and sampled public model data.

This independent public processor is authorized by the project owner. API keys are held only in encrypted CDS_API_KEY/ADS_API_KEY Actions secrets. The private application is not in this repository. Use standard public runners only. Never install these workflows in a private repository sharing mobile billing minutes.

The data is a pilot: country temperature bias is compared with ERA5 on unseen days, not certified against stations. Local polar errors can exceed country mean errors. Each file retains its actual model run and validity; a stale result must not be labelled fresh.

CAMS data: Contains modified Copernicus Atmosphere Monitoring Service information (2026), CC-BY-4.0. ERA5 data: Copernicus Climate Change Service, CC-BY-4.0. NOAA GFS: NOAA/NCEP public forecast model. Upstream dataset terms remain applicable.

Offline checks: node --test tests/*.test.mjs and python -m unittest discover -s ingest -p 'test_*.py'. Plan climate renewal with python ingest/refresh_climate_support.py --plan. Manual workflows are installed first; scheduled runs are enabled only after the initial Linux validation succeeds.

## Mobile launch and ocean side feeds

`mobile-side-feeds.yml` collects public Launch Library 2 schedules hourly and
NOAA OISST v2.1 preliminary anomaly CSV on completed UTC days (12-hour cache).
Cloudflare's shared egress was throttled by LL2 and timed out at NOAA even while
the same requests worked outside Workers. The independent source cache retains
original payloads, observation times and successful retrieval times; failed
components retain their dated last-good files. Component status is published in
`data/mobile-side-feeds/status.json`; a green workflow does not certify freshness.

This uses the existing standard public Ubuntu runner with no new secrets,
packages, artifacts or paid services. It has its own queue so hourly runs cannot
cancel a queued weather/climate job. All three writers rebase their disjoint file
commits before pushing, with bounded non-force retries. The new writer's git
allowlist contains only `data/mobile-side-feeds`. It changes no web model/calibration
files. The mobile ingest Worker validates the fixed
mirror's source/schema/age/coordinates and uses its existing direct sources as
fallback. Provider quota refusals retain the existing retry backoff.

Launch data: The Space Devs / Launch Library 2 (https://thespacedevs.com/llapi).
Ocean: NOAA NCEI OISST v2.1 preliminary via NOAA CoastWatch ERDDAP (degree C).
Only standalone public-source collection code and public data are mirrored;
no mobile UI, app bundle, account data or cloud credentials are stored here.

## Partial failures and calibration expiry

`data/refresh-status.json` records each refresh component and whether the combined
bundle was published. `data/climate-renewal-status.json` records renewal outcomes;
rejected bias candidates include the independent validation metrics and unchanged
limits. The Actions step summaries expose these reports without raw subprocess
errors or credential-bearing HTTP messages. Scientific subprocesses still fail
on rejection. Workflow notification status is separate, as described below.

A bias older than 14 days is not applied to a new forecast. The previous climate
result retains its original date. Once older than 48 hours, only an identical
JSON value already in the previous published bundle may be retained, after its
scientific structure is revalidated. This lets valid weather and aerosol updates
continue without silently publishing a new stale climate candidate. The bundle
explicitly reports `stale-retained`; web consumers keep their existing 48-hour
staleness warning. No thresholds, fitting method, or validation windows are relaxed.

## Repeated notification policy

At the owner's request, known scientific blocks no longer fail every scheduled
workflow. Before running, each job snapshots the previously published reports;
afterward it compares the new reports. The same climate expiry or same rejected
quality criterion remains `degraded`/`rejected` in those reports and in the Actions
summary, but does not generate another failed-run email. A green workflow means
no new actionable alert, **not** accepted climate data.

First/new blocks, recurrence after recovery, newly failing regions or validation
windows, unknown errors, missing reports, and download/publication failures still
alert. Operational failures are never deduplicated. Tests, clocks, scientific
acceptance, and account-wide GitHub notification settings are unchanged. Checkout
uses the latest main after the existing concurrency lock, so queued jobs compare
against the previous job's published state and do not overwrite newer reports.
