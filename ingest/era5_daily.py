"""Validate and sample the official ERA5 daily mean NetCDF field."""
import numpy as np
import xarray as xr

def sample_daily(path,days,sites):
 with xr.open_dataset(path,engine='netcdf4')as ds:
  if set(ds.data_vars)!={'t2m'} or ds.t2m.attrs.get('units')!='K' or ds.t2m.attrs.get('GRIB_paramId')!=167:raise ValueError('Unexpected ERA5 temperature identity')
  if not np.array_equal(ds.latitude.values,np.arange(90,-90.01,-.25)) or not np.array_equal(ds.longitude.values,np.arange(0,360,.25)):raise ValueError('Unexpected ERA5 grid')
  times=[str(x)[:10] for x in ds.valid_time.values]
  if times!=days:raise ValueError('Incomplete/unordered daily times')
  if tuple(ds.t2m.dims)!=('valid_time','latitude','longitude'):raise ValueError('Unexpected dimension order')
  values=ds.t2m.values
  result=[]
  for s in sites:
   y=(90-s['lat'])/.25;x=(s['lon']%360)/.25
   y0=int(np.floor(y));x0=int(np.floor(x));fy=y-y0;fx=x-x0
   y1=min(y0+1,720);x1=(x0+1)%1440
   v=(1-fy)*((1-fx)*values[:,y0,x0]+fx*values[:,y0,x1])+fy*((1-fx)*values[:,y1,x0]+fx*values[:,y1,x1])
   if not np.isfinite(v).all() or v.min()<150 or v.max()>350:raise ValueError('Missing/implausible temperature')
   result.append((v.astype(float)-273.15).tolist())
  return np.array(result).T

