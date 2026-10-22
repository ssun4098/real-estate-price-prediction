export const LAND_START_DATE='2006-01-01';
export const REVENUE_START_DATE='2020-02-04';
export function todayKorea(now=new Date()){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);}
export const isRolling=input=>input.comparisonFilters?.periodMode==='rolling60';
/** 60 complete calendar months; no upstream coverage call or clock timer needed. */
export function rollingPeriod(today=todayKorea()){
 if(!/^\d{4}-(0[1-9]|1[0-2])-\d{2}$/.test(today))throw new Error('한국시간 기준일을 확인하세요.');
 const year=Number(today.slice(0,4)),month=Number(today.slice(5,7));
 const endExclusive=`${year}-${String(month).padStart(2,'0')}-01`,startDate=`${year-5}-${String(month).padStart(2,'0')}-01`;
 const endDate=new Date(Date.UTC(year,month-1,0)).toISOString().slice(0,10);
 return {periodMode:'rolling60',startDate,endDate,endExclusive,start:startDate.slice(0,7),end:endDate.slice(0,7),asOf:today,timezone:'Asia/Seoul',months:60};
}
/** Call only for an explicit parcel/query action, never to relabel restored data. */
export function applyRollingPeriod(input,today=todayKorea()){
 const p=rollingPeriod(today),old=input.comparisonFilters||{};
 const comparisonFilters={...old,periodMode:p.periodMode,asOf:p.asOf,start:p.start,end:p.end,landStart:p.start,landEnd:p.end,revenueStart:p.start,revenueEnd:p.end,
  landStartDate:p.startDate,revenueStartDate:p.startDate,landEndDate:p.endDate,revenueEndDate:p.endDate,endExclusive:p.endExclusive,
  periodCheckedAt:p.asOf,periodStatus:'calendar_rolling60'};
 if(input.project?.asOf===p.asOf&&JSON.stringify(old)===JSON.stringify(comparisonFilters))return input;
 return {...input,project:{...input.project,asOf:p.asOf},comparisonFilters};
}
export function rollingPeriodValid(input){
 const f=input.comparisonFilters||{};
 if(!isRolling(input)||!/^\d{4}-(0[1-9]|1[0-2])-01$/.test(f.endExclusive||''))return false;
 const p=rollingPeriod(f.endExclusive);
 return f.start===p.start&&f.end===p.end&&['land','revenue'].every(kind=>f[kind+'Start']===p.start&&f[kind+'End']===p.end&&f[kind+'StartDate']===p.startDate&&f[kind+'EndDate']===p.endDate);
}
export function rollingQueryValid(query,kind='land'){
 if(query?.periodMode!=='rolling60'||!/^\d{4}-(0[1-9]|1[0-2])-01$/.test(query.endExclusive||''))return false;
 const p=rollingPeriod(query.endExclusive);
 return (query[kind+'Start']||query.start)===p.start&&(query[kind+'End']||query.end)===p.end&&query[kind+'StartDate']===p.startDate&&query[kind+'EndDate']===p.endDate;
}
export const isLatest=input=>input.comparisonFilters?.periodMode==='latest';
export function applyLatestPeriod(input,coverage,today=todayKorea()){
 if(!isLatest(input)||!coverage)return input;
 const landEndDate=today,revenueEndDate=[coverage.revenue?.observedMaxDate,today].filter(Boolean).sort()[0];
 if(!coverage.revenue?.observedMaxDate)return input;
 return {...input,project:{...input.project,asOf:today},comparisonFilters:{...input.comparisonFilters,
  periodMode:'latest',landStart:LAND_START_DATE.slice(0,7),landEnd:landEndDate.slice(0,7),
  revenueStart:REVENUE_START_DATE.slice(0,7),revenueEnd:revenueEndDate.slice(0,7),
  start:REVENUE_START_DATE.slice(0,7),end:revenueEndDate.slice(0,7),
  landStartDate:LAND_START_DATE,revenueStartDate:REVENUE_START_DATE,landEndDate,revenueEndDate,
  periodCheckedAt:coverage.checkedAt,periodStatus:coverage.status}};
}
export function periods(input){const f=input.comparisonFilters||{};return ['separate','latest','rolling60'].includes(f.periodMode)?{landStart:f.landStart||'',landEnd:f.landEnd||'',revenueStart:f.revenueStart||'',revenueEnd:f.revenueEnd||''}:{landStart:f.start||'',landEnd:f.end||'',revenueStart:f.start||'',revenueEnd:f.end||''};}
