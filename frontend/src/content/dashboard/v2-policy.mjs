import {calculateLand,LAND_RULE_VERSION} from './land-comparison.mjs';
import {applyFinanceAmount,financeRowSetting,calculateBudget} from './revision-model.mjs';
export const REALTIME_NOTICE='실시간 조회 영역 제외 · Geocoder 사용조건의 보관 가능 범위 확인 전 적용하는 V5 설계 기준입니다. Python 연결 후 위치 재조회가 필요합니다.';
const safeClone=x=>x==null?x:JSON.parse(JSON.stringify(x));
const secretFields=new Set('key keys apikey servicekey confmkey credentials authorization password secret token accesskey vworldapikey datagokrapikey jusoapikey vworldgeocoderapikey vworldsearchapikey kosisapikey consumerkey consumersecret accesstoken sgissecret'.split(' '));
const transientFields=new Set('geocodingstats geocodingoutcomes refinedaddress refined rawresponse geocoderresponse geocodingstate coordinatebasis coordinatesourceurl coordinateverified coordinatereturned geocodingmethod geocodingerrors distancekm'.split(' '));
const normalizedKey=key=>key.replace(/[_\-\s]/g,'').toLowerCase();
function withoutTransient(value){
 if(Array.isArray(value))return value.map(withoutTransient).filter(x=>x!==undefined);
 if(typeof value==='string'&&/^https?:\/\//i.test(value)){try{const url=new URL(value);if(url.username||url.password||[...url.searchParams.keys()].some(k=>secretFields.has(normalizedKey(k)))||/\/wmts\/1\.0\.0\/[^/]+\//.test(url.pathname))return undefined;}catch{}}
 if(!value||typeof value!=='object')return value;
 if(value.realtimeOnly===true||value.persistencePolicy==='session_only')return undefined;
 return Object.fromEntries(Object.entries(value).filter(([k])=>!secretFields.has(normalizedKey(k))&&!transientFields.has(normalizedKey(k))&&!/geocod|refinedAddress|normalizedAddress|candidateAddress/i.test(k)).map(([k,v])=>[k,withoutTransient(v)]).filter(([,v])=>v!==undefined));
}
export function isRealtimeSource(s){return !!s&&(s.realtimeOnly===true||s.persistencePolicy==='session_only'||/applyhome|revenue|geocod|분양|req\/address/i.test(['id','dataset','name','title','url','sourceUrl','service'].map(k=>s[k]||'').join(' ')));}
export function cleanSources(rows=[]){return rows.filter(s=>!isRealtimeSource(s));}
export function sanitizeInputs(value={}){
 const x=safeClone(value)||{};
 // Original parcel geometry comes from the cadastral API, not Geocoder.
 const query=x.comparables?.landQuery||x.comparables?.query||{};
 const landQuery=Object.fromEntries(['sgg','dong','legalDongCode','start','end','landStart','landEnd','asOf','landEndDate','landScope','landRawScope','landRulesVersion','ruleVersion','collectionStatus','queriedAt','landMatchPolicy','periodMode','landStartDate','endExclusive','selectedPnus'].filter(k=>query[k]!==undefined).map(k=>[k,query[k]]));
 x.comparables={landCases:x.comparables?.landCases||[],revenueCases:[],query:landQuery,landQuery,landCollectionStatus:x.comparables?.landCollectionStatus||x.sources?.find(s=>s.id==='land')?.collectionStatus||x.comparables?.collectionStatus,collectionStatus:'Python 연결 후 위치 재조회 필요',realtimeExcluded:true};
 x.landRulesVersion=LAND_RULE_VERSION;
 x.sources=cleanSources(x.sources);
 x.uiProgress={...x.uiProgress,confirmedRevenueBasis:null};
 delete x.siteSurvey;delete x.survey;delete x.map;delete x.geocodingStats;delete x.geocodingOutcomes;delete x.geocoding;delete x.coordinates;
 x.collectionStatus='저장 가능한 토지자료·사용자 가정만 보관 · 분양 위치 재조회 필요';
 return withoutTransient(x);
}
export function sanitizeSnapshot(value={}){
 const inputs=sanitizeInputs(value.inputs||{}),r=value.results||{};
 // Even the total may include revenue-dependent interest/trust calculations.
 // Preserve directly entered cost rows in inputs, not computed cost totals.
 const keepCosts={rows:safeClone(inputs.costs||[])};
 for(const key of ['profitWon','marginPct','allowableWon','allowableCostWon','allowableTotalWon','headroomWon','costGapWon','gapWon','revenueWon','netRevenueWon'])keepCosts[key]=null;
 keepCosts.status='독립 비용만 보관 · 수입 연계 결과 재조회 필요';
 const development=safeClone(r.development||{});
 for(const key of ['areaPoints','areaStats','complexes','comparisonCases'])delete development[key];
 if(inputs.linkedScenario?.enabled&&inputs.linkedScenario?.areaMode==='median'){
  for(const key of ['units','supplyAreaM2','unitSupplyAreaM2','assignedSupplyAreaM2','unassignedSupplyAreaM2','farAreaPerUnitM2'])development[key]=null;
  development.status='사례 면적에 의존하는 공급계획 · Python 연결 후 재조회 필요';
 }
 const baseline=calculateLand(inputs),landSetting=financeRowSetting(inputs,'land');
 const land={...baseline,comparableWon:baseline.representativeWon,representativeWon:applyFinanceAmount(landSetting,baseline.representativeWon),appliedSetting:landSetting,sourceStatus:landSetting.mode==='amount'?'사용자 가정':'보관 토지자료 기반 추정'};
 const revenueSetting=financeRowSetting(inputs,'revenue'),manualRevenue=revenueSetting.mode==='amount'?applyFinanceAmount(revenueSetting):null;
 const discount=inputs.assumptions?.discountPct??0,sales=inputs.assumptions?.finalSalesPct??100,full=manualRevenue!==null&&Number.isFinite(discount)&&discount>=0&&discount<=100?manualRevenue*(1-discount/100):null;
 const revenue={status:manualRevenue!==null?'사용자 가정':'Python 연결 후 위치 재조회 필요',representativeWon:manualRevenue,comparableWon:null,potentialRevenueWon:manualRevenue,fullNetRevenueWon:full,netRevenueWon:full!==null&&Number.isFinite(sales)&&sales>=0&&sales<=100?full*sales/100:null,points:[],stats:null,appliedSetting:revenueSetting};
 const budget=calculateBudget(inputs,manualRevenue,land.representativeWon);
 return withoutTransient({schemaVersion:value.schemaVersion||1,analysisVersion:'pf-study-5',appVersion:'V5',landRulesVersion:LAND_RULE_VERSION,id:value.id,name:value.name,scenario:value.scenario,createdAt:value.createdAt,inputs,results:{development,land,costs:keepCosts,revenue,budget,cashflow:{status:'실시간 수입 연계 결과 제외'},okr:{status:'실적 미확인 · 실시간 연계 결과 제외'},validation:{mode:'saved-independent-only',fieldErrors:[...(baseline.fieldErrors||[]),...budget.fieldErrors]}},sources:cleanSources(value.sources||[]),warnings:[REALTIME_NOTICE,...(baseline.comparisonReason?[baseline.comparisonReason]:[])],persistencePolicy:'v3_independent_only',realtimeExcluded:true});
}
// Radius-selected membership is itself Geocoder-dependent. Keep the shared
// downloadable evidence dataset empty; live rows remain in the authored view
// and its in-memory detail dialog. Official source links stay in query metadata.
export function publicRevenueEvidence(){return [];}
export function evaluateSite(indicators=[],criteria=[]){
 if(!criteria.length)return {score:null,reason:'평가 지표·방향·구간·가중치를 설정하세요.',rows:[]};
 const rows=criteria.map(c=>{
  const indicator=indicators.find(i=>i.id===c.indicatorId),value=indicator?.value;
  let error='';
  if(!indicator)error='지표 선택 필요';else if(!Number.isFinite(value))error='필수 지표 미확보';
  if(!['increase','decrease'].includes(c.direction))error=error||'평가 방향 필요';
  if(!Number.isFinite(c.min)||!Number.isFinite(c.max)||c.max<=c.min)error=error||'유효한 하한·상한 필요';
  if(!Number.isFinite(c.weight)||c.weight<=0||c.weight>100)error=error||'양수 가중치 필요';
  const ratio=error?null:Math.max(0,Math.min(1,(value-c.min)/(c.max-c.min)));
  return {...c,label:indicator?.label||'미선택',value,unit:indicator?.unit||'',score:ratio==null?null:(c.direction==='decrease'?1-ratio:ratio)*100,error};
 });
 const weight=rows.reduce((n,c)=>n+(Number.isFinite(c.weight)?c.weight:0),0);
 const reason=rows.find(c=>c.error)?.error||(Math.abs(weight-100)>1e-6?'가중치 합계를 100%로 설정하세요.':'');
 return {score:reason?null:rows.reduce((n,c)=>n+c.score*c.weight/100,0),reason,rows,weight};
}
