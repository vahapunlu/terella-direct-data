# Terella direct model processing

Standalone NOAA GFS and Copernicus CAMS/ERA5 processors and sampled public model data.

This independent public processor is authorized by the project owner. API keys are held only in encrypted CDS_API_KEY/ADS_API_KEY Actions secrets. The private application is not in this repository. Use standard public runners only. Never install these workflows in a private repository sharing mobile billing minutes.

The data is a pilot: country temperature bias is compared with ERA5 on unseen days, not certified against stations. Local polar errors can exceed country mean errors. Each file retains its actual model run and validity; a stale result must not be labelled fresh.

CAMS data: Contains modified Copernicus Atmosphere Monitoring Service information (2026), CC-BY-4.0. ERA5 data: Copernicus Climate Change Service, CC-BY-4.0. NOAA GFS: NOAA/NCEP public forecast model. Upstream dataset terms remain applicable.

Offline checks: node --test tests/*.test.mjs and python -m unittest discover -s ingest -p 'test_*.py'. Plan climate renewal with python ingest/refresh_climate_support.py --plan. Manual workflows are installed first; scheduled runs are enabled only after the initial Linux validation succeeds.
