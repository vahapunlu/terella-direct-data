const climateCodes=new Set(['seasonal-normal-expired','calibration-expired-or-overlapping']);
function reason(name,error) {
  // Never publish raw subprocess output: HTTP failures may include credentials.
  if(name==='climate') {
    try {
      const code=JSON.parse(String(error.stdout).trim()).errorCode;
      if(climateCodes.has(code))return code;
    } catch {}
  }
  return 'component-refresh-failed';
}
export async function refreshComponents(jobs,run,publish,now=()=>new Date().toISOString()) {
  const report={schema:1,checkedAt:now(),status:'complete',components:{},bundlePublished:false};
  for(const [name,program,args]of jobs) {
    try {
      await run(program,args);
      report.components[name]={status:'refreshed-or-unchanged'};
    } catch(error) {
      report.status='degraded';
      report.components[name]={status:'failed',reason:reason(name,error),previousDataRetained:true};
    }
  }
  try {await publish();report.bundlePublished=true;}
  catch {report.status='degraded';report.publicationError='bundle-validation-or-write-failed';}
  return report;
}
