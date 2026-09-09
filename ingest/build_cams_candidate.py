"""CAMS surface dust/PM10 and column AOD; private web only."""
import argparse, copy, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import eccodes as ec
import numpy as np
from noaa_grib import Grid

IDENTITY={210004:('kg kg**-1','hybrid',137),210005:('kg kg**-1','hybrid',137),210006:('kg kg**-1','hybrid',137),130:('K','hybrid',137),133:('kg kg**-1','hybrid',137),134:('Pa','surface',0),210074:('kg m**-3','surface',0),210207:('~','surface',0)}

def dry_density(pressure,temperature,q):
    if not (np.isfinite(pressure).all() and np.isfinite(temperature).all() and np.isfinite(q).all()):raise ValueError('Nonfinite thermodynamics')
    if np.min(pressure)<10000 or np.max(pressure)>110000 or np.min(temperature)<150 or np.max(temperature)>350 or np.min(q)<0 or np.max(q)>.06:raise ValueError('Invalid thermodynamics')
    # Ideal moist-air gas law, then dry-air mass fraction; CAMS dry-air MMR.
    return pressure/(287.058*temperature*(1+(461.5/287.058-1)*q))*(1-q)

def convert(path,fetched_at):
    if path.stat().st_size>10_000_000:raise ValueError('CAMS input exceeds bounded request')
    fields={};pv=None;clock=None;geometry=None
    with path.open('rb') as file:
        while (h:=ec.codes_grib_new_from_file(file)):
            try:
                param=ec.codes_get(h,'paramId')
                if param not in IDENTITY or param in fields:raise ValueError('Unexpected/duplicate parameter')
                field=Grid(ec.codes_get_message(h));unit,level_type,level=IDENTITY[param]
                field.require(units=unit,typeOfLevel=level_type,level=level,stepType='instant',Ni=900,Nj=451,iDirectionIncrementInDegrees=.4,jDirectionIncrementInDegrees=.4)
                c=(field.run_at,field.valid_at,field.metadata['startStep'],field.metadata['endStep'])
                if c[2]!=c[3] or (clock is not None and c!=clock):raise ValueError('Mixed CAMS model clocks')
                clock=c
                geo=(field.lat0,field.lon0,field.dx,field.dy)
                if geometry is not None and geo!=geometry:raise ValueError('Mixed grid geometry')
                geometry=geo
                if level_type=='hybrid':
                    coefficients=ec.codes_get_array(h,'pv')
                    if len(coefficients)!=276 or not np.isfinite(coefficients).all():raise ValueError('Unexpected vertical coordinate')
                    if pv is not None and not np.array_equal(pv,coefficients):raise ValueError('Mixed model levels')
                    pv=coefficients
                fields[param]=field
            finally:ec.codes_release(h)
    if set(fields)!=set(IDENTITY):raise ValueError('Incomplete CAMS bundle')
    run,valid,start,end=clock
    run_dt=datetime.fromisoformat(run);valid_dt=datetime.fromisoformat(valid)
    if (valid_dt-run_dt).total_seconds()!=end*3600 or run_dt.hour not in [0,12] or not 0<=end<=120:raise ValueError('Invalid CAMS forecast clock')
    if (datetime.fromisoformat(fetched_at)-valid_dt).total_seconds() < -300:raise ValueError('Future valid time')
    # Full-level pressure is the mean of enclosing half levels, from the GRIB PV.
    a,b=pv[:138],pv[138:]
    pressure=.5*(a[136]+a[137]+(b[136]+b[137])*fields[134].values)
    density=dry_density(pressure,fields[130].values,fields[133].values)
    dust=copy.copy(fields[210004]);dust.values=sum(fields[p].values for p in [210004,210005,210006])*density*1e9
    pm=copy.copy(fields[210074]);pm.values=pm.values*1e9
    aod=fields[210207]
    for field,ceiling in [(dust,100000),(pm,100000),(aod,30)]:
        if not np.isfinite(field.values).all() or field.values.min()<0 or field.values.max()>ceiling:raise ValueError('Invalid aerosol field')
    cells=[[lat,lon,round(dust.sample(lat,lon),1),round(pm.sample(lat,lon),1),round(aod.sample(lat,lon),3)] for lat in range(-75,76,15) for lon in range(-180,180,15)]
    return {'schema':1,'status':'local-candidate-not-production','publicationAllowed':False,
      'source':{'model':'Copernicus CAMS','dataset':'cams-global-atmospheric-composition-forecasts','url':'https://ads.atmosphere.copernicus.eu/datasets/cams-global-atmospheric-composition-forecasts','licence':'CC-BY-4.0','attribution':'Contains modified Copernicus Atmosphere Monitoring Service information (2026)','runAt':run,'forecastHour':end,'sourceGridDegrees':.4,'interpolation':'bilinear after concentration conversion','modelLevel':137,'dustDefinition':'sum of CAMS dust bins 0.03–20 um, dry-air density from co-located T/q and GRIB half-level pressure','pm10Unit':'ug/m3','aodWavelengthNm':550,'rawSha256':hashlib.sha256(path.read_bytes()).hexdigest()},
      'aerosols':{'cells':cells,'observedAt':valid,'fetchedAt':fetched_at}}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    result=convert(args.input,datetime.now(timezone.utc).isoformat().replace('+00:00','Z'))
    args.output.write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(json.dumps({'cells':len(result['aerosols']['cells']),'validAt':result['aerosols']['observedAt'],'ranges':[[min(r[i]for r in result['aerosols']['cells']),max(r[i]for r in result['aerosols']['cells'])]for i in [2,3,4]]}))
