// 사업성 분석 콘솔 (/console). 기존 화면(/)과 같은 서버 API와 같은 계산 규칙 모듈을 쓰고, 화면만 새로 만든다.
// 흐름: 지도에서 필지 선택 → /api/parcel(속성) → /api/boundary-allocation(용도지역 경계) → /api/site-survey(주변시설)
//       → /api/comparables(분양·토지 사례) → /api/analyze(수지 계산, 토지비 모델 예측 포함) → 화면.
// 입력을 바꾸면 브라우저 미리 계산(projectRevision)을 바로 보여 주고, 0.45초 뒤 서버 계산 결과로 바꾼다.
import {applyRollingPeriod,todayKorea} from '../../src/content/dashboard/period-policy.mjs';
import {LINKED_DEFAULTS,BUDGET_DEFAULTS,projectRevision,restoreTrustDefaults,currentBudget,financeRowSetting,calculateBudget} from '../../src/content/dashboard/revision-model.mjs';
import {sanitizeSnapshot} from '../../src/content/dashboard/v2-policy.mjs';
import {selectedParcelCenter,comparisonIdentity,invalidateChangedComparisons,replaceComparisonSources,comparisonRequest,createComparisonRequestGate} from '../../src/content/dashboard/comparison-scope.mjs';
import {createSelectionSession,canAutoQuery,confirmSelectedQuery} from '../../src/content/dashboard/selection-query.mjs';
import {mergeParcelAttributes,mergeSurveyParcels,failParcelLookup,createTaskQueue,retryBusy} from '../../src/content/dashboard/parcel-recovery.mjs';
import {boundaryAttributeIdentity,validateBoundaryAllocation,validBoundaryGeometry} from '../../src/content/dashboard/boundary-allocation.mjs';
import {adoptAnalyzedBoundaries} from '../../src/content/dashboard/boundary-adoption.mjs';
import {clearedSelectionInputs} from '../../src/content/dashboard/selection-reset.mjs';
import {assessLandCases} from '../../src/content/dashboard/land-comparison.mjs';
import {withoutRetailSurvey} from '../../src/content/dashboard/map-overlays.mjs';
import {calculationIdentity,periodErrors} from '../../src/content/dashboard/ui-workflow.mjs';
import {cleanPortfolioValue} from '../../src/content/dashboard/portfolio-samples.mjs';
import {captureScreen,buildScreenPdf} from '../../src/content/dashboard/screen-pdf.mjs';
import {fin,nf,eok,man,m2,pct,signed,esc,PY,groupLabel,rolling,forecastChart,waterfall,strip,dotPlot,heatmap,tornado,lineSeries,radar,facIcon,parcelPlan} from './charts.js';
import {uniqueSurveyParcels} from '../../src/content/dashboard/survey-summary.mjs';
import {classifyZone} from '../../src/content/dashboard/land-classification.mjs';
import {renderMap} from './map.jsx';

const $=id=>document.getElementById(id);
const COLORS=['var(--s1)','var(--s2)','var(--s3)','var(--s4)','var(--s5)'];
// 주변시설 종류: 이름과 색 (색은 기존 화면 지도 FACILITY_CATEGORIES 와 같게)
const FAC={school:['학교','#76b8ee'],mountain:['산','#c2d579'],river:['하천','#dc8ad4'],sewage:['하수처리시설','#55d9d0'],industrial:['산업단지','#b89aff']};

/* ---------- 입력 기본값 (기존 화면 LiveDashboard 의 fresh/normal 과 같은 규칙) ---------- */
const COSTS=[['land_extra','토지 부대비·명도비'],['construction','본 도급공사비'],['separate_construction','별도 공사비'],['professional','설계·감리·사업관리비'],['tax_guarantee','세금·부담금·보증료'],['marketing_operating','분양·광고·운영비'],['finance_trust','금융비·신탁보수'],['contingency','예비비']];
const fresh=()=>applyRollingPeriod({project:{name:'',scenario:'기준안',asOf:todayKorea()},parcels:[],unitPlan:[],linkedScenario:{...LINKED_DEFAULTS},budgetAllocation:{...BUDGET_DEFAULTS},comparables:{revenueCases:[],landCases:[]},uiSettings:{moneyUnit:'억원',areaUnit:'㎡',satelliteTransparency:40},uiProgress:{},planHistory:[],comparisonFilters:{periodMode:'rolling60',scope:'radius',radiusKm:5,sgg:'',dong:'',start:'',end:'',minSupplyM2:null,maxSupplyM2:null,jimok:'',landUse:'',search:''},assumptions:{revenueMethod:'median',landMethod:'median',revenueAdjustmentPct:0,landAdjustmentPct:0,targetMarginPct:null,discountPct:0,finalSalesPct:100,farPct:null,farBaseAreaM2:null},costs:COSTS.map(([id,label])=>({id,category:id,label,amountWon:null,sourceStatus:'미확보'})),cashflow:null,sources:[]});
const normal=x=>restoreTrustDefaults({...fresh(),...x,linkedScenario:{...LINKED_DEFAULTS,enabled:false,...x.linkedScenario},budgetAllocation:{...BUDGET_DEFAULTS,...x.budgetAllocation},costs:(x.costs||fresh().costs).map(c=>({...c,category:c.category||c.id})),uiSettings:{...fresh().uiSettings,...x.uiSettings},uiProgress:{...x.uiProgress},project:{...fresh().project,...x.project},assumptions:{...fresh().assumptions,targetMarginPct:null,...x.assumptions},comparisonFilters:{...fresh().comparisonFilters,periodMode:'common',start:'',end:'',landStart:'',landEnd:'',revenueStart:'',revenueEnd:'',landStartDate:undefined,landEndDate:undefined,revenueStartDate:undefined,revenueEndDate:undefined,endExclusive:undefined,scope:'dong',...x.comparisonFilters},comparables:{revenueCases:[],landCases:[],...x.comparables}});
/* 사례 포함·제외 판정 (기존 화면의 effective 와 같음).
   토지 사례 판정이 무거우므로 같은 입력에는 한 번만 계산한다 (입력은 바뀔 때마다 새 객체).
   경계 검사(validateBoundaryAllocation)는 빌드가 boundary-cache.mjs 로 바꿔 필지마다 한 번만 계산한다. */
let effectiveCache={input:null,value:null};
function effective(input){
 if(effectiveCache.input===input)return effectiveCache.value;
 const value=effectiveOf(input);effectiveCache={input,value};return value;
}
function effectiveOf(input){
 const f=input.comparisonFilters;
 const apply=r=>{const reasons=[];const baseEligible=r.baseEligible??r.eligible,baseReason=r.baseExclusionReason??r.exclusionReason;if(baseEligible===false)reasons.push(baseReason||'수집 검증 제외');if(f.minSupplyM2!=null&&r.supplyAreaM2<f.minSupplyM2)reasons.push('최소 공급면적 미달');if(f.maxSupplyM2!=null&&r.supplyAreaM2>f.maxSupplyM2)reasons.push('최대 공급면적 초과');if(f.search&&!`${r.name||''} ${r.address||''} ${r.contractor||''}`.includes(f.search))reasons.push('단지·시공사 불일치');return {...r,baseEligible,baseExclusionReason:baseReason,apiEligible:r.apiEligible??baseEligible,eligible:!reasons.length,exclusionReason:reasons.join(' · ')}};
 return {...input,comparables:{...input.comparables,revenueCases:input.comparables.revenueCases.map(apply),landCases:assessLandCases(input)}};
}

/* ---------- 상태 ---------- */
let input=fresh(),result=null,needsPreview=false,lastIdentity='',status={mode:'checking'},survey=null,surveyState={};
let baseline=null,samples=[],activeSample=null,address='',busy='',calcing=false,autoQueryPending=false,casesLoading=false;
const hist=new Map(),histLoading=new Set(),grpOff=new Set(),grpSeen=new Set(),indicators=new Map();
let showExcluded=false,boundaryState={};
const selection=createSelectionSession(),comparisonGate=createComparisonRequestGate();
const parcelQueue=createTaskQueue(2),boundaryQueue=createTaskQueue(1),surveyQueue=createTaskQueue(1);
const parcelTokens=new Map(),boundaryAttempts=new Map();
let analyzeTimer=0,analyzeVersion=0,surveySeq=0,followTimer=0,surveyTried='';
const surveyKey=()=>JSON.stringify([input.parcels.map(p=>p.pnu).sort(),input.project.asOf,input.comparisonFilters.radiusKm??5]);
const local=()=>status.mode==='local';
const parcelPending=()=>input.parcels.some(p=>['queued','loading'].includes(p.attributeState)&&parcelTokens.has(p.pnu));

async function request(url,options={}){
 const r=await fetch(url,{...options,headers:{'Content-Type':'application/json',...options.headers}});let data;
 try{data=await r.json()}catch{const e=new Error('서버 응답을 읽을 수 없습니다. 서버 실행 상태를 확인하세요.');e.status=r.status;throw e}
 if(!r.ok){const d=data?.error,e=new Error(typeof d?.message==='string'?d.message:`요청 실패 (${r.status})`);e.status=r.status;e.code=d?.code;const ra=r.headers.get('Retry-After');if(ra)e.retryAfterSeconds=Number(ra);throw e}
 return data;
}
function toast(msg,err=false){const t=$('toast');t.textContent=msg;t.className='toast on'+(err?' err':'');clearTimeout(toast.t);toast.t=setTimeout(()=>t.className='toast',err?7000:3500)}
const fail=e=>{console.error(e);toast(e.message||String(e),true)};

/* ---------- 입력 변경 · 계산 ---------- */
function setInput(next,{analyze=true}={}){
 const prev=input;next=invalidateChangedComparisons(prev,next);
 if(comparisonIdentity(prev)!==comparisonIdentity(next)){comparisonGate.cancel();casesLoading=false;if(next.comparables?.collectionStatus==='재조회 필요')autoQueryPending=true}
 input=next;if(analyze)analyzeWanted=true;
 // 지도(선택 필지 색칠)는 바로 다시 그리고, 무거운 미리 계산과 나머지 화면은 다음 순간에 한 번에 처리한다.
 drawMap({now:true});renderAll();
}
/* 입력이 서버 계산 때와 달라졌는지 확인하고, 달라졌으면 서버 계산을 예약한다. */
let analyzeWanted=false;
function refreshPreview(){
 needsPreview=calculationIdentity(effective(input))!==lastIdentity;
 if(analyzeWanted&&needsPreview)scheduleAnalyze();
 analyzeWanted=false;
}
function scheduleAnalyze(force=false){
 clearTimeout(analyzeTimer);
 if(!local()||!input.parcels.length)return;
 analyzeTimer=setTimeout(async()=>{
  const body=effective(input),id=calculationIdentity(body);
  if(!force&&id===lastIdentity&&result)return;
  const v=++analyzeVersion;calcing=true;renderStatus();
  try{
   const x=await request('/api/analyze',{method:'POST',body:JSON.stringify(body)});
   if(v!==analyzeVersion)return;
   const updated=adoptAnalyzedBoundaries(input,x.inputs);if(updated!==input)input=updated;
   result={...x,inputs:{...x.inputs,uiSettings:input.uiSettings,uiProgress:input.uiProgress,planHistory:input.planHistory}};
   lastIdentity=calculationIdentity(effective(input));needsPreview=false;activeSample=null;
   if(!baseline)baseline=summary(current());
  }catch(e){if(v===analyzeVersion)fail(e)}
  finally{if(v===analyzeVersion){calcing=false;renderAll()}}
 },force?0:450);
}
/* 화면에 보여 줄 결과. 미리 계산(projectRevision)은 입력·서버 결과가 그대로면 다시 하지 않는다. */
let currentCache=null;
function current(){
 if(!(needsPreview||!result))return result;
 if(currentCache?.input===input&&currentCache.result===result)return currentCache.value;
 const value=projectRevision(effective(input),result,{});currentCache={input,result,value};return value;
}
function summary(r){const res=r?.results||{},b=currentBudget(input,res);return {R:b.revenueWon,T:b.totalExpenseWon,P:b.profitWon,M:b.targetMarginPct,units:res.development?.units,L:b.landWon}}

/* ---------- 필지 선택 · 조회 ---------- */
/* 기존 화면 LiveDashboard.toggle 과 같은 동작 */
function toggleParcel(feature){
 const pnu=String(feature.properties?.pnu||feature.id||'');if(!/^\d{19}$/.test(pnu))return;
 const exists=input.parcels.some(p=>p.pnu===pnu);
 const parcels=exists?input.parcels.filter(p=>p.pnu!==pnu):[...input.parcels,{pnu,geometry:feature.geometry,group:'기본',areaM2:null,sourceStatus:'필지 속성 조회 중',attributeRequestedYear:todayKorea().slice(0,4)}];
 parcelTokens.delete(pnu);selection.arm(parcels);autoQueryPending=parcels.length>0;activeSample=null;
 setInput(applyRollingPeriod({...input,parcels}));
 if(!exists)fetchParcel(pnu);
 followUp();
}
/* 전체 해제: 기존 화면 LiveDashboard.clearParcels 와 같음. 필지와 필지에 딸린 조회 결과(경계·주변시설·비교사례·계산 결과)만 지우고,
   입력한 사업 가정(용적률, 보정값, 수지 항목 기준 등)은 그대로 둔다. 진행 중인 조회·계산 응답은 버린다. */
function clearParcels(){
 if(!input.parcels.length)return;
 comparisonGate.cancel();parcelTokens.clear();boundaryAttempts.clear();selection.reset();
 surveySeq++;analyzeVersion++;clearTimeout(analyzeTimer);clearTimeout(followTimer);
 autoQueryPending=false;casesLoading=false;calcing=false;busy='';
 input=clearedSelectionInputs(input);result=null;lastIdentity='';needsPreview=false;baseline=null;activeSample=null;
 boundaryState={};survey=null;surveyState={};surveyTried='';selectedPnu=null;
 drawMap({now:true});renderAll();renderSampleSelect();
 toast('선택한 필지를 모두 해제했습니다. 입력한 사업 가정은 유지됩니다.');
}
async function fetchParcel(pnu,refresh=false){
 const year=input.project.asOf.slice(0,4),token=Math.random().toString(36).slice(2);
 if(!selection.allows(input.parcels)||!input.parcels.some(p=>p.pnu===pnu)||parcelTokens.has(pnu))return;
 parcelTokens.set(pnu,token);
 const isCurrent=()=>parcelTokens.get(pnu)===token&&input.project.asOf.slice(0,4)===year&&input.parcels.some(p=>p.pnu===pnu);
 const update=fn=>setInput({...input,parcels:input.parcels.map(p=>p.pnu===pnu?fn(p):p)});
 update(p=>({...p,attributeState:'queued',attributeError:'',attributeRequestedYear:year}));
 try{await parcelQueue.enqueue(async()=>{
  if(!isCurrent())return;update(p=>({...p,attributeState:'loading'}));
  const data=await retryBusy(()=>request('/api/parcel?'+new URLSearchParams({pnu,year,refresh:refresh?'1':'0'})),{isCurrent});
  if(!data||!isCurrent())return;autoQueryPending=true;update(p=>mergeParcelAttributes(p,data,year));
 })}catch(e){if(isCurrent())update(p=>failParcelLookup(p,e.message))}
 finally{if(parcelTokens.get(pnu)===token){parcelTokens.delete(pnu);if(input.parcels.some(p=>p.pnu===pnu&&['loading','queued'].includes(p.attributeState)))update(p=>failParcelLookup(p,'조회 조건이 바뀌었습니다. 다시 조회하세요.'))}followUp()}
}
async function fetchBoundary(pnu,refresh=false){
 const parcel=input.parcels.find(p=>String(p.pnu)===String(pnu));if(!parcel)return;
 const year=input.project.asOf.slice(0,4),identity=boundaryAttributeIdentity(parcel);
 boundaryAttempts.set(String(pnu),year+'|'+identity);boundaryState={...boundaryState,[pnu]:{loading:true}};renderParcels();
 try{await boundaryQueue.enqueue(async()=>{
  const now=input.parcels.find(p=>String(p.pnu)===String(pnu));if(!now||boundaryAttributeIdentity(now)!==identity)return;
  const data=await retryBusy(()=>request('/api/boundary-allocation?'+new URLSearchParams({pnu,year,refresh:refresh?'1':'0'})));
  const canonical=data.parcel||data,allocation=data.boundaryAllocation||canonical.boundaryAllocation;
  if(String(canonical.pnu||allocation?.pnu||'')!==String(pnu)||!allocation)throw new Error('필지와 경계 응답이 일치하지 않습니다.');
  setInput({...input,parcels:input.parcels.map(p=>String(p.pnu)===String(pnu)?{...mergeParcelAttributes(p,canonical,year),boundaryAllocation:allocation}:p)});
  const cur=input.parcels.find(p=>String(p.pnu)===String(pnu)),check=validateBoundaryAllocation(cur);
  boundaryAttempts.set(String(pnu),year+'|'+boundaryAttributeIdentity(cur));
  boundaryState={...boundaryState,[pnu]:{loading:false,status:check.status,error:check.status==='ready'?'':check.reasons.join(' · ')}};
 })}catch(e){boundaryState={...boundaryState,[pnu]:{loading:false,status:'failed',error:e.message}}}
 renderParcels();followUp();
}
/* 필지 조회가 끝나면: 경계 → 주변시설 → 비교사례 순서로 이어서 조회 */
function followUp(){
 clearTimeout(followTimer);
 followTimer=setTimeout(()=>{
  if(!local()||parcelPending()||!selection.allows(input.parcels))return;
  const year=input.project.asOf.slice(0,4);
  for(const p of input.parcels){
   if(!p.attributes?.landRegister?.rows?.length||!p.attributes?.landUse?.rows?.length)continue;
   if(validateBoundaryAllocation(p).status==='ready'||boundaryState[p.pnu]?.loading||boundaryAttempts.get(String(p.pnu))===year+'|'+boundaryAttributeIdentity(p))continue;
   fetchBoundary(p.pnu);
  }
  if(!survey&&!surveyState.loading&&surveyTried!==surveyKey())runSurvey();  // 같은 선택으로는 자동 조회를 한 번만 (실패 시 '다시 조회' 버튼)
  if(canAutoQuery(input,selection,{local:local(),parcelPending:parcelPending(),busy:casesLoading,pending:autoQueryPending})){try{comparisonRequest(input);fetchCases(false)}catch{}}
 },700);
}
async function runSurvey(){
 const seq=++surveySeq,parcels=input.parcels;if(!parcels.length)return;surveyTried=surveyKey();
 const center=selectedParcelCenter(parcels),year=input.project.asOf.slice(0,4);
 surveyState={loading:true};renderLocation();
 const q=new URLSearchParams({pnus:parcels.map(p=>p.pnu).join(','),year,asOf:input.project.asOf,radiusKm:String(input.comparisonFilters.radiusKm??5),...(center?{lon:String(center.lon),lat:String(center.lat)}:{})});
 try{await surveyQueue.enqueue(async()=>{
  if(seq!==surveySeq)return;
  const data=await retryBusy(()=>request('/api/site-survey?'+q),{isCurrent:()=>seq===surveySeq});
  if(!data||seq!==surveySeq)return;
  survey=withoutRetailSurvey(data);surveyState={};
  const merged=mergeSurveyParcels(input.parcels,data.parcels,year);if(merged!==input.parcels){autoQueryPending=true;setInput({...input,parcels:merged})}
 })}catch(e){if(seq===surveySeq)surveyState={error:e.message}}
 renderLocation();drawMap();followUp();
}
async function fetchCases(refresh,explicit=false){
 if(!local()||parcelPending()||casesLoading)return;
 if(explicit&&!confirmSelectedQuery(input.parcels,selection,{local:local(),parcelPending:parcelPending()}))return toast('조회할 필지를 선택하세요.',true);
 let snap,params;
 try{const prepared=applyRollingPeriod(input);if(prepared!==input)setInput(prepared,{analyze:false});snap=input;
  const issues=periodErrors(snap,null);if(issues.length)throw new Error(issues[0].message);params=comparisonRequest(snap,refresh);
 }catch(e){return fail(e)}
 const ticket=comparisonGate.start(comparisonIdentity(snap));if(!ticket)return;
 const sessionTicket=selection.ticket();autoQueryPending=false;casesLoading=true;renderStatus();
 try{
  const d=await request('/api/comparables?'+new URLSearchParams(params),{signal:ticket.controller.signal});
  if(!comparisonGate.accepts(ticket,input)||!selection.accepts(sessionTicket,input.parcels))return;
  const f=snap.comparisonFilters;
  if(d.query?.asOf!==snap.project.asOf||d.query?.endExclusive!==f.endExclusive||d.query?.landStartDate!==f.landStartDate||d.query?.revenueStartDate!==f.revenueStartDate)throw new Error('서버 조회기간이 현재 60개월 조건과 다릅니다. 다시 조회하세요.');
  const mark=r=>({...r,apiEligible:r.eligible,baseEligible:r.eligible,baseExclusionReason:r.exclusionReason});
  setInput({...input,comparables:{...input.comparables,revenueCases:(d.revenueCases||[]).map(mark),landCases:(d.landCases||[]).map(mark),query:d.query,landQuery:d.landQuery||d.query,landCollectionStatus:d.landCollectionStatus,collectionStatus:d.collectionStatus,fromCache:d.fromCache,geocodingStats:d.geocodingStats,geocodingCollectionStatus:d.geocodingCollectionStatus,geocodingOutcomes:d.geocodingOutcomes,realtimeOnly:d.realtimeOnly,persistencePolicy:d.persistencePolicy},sources:replaceComparisonSources(input.sources,(d.sources||[]).map(x=>({...x,fromCache:!!d.fromCache}))),collectionStatus:d.collectionStatus});
  toast(d.warnings?.length?d.warnings.map(w=>typeof w==='string'?w:w.message).join(' · '):'비교사례 조회 완료');
 }catch(e){if(e.name!=='AbortError'&&comparisonGate.accepts(ticket,input))fail(e)}
 finally{comparisonGate.finish(ticket);casesLoading=false;renderAll()}
}

/* ---------- 샘플 · 저장 ---------- */
function openSnapshot(x,{display=null,label=''}={}){
 comparisonGate.cancel();parcelTokens.clear();boundaryAttempts.clear();boundaryState={};selection.reset();surveySeq++;analyzeVersion++;autoQueryPending=false;
 input=normal(x.inputs);result=x;lastIdentity=calculationIdentity(effective(input));needsPreview=false;
 survey=display?.survey||null;surveyState={};address=display?.address||'';baseline=summary(result);
 const view=display?.mapView,center=selectedParcelCenter(input.parcels);mapFocus=view&&fin(view.lat)&&fin(view.lon)?{...view}:center?{...center,z:17}:mapFocus;
 if(label)toast(label);renderAll();
}
async function loadSamples(){
 try{const d=await request('/api/portfolio-samples');samples=d.items||[];return d.defaultId}catch(e){samples=[];fail(e)}
 finally{renderSampleSelect()}
}
async function openSample(id){
 if(!id)return;busy='sample';renderStatus();
 try{const item=cleanPortfolioValue(await request('/api/portfolio-samples/'+encodeURIComponent(id)));
  if(item.persistencePolicy!=='portfolio_frozen_v1'||item.snapshot?.schemaVersion!==1)throw new Error('지원하는 저장 분석이 아닙니다.');
  activeSample=item;openSnapshot(item.snapshot,{display:item.displayState,label:`'${item.name}'을 열었습니다 · 저장 시점 결과`});
 }catch(e){fail(e)}finally{busy='';renderSampleSelect();renderStatus()}
}
async function saveSample(){
 if(!result||needsPreview||calcing||parcelPending())return toast('계산이 끝난 뒤 저장하세요.',true);
 if(!input.parcels.length)return toast('필지를 먼저 선택하세요.',true);
 const label=(String(input.project?.name||'').trim()||address.trim()||'분석').replace(/\s*·\s*\d+\s*필지\s*$/,'');
 const payload=cleanPortfolioValue({name:`${label} · ${input.parcels.length}필지`,snapshot:{...result,inputs:{...result.inputs,uiSettings:input.uiSettings,uiProgress:input.uiProgress}},displayState:{survey,address,viewState:{main:'survey',tab:'parcels'},mapView:mapView?{...mapView}:null}});
 try{const item=await request('/api/portfolio-samples',{method:'POST',body:JSON.stringify(payload)});activeSample=item;await loadSamples();toast(`'${item.name}' 저장 완료`)}catch(e){fail(e)}
}
function downloadBlob(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000)}
const fileName=s=>String(s||'사업성 분석').replace(/[\\/:*?"<>|\x00-\x1f]/g,' ').trim().slice(0,60);
function exportJson(){
 if(!result||needsPreview)return toast('계산이 끝난 뒤 내보내세요.',true);
 downloadBlob(new Blob([JSON.stringify(sanitizeSnapshot(result),null,2)],{type:'application/json'}),`${fileName(input.project.name)}_${todayKorea()}.json`);
}
async function importJson(file){
 try{if(file.size>64*1024*1024)throw new Error('64MB 이하 파일을 선택하세요.');const raw=JSON.parse(await file.text());
  if(raw?.schemaVersion!==1||!raw.inputs||!raw.results)throw new Error('지원하는 분석 결과 파일이 아닙니다.');
  activeSample=null;openSnapshot(sanitizeSnapshot(raw),{label:'파일을 열었습니다 · 값을 바꾸면 다시 계산합니다'});
 }catch(e){fail(e)}
}
async function exportPdf(){
 if(calcing||parcelPending()||casesLoading)return toast('조회·계산이 끝난 뒤 저장하세요.',true);
 const btn=$('pdfBtn');btn.disabled=true;btn.textContent='PDF 만드는 중…';document.body.classList.add('capturing');printing=true;drawMap();
 const controller=new AbortController(),cache=new Map(),pages=[];
 try{
  await new Promise(r=>setTimeout(r,250));
  for(const id of ['page1','page2','page3','page4','page5']){const el=$(id),rect=el.getBoundingClientRect();pages.push(await captureScreen(el,{width:Math.ceil(rect.width),height:Math.ceil(rect.height),pixelRatio:2,backgroundColor:'#0D1117',signal:controller.signal,resourceCache:cache}))}
  downloadBlob(new Blob([buildScreenPdf(pages)],{type:'application/pdf'}),`${fileName(input.project.name)}_분석콘솔_${todayKorea()}.pdf`);
  toast('PDF 5쪽을 저장했습니다');
 }catch(e){fail(e)}
 finally{document.body.classList.remove('capturing');printing=false;drawMap();btn.disabled=false;btn.textContent='PDF 저장'}
}

/* ---------- 지도 (기존 화면 부품 SatelliteMap 그대로) ---------- */
let mapFocus=null,mapView=null,selectedPnu=null,printing=false;
let shown=null;  // 마지막으로 화면에 그린 결과 (지도를 먼저 그릴 때 씀)
function drawMap({now=false}={}){
 const r=shown||current();
 renderMap($('mapRoot'),{
  mode:status.mode,parcels:input.parcels,land:r.results?.land||{},boundaryState,onBoundaryRetry:retryBoundary,
  facilities:survey?.facilities?.items||[],referenceFeatures:survey?.facilities?.referenceFeatureCollection?.features||[],
  selectedPnu,onInspectParcel:pnu=>{selectedPnu=pnu;drawMap()},onToggle:toggleParcel,onNotice:msg=>toast(msg),
  focus:mapFocus,onViewChange:view=>{mapView=view},printing,
  transparency:input.uiSettings?.satelliteTransparency??40,
  onTransparencyChange:v=>setInput({...input,uiSettings:{...input.uiSettings,satelliteTransparency:v}},{analyze:false}),
 },{now});
}
const retryBoundary=pnu=>{if(pnu)fetchBoundary(pnu,true);else input.parcels.forEach(p=>fetchBoundary(p.pnu,true))};
function parcelStatus(p){
 if(['queued','loading'].includes(p.attributeState))return ['wait','속성 조회 중'];
 if(p.attributeState==='failed'||p.attributeError)return ['err',p.attributeError||'조회 실패'];
 const b=boundaryState[p.pnu];if(b?.loading)return ['wait','경계 조회 중'];
 const v=p.attributes?validateBoundaryAllocation(p):null;
 if(v&&v.status!=='ready')return ['wait','경계 보류 · '+(v.reasons||[]).slice(0,1).join('')];
 return ['ok','조회 완료'];
}
const jibun=p=>{const r=p.attributes?.landRegister?.rows?.[0];return r?.mnnmSlno||String(p.address||'').split(' ').pop()||p.pnu.slice(-8)};
async function searchAddress(){
 const q=$('addr').value.trim();if(!q)return;address=q;
 try{const d=await request('/api/address?keyword='+encodeURIComponent(q));const c=d.candidates||[];
  $('cands').innerHTML=c.length?c.slice(0,200).map((a,i)=>`<button type="button" data-cand="${i}">${esc(a.address||a.label)}<small>${esc(a.roadAddress||a.jibunAddress||'')}</small></button>`).join('')+(d.truncated?'<button type="button" disabled>결과가 많아 일부만 보입니다 · 주소를 더 자세히 입력하세요</button>':''):'<button type="button" disabled>검색 결과가 없습니다</button>';
  $('cands').hidden=false;$('cands').data=c;
 }catch(e){fail(e)}
}
async function goCandidate(a){
 $('cands').hidden=true;
 try{let p=fin(a.lon)&&fin(a.lat)?a:null;
  if(!p){const r=await request('/api/address?keyword='+encodeURIComponent(a.address||a.label));p=(r.candidates||[]).find(c=>fin(c.lon)&&fin(c.lat)&&c.address===a.address)||null}
  if(!p)throw new Error('이 주소의 좌표를 찾지 못했습니다. 지도를 직접 이동하세요.');
  mapFocus={lon:p.lon,lat:p.lat,z:18};drawMap();
 }catch(e){fail(e)}
}

/* ---------- 사업지 도면 (지목·용도지역) ---------- */
// 지목 색 (흔한 지목만 정하고 나머지는 차례로)
const JIMOK_COLOR={전:'#D9B26F',답:'#7FC8C0',대:'#F08C7A',임야:'#5FA866',공장용지:'#A78BDA',도로:'#8A94A6',잡종지:'#C7A0C9',하천:'#6EA8E0',구거:'#5B8FC9',유지:'#4F9FD1',묘지:'#B7B7B7',주차장:'#9AA7B8',창고용지:'#C98F6B',학교용지:'#E6C35C',과수원:'#B9D66B',목장용지:'#A8C77F',철도용지:'#7D7F8C',공원:'#4FB98A',종교용지:'#D9A3B8'};
// 용도지역 색 (도시계획 도면의 관례: 주거=노랑~주황, 상업=분홍·빨강, 공업=보라, 녹지·관리=초록 계열)
const ZONE_COLOR=[[/제1종전용주거/,'#FFF2A8'],[/제2종전용주거/,'#FFE98A'],[/제1종일반주거/,'#FFE070'],[/제2종일반주거/,'#F5C94E'],[/제3종일반주거/,'#E8B03A'],[/준주거/,'#E39540'],[/상업/,'#E8707E'],[/공업/,'#A98BE0'],[/보전녹지/,'#3E9B5A'],[/생산녹지/,'#7CC36A'],[/자연녹지/,'#A7D98C'],[/보전관리/,'#6FAE8A'],[/생산관리/,'#C9C47A'],[/계획관리/,'#D9B88A'],[/관리지역/,'#CDBB8F'],[/농림/,'#B5CF6B'],[/자연환경보전/,'#4F8F6F']];
const SPARE=['#7AA7FF','#E58FD3','#C9D36B','#4FD1A5','#F2A65A','#B392F0'];
const colorFor=(map,name,used)=>{if(map[name])return map[name];if(!used.has(name))used.set(name,SPARE[used.size%SPARE.length]);return used.get(name)};
const zoneColor=name=>(ZONE_COLOR.find(([re])=>re.test(name))||[])[1]||'#9AA7B8';
function planLegend(rows,total){
 return rows.sort((a,b)=>b.area-a.area).map(x=>`<div data-tip="${esc(x.name)} · ${x.pnus.size}필지 · ${m2(x.area)}"><i style="${x.hatch?'background:repeating-linear-gradient(45deg,var(--panel-2) 0 3px,var(--muted) 3px 5px)':`background:${x.color}`}"></i><b>${esc(x.name)}</b><span>${kv('필지',nf(x.pnus.size))}${kv('면적',nf(x.area)+'㎡')}${total>0?kv('비율',nf(x.area/total*100,0)+'%'):''}</span></div>`).join('');
}
function renderPlans(){
 const ps=uniqueSurveyParcels(input.parcels).filter(p=>p.geometry),number=new Map(uniqueSurveyParcels(input.parcels).map((p,i)=>[String(p.pnu),i+1]));
 const outline=ps.map(p=>({geometry:p.geometry,number:number.get(String(p.pnu))}));
 const name=p=>`${number.get(String(p.pnu))}번 ${jibun(p)}`;
 // 지목: 토지대장 지목으로 필지 전체를 칠한다
 const jUsed=new Map(),jRows=new Map(),jFills=[];
 for(const p of ps){const j=p.attributes?.landRegister?.rows?.[0]?.lndcgrCodeNm||'미확인',c=j==='미확인'?'#5A6472':colorFor(JIMOK_COLOR,j,jUsed),a=fin(p.areaM2)?p.areaM2:0;
  jFills.push({geometry:p.geometry,color:c,tip:`${name(p)} · 지목 ${j} · ${m2(p.areaM2)}`});const row=jRows.get(j)||{name:j,color:c,area:0,pnus:new Set()};row.area+=a;row.pnus.add(p.pnu);jRows.set(j,row)}
 // 용도지역: 검증된 경계 배분(필지 안 용도지역별 도형)을 쓰고, 없으면 토지이용계획의 용도지역이 하나일 때만 필지 전체를 그 색으로. 둘 이상인데 경계가 없으면 '경계 미확정'
 const zRows=new Map(),zFills=[],add=(n,c,a,pnu,hatch=false)=>{const row=zRows.get(n)||{name:n,color:c,area:0,pnus:new Set(),hatch};row.area+=a;row.pnus.add(pnu);zRows.set(n,row)};
 for(const p of ps){const check=validateBoundaryAllocation(p),parts=check.status==='ready'?(check.parts||[]).filter(x=>validBoundaryGeometry(x.geometry)):[];
  if(parts.length){for(const x of parts){const n=x.zoneName||'용도지역 미확인',c=zoneColor(n),a=fin(x.allocatedAreaM2)?x.allocatedAreaM2:0;zFills.push({geometry:x.geometry,color:c,tip:`${name(p)} · ${n} · ${m2(x.allocatedAreaM2)}${fin(x.ratio)?` (${nf(x.ratio*100,0)}%)`:''}`});add(n,c,a,p.pnu)}continue}
  const zones=[...new Map((p.attributes?.landUse?.rows||[]).filter(x=>['1','2'].includes(String(x.cnflcAt))).map(x=>[x,classifyZone(x.prposAreaDstrcCodeNm,x.prposAreaDstrcCode)]).filter(([,z])=>z.status==='ready').map(([x,z])=>[z.code,x.prposAreaDstrcCodeNm])).values()];
  const a=fin(p.areaM2)?p.areaM2:0;
  if(zones.length===1){const n=zones[0],c=zoneColor(n);zFills.push({geometry:p.geometry,color:c,tip:`${name(p)} · ${n} · ${m2(p.areaM2)} (토지이용계획 기준)`});add(n,c,a,p.pnu)}
  else{const n=p.attributes?'경계 미확정':'조회 중';zFills.push({geometry:p.geometry,hatch:true,tip:`${name(p)} · ${zones.length>1?zones.join(', ')+' · ':''}${n}`});add(n,null,a,p.pnu,true)}}
 const total=ps.reduce((t,p)=>t+(fin(p.areaM2)?p.areaM2:0),0),opt={w:widthOf('jimokPlan',640),h:360};
 $('jimokPlan').innerHTML=parcelPlan({fills:jFills,parcels:outline},opt);$('zonePlan').innerHTML=parcelPlan({fills:zFills,parcels:outline},{...opt,w:widthOf('zonePlan',640)});
 $('jimokLegend').innerHTML=planLegend([...jRows.values()],total);$('zoneLegend').innerHTML=planLegend([...zRows.values()],total);
 $('jimokSum').textContent=ps.length?`${jRows.size}종 · ${ps.length}필지`:'';$('zoneSum').textContent=ps.length?`${[...zRows.values()].filter(x=>!x.hatch).length}개 용도지역`:'';
}
/* ---------- 화면 그리기 ---------- */
/* 차트를 칸의 실제 폭으로 그린다 (글씨가 CSS 크기 그대로 보이도록; 칸이 넓어져도 글씨가 따라 커지지 않음) */
const widthOf=(id,fallback)=>{const w=$(id)?.clientWidth;return w&&w>200?Math.round(w):fallback};

/* 지금 진행 중인 일. 상단 상태 표시, 진행 막대, KPI 스켈레톤이 모두 이것 하나를 본다.
   kpi: 이 일이 끝나야 KPI 값(수입·지출·수익률 등)이 확정되는지 (주변시설 조회는 KPI와 무관) */
function workState(){
 const step=parcelPending()?'필지 조회 중':Object.values(boundaryState).some(s=>s.loading)?'용도지역 경계 조회 중':casesLoading?'비교사례 조회 중':calcing?'서버 계산 중':busy==='sample'?'샘플 여는 중':'';
 if(step)return {kind:'busy',text:step,kpi:true};
 if(surveyState.loading)return {kind:'busy',text:'주변시설 조회 중',kpi:false};
 if(status.mode==='checking')return {kind:'busy',text:'서버 확인 중',kpi:true};
 if(!local())return {kind:'off',text:'서버 연결 안 됨 · 보기 전용',kpi:false};
 if(activeSample)return {kind:'saved',text:'저장 시점 결과',kpi:false};
 if(needsPreview&&input.parcels.length)return {kind:'busy',text:'계산 준비 중',kpi:true};
 if(!input.parcels.length)return {kind:'idle',text:'필지를 선택하세요',kpi:false};
 return {kind:'done',text:'서버 계산 완료',kpi:false};
}
function renderStatus(){
 const r=current(),b=currentBudget(input,r.results||{});
 $('siteTag').textContent=input.parcels.length?`${input.parcels[0]?.attributes?.landRegister?.rows?.[0]?.ldCodeNm||input.parcels[0]?.legalDongName||'선택 지역'} · ${input.parcels.length}필지`:'사업지 미선택';
 const w=workState(),t=$('calcTag');
 t.className='status '+w.kind;t.querySelector('.status-text').textContent=w.text;
 $('busyBar').hidden=w.kind!=='busy';
 // 계산 중 ↔ 완료가 바뀌면 KPI 스켈레톤도 바로 바꾼다
 const kpiBusy=w.kpi&&input.parcels.length>0;if(kpiBusy!==renderStatus.kpiBusy){renderStatus.kpiBusy=kpiBusy;renderKpis(r)}
 const note=[];if(!local())note.push('서버에 연결되지 않아 조회·계산을 할 수 없습니다.');if(activeSample)note.push('저장 샘플은 저장 당시 결과입니다. 값을 바꾸거나 다시 계산을 누르면 현재 규칙·모델로 계산합니다.');
 $('asideNote').textContent=note.join(' ');
}
function renderControls(){
 const set=(id,v)=>{const el=$(id);if(el&&document.activeElement!==el)el.value=v??''};
 const ls={...LINKED_DEFAULTS,...input.linkedScenario},a=input.assumptions;
 set('projName',input.project.name);set('asOf',input.project.asOf);
 set('far',ls.farPct);set('farMax',ls.farMaxPct);document.querySelector('[data-for="far"]').max=ls.farMaxPct||500;document.querySelector('[data-for="far"]').value=ls.farPct??0;
 // 호당 ㎡: '비교단지 중앙값'이면 계산에 쓰인 중앙값을 보여 주고(읽기 전용), '직접 입력'이면 입력값 (2026-10-30 요청: 공란이던 칸)
 const unitMedian=(shown||current()).results?.development?.unitSupplyAreaM2,manual=ls.areaMode==='manual',ma=$('manualArea');
 set('manualArea',manual?ls.supplyAreaM2:fin(unitMedian)?Math.round(unitMedian*10)/10:'');ma.readOnly=!manual;ma.title=manual?'호당 공급면적 직접 입력':'비교단지 중앙값에서 자동으로 정해집니다. 바꾸려면 ‘직접 입력’을 누르세요.';ma.placeholder=manual?'':'계산 후 표시';
 document.querySelectorAll('[data-area]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.area===ls.areaMode));
 set('revAdj',a.revenueAdjustmentPct??0);document.querySelector('[data-for="revAdj"]').value=a.revenueAdjustmentPct??0;
 set('landAdj',a.landAdjustmentPct??0);document.querySelector('[data-for="landAdj"]').value=a.landAdjustmentPct??0;
 document.querySelectorAll('[data-method]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.method===(a.revenueMethod||'median')));
 set('radius',input.comparisonFilters.radiusKm??5);
 for(const id of ['far','farMax','manualArea','revAdj','landAdj','radius','requery','recalc','projName','asOf'])$(id).disabled=!local();
}
// 이름표 + 값 (회색 이름표, 밝은 값) — KPI 아래 줄과 도면 범례에서 씀
const kv=(label,value)=>`<span class="kv"><em>${esc(label)}</em><strong>${value}</strong></span>`;
function delta(v,b,fmt,goodUp=true){if(!fin(v)||!fin(b))return '<span class="flat">—</span>';const d=v-b;if(Math.abs(d)<1e-6)return '';/* 기준안과 같으면 아무것도 쓰지 않는다 (2026-10-30 요청) */return `<span class="${(goodUp?d>0:d<0)?'up':'dn'}">${d>0?'▲':'▼'} ${fmt(Math.abs(d))} vs 기준안</span>`}
function renderKpis(r){
 const res=r.results||{},b=currentBudget(input,res),dev=res.development||{},land=res.land||{},m=b.targetMarginPct,t=!fin(m)?'ink':m<100?'bad':m<110?'warn':'good',B=baseline||{};
 const K=[['예상 총수입',eok(b.revenueWon,1),delta(b.revenueWon,B.R,v=>eok(v,1))],['예상 총지출',eok(b.totalExpenseWon,1),delta(b.totalExpenseWon,B.T,v=>eok(v,1),false)],['사업이익',eok(b.profitWon,1),delta(b.profitWon,B.P,v=>eok(v,1))],['목표 수익률',`<span style="color:var(--${t})">${pct(m,2)}</span>`,delta(m,B.M,v=>nf(v,2)+'%p')],['공급',fin(dev.units)?nf(dev.units)+'호':'—',kv('연면적',m2(dev.supplyAreaM2))+kv('대지면적',m2(dev.landAreaM2))+kv('용적률',`${nf(input.linkedScenario?.farPct)}%`)],['토지비 비중',fin(b.landWon)&&fin(b.totalExpenseWon)&&b.totalExpenseWon>0?pct(b.landWon/b.totalExpenseWon*100):'—',kv(land.amountBasis==='model'?'모델 예측':'실거래 비교',eok(b.landWon,1))]];
 // 계산이 끝나지 않았으면 값 대신 움직이는 회색 막대(스켈레톤)를 보여 준다. 값이 없고 할 일도 없으면 이유를 적는다.
 const w=workState(),loading=w.kpi&&input.parcels.length>0,why=!input.parcels.length?'필지를 선택하면 계산합니다':'자료가 부족해 계산하지 못했습니다';
 K.forEach(([l,v,d],i)=>{const el=$('k'+(i+1));el.classList.toggle('loading',loading);el.setAttribute('aria-busy',String(loading));
  el.innerHTML=loading?`<h3>${l}<span class="r kpi-wait">${esc(w.text)}</span></h3><div class="v"><span class="skel skel-v"></span></div><div class="d"><span class="skel skel-d"></span></div>`
   :`<h3>${l}</h3><div class="v">${v}</div><div class="d">${String(v).includes('—')?`<span class="flat">${why}</span>`:d}</div>`});
}
function renderParcels(){
 const ps=input.parcels,area=ps.reduce((t,p)=>t+(fin(p.areaM2)?p.areaM2:0),0);
 $('parcelSum').textContent=ps.length?`${ps.length}필지 · ${m2(area)}`:'';$('clearParcels').disabled=!ps.length;
 // 필지 줄: 지번 · '지목 전'(색 없음, 지목 이름만 굵게) · 용도지역 라벨(도면과 같은 색) / 면적 · PNU (2026-10-30 요청)
 const chip=(text,color,title,key='')=>`<span class="tagc${color?'':' neutral'}"${color?` style="--c:${color}"`:''} title="${esc(title)}">${key?`<i>${key}</i>`:''}${esc(text)}</span>`;
 $('parcelList').innerHTML=ps.length?ps.map(p=>{const [s,t]=parcelStatus(p),reg=p.attributes?.landRegister?.rows?.[0]||{},rows=(p.attributes?.landUse?.rows||[]).filter(x=>String(x.prposAreaDstrcCode||'').startsWith('UQA')&&['1','2'].includes(String(x.cnflcAt)));
  const zones=[...new Map(rows.map(x=>[x.prposAreaDstrcCodeNm,classifyZone(x.prposAreaDstrcCodeNm,x.prposAreaDstrcCode).status==='ready'])).entries()].sort((a,b)=>b[1]-a[1]);
  const j=reg.lndcgrCodeNm,labels=(j?`<span class="pjm"><i>지목</i><b>${esc(j)}</b></span>`:'')+(zones.length?zones.map(([n,ready])=>ready?chip(n,zoneColor(n),'용도지역'):chip(n,null,'용도지역 (큰 구분)')).join(''):`<span class="tagc neutral">${p.attributes?'용도지역 없음':'용도지역 확인 중'}</span>`);
  return `<div class="prow"><div class="pmain"><div class="pline"><b class="pjb">${esc(jibun(p))}</b>${labels}</div><div class="pmeta"><span><em>면적</em><strong>${p.areaM2?m2(p.areaM2):'확인 중'}</strong></span><span><em>PNU</em><span class="pnu">${p.pnu}</span></span></div></div><span class="state ${s==='ok'?'ok':s==='err'?'err':'wait'}" title="${esc(t)}">${esc(t.split(' · ')[0])}</span><button class="x" type="button" data-remove="${p.pnu}" aria-label="${esc(jibun(p))} 선택 해제">×</button></div>`}).join('')+(ps.some(p=>parcelStatus(p)[0]==='err')?`<button class="btn sm" type="button" id="retryParcels" style="margin-top:8px">실패한 필지 다시 조회</button>`:''):'<p class="empty">주소로 이동하거나 지도를 16단계 이상 확대한 뒤 필지를 눌러 선택하세요.</p>';
 drawMap();renderStatus();
}
function forecastGroups(r){
 const est=r.results?.land?.modelEstimate,rows=est?.rows||[],by=new Map();
 for(const x of rows){const k=x.landGroupKey,u=x.unitPriceKrwPerM2;if(!k||!fin(u))continue;const g=by.get(k)||{key:k,label:groupLabel(k),unit:u,targetMonth:x.targetMonth,fromMonth:x.forecastMonth,areaM2:0};g.areaM2+=fin(x.areaM2)?x.areaM2:0;by.set(k,g)}
 return [...by.values()].sort((a,b)=>b.areaM2-a.areaM2);
}
async function ensureHistory(keys){
 const need=keys.filter(k=>!hist.has(k)&&!histLoading.has(k));if(!need.length||!local())return;
 need.forEach(k=>histLoading.add(k));
 try{const d=await request('/api/console/land-history?keys='+encodeURIComponent(need.join(',')));for(const s of d.series||[])hist.set(s.key,rolling(s.points))}catch(e){need.forEach(k=>hist.set(k,[]))}
 finally{need.forEach(k=>histLoading.delete(k));renderForecast(current())}
}
function renderForecast(r){
 const land=r.results?.land||{},est=land.modelEstimate,groups=forecastGroups(r);
 $('modelTag').textContent=est?.used===false||!est?'모델 예측 없음':`${est.model||'토지가격 모델'}${est.version?' '+est.version:''}`;
 if(!groups.length){$('grpChips').innerHTML='';$('fc').innerHTML=`<p class="empty">${esc(est?.reason||(activeSample?'저장 시점 결과에는 모델 예측이 없습니다. 왼쪽 ‘다시 계산’을 누르면 현재 모델로 예측합니다.':'필지를 선택하고 계산이 끝나면 토지 그룹별 예측이 나옵니다.'))}</p>`;
  $('fcTable').innerHTML=`<div class="fc-row"><span>실거래 비교 토지비</span><span class="num" style="text-align:right">${eok(land.comparablesRepresentativeWon??land.representativeWon,1)}</span><span></span></div>`;$('fcAlert').hidden=true;return}
 ensureHistory(groups.map(g=>g.key));
 // 처음 보는 그룹은 면적이 큰 3개만 켜 둔다 (선이 많으면 라벨이 겹쳐 읽기 어려움). 나머지는 위 칩을 눌러 켠다.
 groups.forEach((g,i)=>{if(!grpSeen.has(g.key)){grpSeen.add(g.key);if(i>=3)grpOff.add(g.key)}});
 const shown=groups.map((g,i)=>({...g,color:COLORS[i%COLORS.length],points:hist.get(g.key)||[]}));
 $('grpChips').innerHTML=shown.map(g=>`<button class="chip" type="button" data-grp="${esc(g.key)}" aria-pressed="${!grpOff.has(g.key)}"><i style="background:${g.color}"></i>${esc(g.label)}</button>`).join('');
 const vis=shown.filter(g=>!grpOff.has(g.key));
 // 2026-10-30 요청: 단가는 평당으로 보여 준다 (모델·자료는 ㎡당 → 평당 = ㎡당 × 3.3058)
 const perPy=g=>({...g,unit:fin(g.unit)?g.unit*PY:g.unit,points:g.points.map(p=>[p[0],fin(p[1])?p[1]*PY:p[1],p[2],fin(p[3])?p[3]*PY:p[3]])});
 $('fc').innerHTML=vis.some(g=>g.points.length)||!vis.length?forecastChart((vis.length?vis:shown.slice(0,1)).map(perPy),{w:widthOf('fc',820),h:380,asOf:input.project.asOf.slice(0,7)}):'<p class="empty">추이 자료 불러오는 중…</p>';
 const last=g=>g.points.filter(p=>fin(p[3])).at(-1);
 const rows=est.rows||[],filled=rows.filter(x=>!fin(x.unitPriceKrwPerM2)),filledArea=filled.reduce((t,x)=>t+(fin(x.areaM2)?x.areaM2:0),0);
 $('fcTable').innerHTML=`<div class="fc-row sub"><span>그룹 · 사업지 면적</span><span style="text-align:right">최근→예측 만원/평</span><span style="text-align:right">변화</span></div>`+shown.map(g=>{const l=last(g),c=l?(g.unit/l[3]-1)*100:null;return `<div class="fc-row"><span><i style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${g.color};margin-right:6px"></i>${esc(g.label)}<br><span class="sub">${nf(g.areaM2)}㎡ · ${esc(g.targetMonth||'')} 예측</span></span><span class="num" style="text-align:right">${l?nf(l[3]*PY/1e4,1):'—'} → <b>${nf(g.unit*PY/1e4,1)}</b></span><span class="num ${fin(c)?c<0?'dn':'up':'flat'}" style="text-align:right">${fin(c)?signed(c,1):'—'}</span></div>`}).join('')+(filled.length?`<div class="fc-row"><span>예측 없는 ${filled.length}필지<br><span class="sub">${nf(filledArea)}㎡ · 평균 단가로 채움</span></span><span class="num" style="text-align:right">평균 <b>${nf((est.averageUnitPriceKrwPerM2??est.averageUnitWonM2??NaN)*PY/1e4,1)}</b></span><span class="num flat" style="text-align:right">—</span></div>`:'')+`<div class="fc-row"><span><b>토지비 합계</b><br><span class="sub">실거래 비교 ${eok(land.comparablesRepresentativeWon,1)}</span></span><span class="num" style="text-align:right"><b>${eok(est.totalWon??land.representativeWon,1)}</b></span><span class="num ${fin(land.comparablesRepresentativeWon)&&land.comparablesRepresentativeWon>0?'':'flat'}" style="text-align:right">${fin(land.comparablesRepresentativeWon)&&land.comparablesRepresentativeWon>0?signed(((est.totalWon??land.representativeWon)/land.comparablesRepresentativeWon-1)*100,0):'—'}</span></div>`;
 const thin=shown.filter(g=>g.points.length&&g.points.filter(p=>p[0]>=shiftMonth(input.project.asOf.slice(0,7),-12)).reduce((t,p)=>t+p[2],0)<6);
 $('fcAlert').hidden=!thin.length;$('fcAlert').textContent=thin.length?`${thin.map(g=>`'${g.label}'`).join(', ')}은 최근 1년 거래가 6건 미만이라 예측과 추이가 크게 흔들릴 수 있습니다.`:'';
}
const shiftMonth=(m,k)=>{const [y,mm]=m.split('-').map(Number),t=y*12+mm-1+k;return `${Math.floor(t/12)}-${String(t%12+1).padStart(2,'0')}`};
/* 수지 항목 표 (기존 화면 FinanceRow 와 같은 규칙: 공사비% 기본값은 지출%로 환산해 표시) */
const MODE_LABEL={comparablePct:'사례%',amount:'금액',areaUnit:'평당',budgetPct:'지출%',revenuePct:'수입%'};
function financeRow(id,label,b,r){
 const s=financeRowSetting(input,id),landModel=id==='land'&&r.results?.land?.amountBasis==='model';
 const applied=id==='revenue'?b.revenueWon:id==='land'?b.landWon:id==='trust'?b.trustWon:b.allocationRows?.find(x=>x.id===id)?.amountWon;
 const fromC=s.mode==='constructionPct',shown=fromC?'budgetPct':s.mode,amount=shown==='amount';
 const value=fromC?(fin(applied)&&fin(b.totalExpenseWon)&&b.totalExpenseWon>0?Math.round(applied/b.totalExpenseWon*1e4)/100:''):fin(s.value)?+(s.value/(amount?1e8:1)).toFixed(amount?2:2):'';
 const choices=id==='revenue'||id==='land'?[['comparablePct',landModel?'모델%':'사례%'],['amount','금액']]:id==='construction'?[['areaUnit','평당'],['budgetPct','지출%'],['revenuePct','수입%'],['amount','금액']]:id==='trust'?[['revenuePct','수입%'],['budgetPct','지출%'],['amount','금액']]:[['budgetPct','지출%'],['revenuePct','수입%'],['amount','금액']];
 const unit=amount?'억':shown==='areaUnit'?'만원/평':'%';
 return `<div class="frow"><span>${esc(label)}</span><select data-fmode="${id}" aria-label="${esc(label)} 기준" ${local()?'':'disabled'}>${choices.map(([v,l])=>`<option value="${v}" ${v===shown?'selected':''}>${l}</option>`).join('')}</select><input data-fval="${id}" inputmode="decimal" value="${value}" aria-label="${esc(label)} 값 (${unit})" title="${fromC?`기본값: 허용 공사비의 ${s.value}%를 총지출 대비로 표시`:unit}" ${local()?'':'disabled'}><span class="amt" data-amt="${id}">${eok(applied,2)}</span>${fromC?`<span class="why">기본값 · 허용 공사비의 ${s.value}%</span>`:id==='land'&&landModel?`<span class="why">모델 예측 ${eok(r.results.land.representativeWon,1)} 기준</span>`:''}</div>`;
}
function renderFinance(r){
 const res=r.results||{},b=currentBudget(input,res);
 $('totalTag').textContent='총지출 '+eok(b.totalExpenseWon,2);
 const parts=[['토지비',b.landWon,'var(--land)'],['공사비',b.allocationRows?.find(x=>x.id==='construction')?.amountWon,'var(--build)'],['간접·분양·제세',['indirect','sales','tax'].reduce((t,id)=>t+(b.allocationRows?.find(x=>x.id===id)?.amountWon||0),0),'var(--soft)'],['금융·신탁',(b.allocationRows?.find(x=>x.id==='finance')?.amountWon||0)+(b.trustWon||0),'var(--fin)']];
 $('costbar').innerHTML=fin(b.totalExpenseWon)&&b.totalExpenseWon>0?`<div class="costbar">${parts.map(([l,v,c])=>`<i style="flex:${Math.max(0,v||0)};background:${c}" data-tip="${l} ${eok(v)} · ${pct((v||0)/b.totalExpenseWon*100)}"></i>`).join('')}</div><div class="legend" style="margin:0 0 8px">${parts.map(([l,v,c])=>`<span><i style="background:${c}"></i>${l} ${pct((v||0)/b.totalExpenseWon*100,0)}</span>`).join('')}</div>`:'';
 const fe=$('finance');
 if(fe.contains(document.activeElement)){fe.querySelectorAll('[data-amt]').forEach(el=>{const id=el.dataset.amt;el.textContent=eok(id==='revenue'?b.revenueWon:id==='land'?b.landWon:id==='trust'?b.trustWon:b.allocationRows?.find(x=>x.id===id)?.amountWon,2)});const tot=fe.querySelector('[data-total]');if(tot)tot.textContent=eok(b.totalExpenseWon,2);const pr=fe.querySelector('[data-profit]');if(pr)pr.textContent=eok(b.profitWon,2);}
 else fe.innerHTML=`<div class="frow h"><span>항목</span><span>기준</span><span style="text-align:right">값</span><span style="text-align:right">억원</span></div>`+financeRow('revenue','예상 총수입',b,r)+financeRow('land','예상 토지비',b,r)+[['construction','허용 공사비'],['indirect','예상 간접 공사비'],['sales','예상 분양제 비용'],['trust','예상 신탁보수'],['tax','예상 제세공과금'],['finance','예상 금융비용']].map(([id,l])=>financeRow(id,l,b,r)).join('')+
  `<div class="frow total"><span>예상 총지출</span><span></span><span></span><span class="amt" data-total>${eok(b.totalExpenseWon,2)}</span></div><div class="frow total"><span>사업이익 · 목표 수익률</span><span></span><span class="amt" style="color:var(--${!fin(b.targetMarginPct)?'ink':b.targetMarginPct<100?'bad':'good'})">${pct(b.targetMarginPct,2)}</span><span class="amt" data-profit>${eok(b.profitWon,2)}</span></div>`+
  (b.fieldErrors?.length?`<div class="alert bad">${b.fieldErrors.map(e=>esc(e.message)).join('<br>')}</div>`:'');
 // 폭포
 const rows=[{label:'예상 토지비',amt:b.landWon,kind:'land'},...['construction','indirect','sales','tax','finance'].map(id=>{const x=b.allocationRows?.find(y=>y.id===id);return {label:{construction:'허용 공사비',indirect:'예상 간접 공사비',sales:'예상 분양제 비용',tax:'예상 제세공과금',finance:'예상 금융비용'}[id],amt:x?.amountWon,kind:id}}),{label:'예상 신탁보수',amt:b.trustWon,kind:'trust'}];
 $('wf').innerHTML=waterfall(b.revenueWon,rows,b.profitWon,{w:widthOf('wf',760),h:350});
 // 민감도
 const dev=res.development||{},S=dev.supplyAreaM2,far=input.linkedScenario?.farPct,R=b.revenueWon,Lw=b.landWon,cs=financeRowSetting(input,'construction');
 const ok=fin(S)&&S>0&&fin(far)&&far>0&&fin(R)&&fin(Lw);
 const marginFor=({far2=far,unit=null,revF=1,landF=1}={})=>{const S2=S*(far2/far),inp=unit==null?input:{...input,financeEditor:{...input.financeEditor,expenses:{...input.financeEditor?.expenses,construction:{mode:'areaUnit',value:unit}}}};return calculateBudget(inp,R*(S2/S)*revF,Lw*landF,S2).targetMarginPct};
 if(ok){
  const base=marginFor(),units=[800,900,1000,1100,1200,1400],fars=[...new Set([150,200,250,300,far].map(Math.round))].sort((a,b)=>a-b).filter(f=>f<=(input.linkedScenario?.farMaxPct||500)).slice(0,5);
  const curUnit=cs.mode==='areaUnit'?cs.value:null;
  $('heat').innerHTML=heatmap(units,fars,units.map(u=>fars.map(f=>marginFor({far2:f,unit:u}))),curUnit!=null?[curUnit,Math.round(far)]:null,{w:widthOf('heat',440),h:280,rowLabel:u=>nf(u)+'만',colLabel:f=>f+'%',corner:'평당\\용적률'})+(cs.mode==='areaUnit'?'':'<p class="note">공사비가 평당 기준이 아니어서 표는 평당 단가를 가정해 계산했습니다.</p>');
  const items=[['분양가',x=>marginFor({revF:1+x})],['토지비',x=>marginFor({landF:1+x})],...(cs.mode==='areaUnit'?[['평당 공사비',x=>marginFor({unit:cs.value*(1+x)})]]:[]),['용적률',x=>marginFor({far2:far*(1+x)})]].map(([label,f])=>({label,down:f(-.1)-base,up:f(.1)-base})).sort((a,b)=>Math.max(Math.abs(b.down),Math.abs(b.up))-Math.max(Math.abs(a.down),Math.abs(a.up)));
  $('tor').innerHTML=tornado(items,{w:widthOf('tor',440),h:250});
 }else{$('heat').innerHTML='<p class="empty">공급면적·총수입·토지비가 계산되면 표시됩니다.</p>';$('tor').innerHTML='<p class="empty">공급면적·총수입·토지비가 계산되면 표시됩니다.</p>'}
}
function renderComparables(r){
 const res=r.results||{},rev=res.revenue||{},dev=res.development||{};
 const cases=input.comparables.revenueCases||[],byComplex=new Map();
 for(const c of cases){const k=String(c.complexId||c.houseManageNo||c.id);if(!byComplex.has(k))byComplex.set(k,{id:k,name:c.name,date:c.date,dong:c.legalDongName,cases:[]});byComplex.get(k).cases.push(c)}
 const priced=new Map((rev.eligibleComplexes||rev.points||[]).map(p=>[String(p.id),p]));
 // 제외된 단지는 서버 단가가 없으므로 같은 규칙(주택형별 분양가÷공급면적의 중앙값)으로 구해 그래프에 흐리게 남긴다
 const caseMedianUnit=cs=>{const u=cs.map(x=>x.priceManwon*1e4/x.supplyAreaM2).filter(v=>fin(v)&&v>0).sort((a,b)=>a-b),n=u.length;return n?(n%2?u[(n-1)/2]:(u[n/2-1]+u[n/2])/2):null};
 const list=[...byComplex.values()].map(c=>{const p=priced.get(c.id),off=c.cases.every(x=>(x.baseEligible??x.eligible)===false);return {...c,unit:p?.unitPriceWonM2??caseMedianUnit(c.cases),km:p?.distanceKm??c.cases[0]?.distanceKm,area:p?.medianSupplyAreaM2,on:!off&&(!priced.size||!!p),off}}).sort((a,b)=>(b.on-a.on)||((b.unit||0)-(a.unit||0)));
 const applied=fin(rev.representativeWon)&&fin(dev.supplyAreaM2)&&dev.supplyAreaM2>0?rev.representativeWon/dev.supplyAreaM2*PY:null;
 $('strip').innerHTML=dotPlot(list.filter(c=>fin(c.unit)).map(c=>({label:c.name,value:c.unit*PY,on:c.on,km:c.km})),applied,{w:widthOf('strip',440)});
 $('cxTable').innerHTML=list.length?`<div class="scroll" style="max-height:220px"><table><thead><tr><th>단지</th><th class="r">거리</th><th class="r">평당</th><th></th></tr></thead><tbody>${list.map(c=>`<tr class="${c.on?'':'off'}"><td>${esc(c.name)}<div class="sub">${esc(c.date||'')} · ${c.cases.length}개 주택형</div></td><td class="r">${fin(c.km)?nf(c.km,1)+'km':'—'}</td><td class="r">${fin(c.unit)?man(c.unit*PY,0):'—'}</td><td><button class="btn sm" type="button" data-cx="${esc(c.id)}" data-on="${c.off?'1':'0'}" ${local()?'':'disabled'}>${c.off?'포함':'제외'}</button></td></tr>`).join('')}</tbody></table></div>`:`<p class="empty">${casesLoading?'비교사례 조회 중…':'필지를 선택하면 반경 안 분양사례를 조회합니다.'}</p>`;
 // 토지 사례
 const land=assessLandCases(input).filter(c=>showExcluded||c.eligible!==false||c.referenceEligible===true||c.fallbackGroupIds?.length).sort((a,b)=>String(b.date).localeCompare(String(a.date)));
 $('landCases').innerHTML=land.length?`<table><thead><tr><th>거래일</th><th>위치</th><th>지목</th><th>용도지역</th><th class="r">면적</th><th class="r">거래가</th><th class="r">만원/㎡</th><th>산정</th><th></th></tr></thead><tbody>${land.slice(0,300).map(c=>{const unit=fin(c.priceManwon)&&c.areaM2>0?c.priceManwon/c.areaM2:null,inc=c.eligible!==false;return `<tr class="${inc?'':'off'}"><td class="num">${esc(c.date||'')}</td><td>${esc(c.dong||c.legalDongName||'')}</td><td>${esc(c.jimok||'')}</td><td>${esc(c.landUse||'')}</td><td class="r">${nf(c.areaM2,0)}</td><td class="r">${nf((c.priceManwon||0)/1e4,2)}억</td><td class="r">${nf(unit,1)}</td><td class="sub">${inc?'포함':c.fallbackGroupIds?.length?'대체':c.referenceEligible?'참고':esc(c.exclusionReason||'제외')}</td><td><button class="btn sm" type="button" data-land="${esc(c.id)}" data-on="${c.manualExclusion?'1':'0'}" ${local()?'':'disabled'}>${c.manualExclusion?'포함':'제외'}</button></td></tr>`}).join('')}</tbody></table>${land.length>300?'<p class="note">최근 300건만 표시합니다.</p>':''}`:`<p class="empty">${casesLoading?'토지 실거래 조회 중…':'토지 실거래 사례가 없습니다.'}</p>`;
}
function renderLocation(){
 const center=selectedParcelCenter(input.parcels),items=survey?.facilities?.items||[];
 const bands=[[0,1,'1km'],[1,3,'1~3km'],[3,5,'3~5km']];
 const groups=Object.entries(FAC).filter(([g])=>items.some(f=>f.group===g)||['school','mountain','river','sewage'].includes(g));
 const counts=groups.map(([g,[l,c]])=>{const fs=items.filter(f=>f.group===g),near=fs.slice().sort((a,b)=>(a.distanceKm??9)-(b.distanceKm??9))[0];return `<tr><td>${facIcon(g,c)}${l}</td>${bands.map(([a,b])=>`<td class="r">${fs.filter(f=>f.distanceKm>a&&f.distanceKm<=b).length}</td>`).join('')}<td>${near?`${esc(near.name)} <span class="sub">${nf(near.distanceKm,2)}km</span>`:'—'}</td></tr>`}).join('');
 const reg={};for(const p of input.parcels)for(const x of p.attributes?.landUse?.rows||[]){if(!['1','2'].includes(String(x.cnflcAt)))continue;const code=String(x.prposAreaDstrcCode||''),n=x.prposAreaDstrcCodeNm;if(!n||['UQA01X','UQA001'].includes(code))continue;(reg[n]=reg[n]||new Set()).add(p.pnu)}
 const regRows=Object.entries(reg).sort((a,b)=>b[1].size-a[1].size).slice(0,10);
 const road={};for(const p of input.parcels){const r=p.attributes?.characteristics?.rows?.[0]?.roadSideCodeNm;if(r)road[r]=(road[r]||0)+1}
 const warn=[reg['개발제한구역']?`개발제한구역 ${reg['개발제한구역'].size}필지`:'',road['맹지']?`맹지 ${road['맹지']}필지`:''].filter(Boolean);
 $('loc').innerHTML=`${surveyState.loading?'<p class="note">주변시설 조회 중…</p>':surveyState.error?`<div class="alert bad">${esc(surveyState.error)} <button class="btn sm" type="button" id="retrySurvey">다시 조회</button></div>`:''}
  <div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px">${radar(items,center,{size:300,radiusKm:Math.min(5,input.comparisonFilters.radiusKm||5),groups:FAC})}
  <div>${warn.length?`<div class="alert" style="margin:0 0 8px">${warn.join(' · ')} · 개발 가능 여부 확인 필요</div>`:''}<table><thead><tr><th>규제 (포함·저촉)</th><th class="r">필지</th></tr></thead><tbody>${regRows.map(([n,s])=>`<tr><td>${esc(n)}</td><td class="r">${s.size}</td></tr>`).join('')||'<tr><td colspan="2" class="sub">필지 속성 조회 후 표시</td></tr>'}</tbody></table>
  <p class="sub" style="margin:8px 0 0">도로 접면: ${Object.entries(road).map(([k,v])=>`${esc(k)} ${v}`).join(' · ')||'—'}</p></div></div>
  <table style="margin-top:8px"><thead><tr><th>주변시설</th>${bands.map(b=>`<th class="r">${b[2]}</th>`).join('')}<th>가장 가까운 곳</th></tr></thead><tbody>${counts}</tbody></table>`;
}
async function renderIndicators(){
 const sgg=String(input.parcels[0]?.pnu||'').slice(0,5);
 if(!/^\d{5}$/.test(sgg)){$('m1').innerHTML=$('m2').innerHTML='<p class="empty">필지를 선택하면 지역 지표가 표시됩니다.</p>';return}
 if(!indicators.has(sgg)&&local()){indicators.set(sgg,null);try{indicators.set(sgg,await request('/api/console/region-indicators?sgg='+sgg))}catch{indicators.set(sgg,{landChange:[],cofix:[]})}}
 const d=indicators.get(sgg);if(!d)return;
 const from=shiftMonth(input.project.asOf.slice(0,7),-60);
 $('m1h').textContent=`${d.regionName||'시군구'} 월간 지가변동률 %`;
 $('m1').innerHTML=lineSeries((d.landChange||[]).filter(p=>p[0]>=from),{w:widthOf('m1',620),h:170,unit:'%',color:'var(--s2)',label:'월간 지가변동률'});
 $('m2').innerHTML=lineSeries((d.cofix||[]).filter(p=>p[0]>=from),{w:widthOf('m2',620),h:170,unit:'%',color:'var(--s3)',label:'COFIX'});
}
function renderSources(r){
 const src=(input.sources||[]).filter(s=>s&&(s.title||s.label));
 const errs=(r.results?.validation?.fieldErrors||[]).map(e=>e.message),warns=(r.warnings||[]).map(w=>typeof w==='string'?w:w?.message).filter(Boolean);
 $('sources').innerHTML=`<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px"><div><p class="sub" style="margin:0 0 6px">${esc(r.calculationStatus||(activeSample?'저장 시점 결과':''))} · 기준일 ${esc(input.project.asOf)} · 비교기간 ${esc(input.comparisonFilters.landStartDate||input.comparisonFilters.start||'—')} ~ ${esc(input.comparisonFilters.landEndDate||input.comparisonFilters.end||'—')}</p>${[...errs,...warns].slice(0,8).map(m=>`<div class="alert" style="margin:4px 0">${esc(m)}</div>`).join('')||'<p class="sub">계산 경고 없음</p>'}</div><div>${src.slice(0,12).map(s=>`<div class="sub" style="margin-bottom:4px">${s.url&&/^https?:\/\//.test(s.url)?`<a href="${esc(s.url)}" target="_blank" rel="noreferrer" style="color:var(--ink-2)">${esc(s.title||s.label)} ↗</a>`:esc(s.title||s.label)}${s.queriedAt?` · ${esc(String(s.queriedAt).slice(0,10))}`:''}</div>`).join('')||'<p class="sub">조회한 자료 출처가 여기에 표시됩니다.</p>'}</div></div>`;
}
function renderSampleSelect(){
 const sel=$('sampleSelect');
 sel.innerHTML=`<option value="">${samples.length?'저장 샘플 열기…':'저장 샘플 없음'}</option>`+samples.map(s=>`<option value="${esc(s.id)}" ${activeSample?.id===s.id?'selected':''}>${esc(s.name||s.id)}${s.capturedAt?` · ${esc(String(s.capturedAt).slice(0,10))}`:''}</option>`).join('');
}
let renderQueued=false;
function renderAll(){
 if(renderQueued)return;renderQueued=true;
 // 화면이 한 번 그려진 뒤(지도 색칠이 먼저 보이도록) 실행한다.
 requestAnimationFrame(()=>setTimeout(()=>{renderQueued=false;renderNow()},0));
}
function renderNow(){
 refreshPreview();
 const r=current();shown=r;
 renderStatus();renderControls();renderKpis(r);renderParcels();renderPlans();renderForecast(r);renderFinance(r);renderComparables(r);renderLocation();renderIndicators();renderSources(r);
}

/* ---------- 이벤트 ---------- */
const num=v=>v===''||v==null?null:Number(v);
const patchLinked=ch=>setInput({...input,linkedScenario:{...LINKED_DEFAULTS,...input.linkedScenario,enabled:true,...ch}});
const patchAssume=ch=>setInput({...input,assumptions:{...input.assumptions,...ch}});
function bindControls(){
 const onNum=(id,fn)=>{const handler=e=>{const v=num(e.target.value);if(v==null||!fin(v))return;fn(v);if(e.target.dataset.for)$(id).value=v;else{const r=document.querySelector(`[data-for="${id}"]`);if(r)r.value=v}};$(id).addEventListener('change',handler);const r=document.querySelector(`[data-for="${id}"]`);if(r)r.addEventListener('input',handler)};
 onNum('far',v=>patchLinked({farPct:v}));onNum('farMax',v=>patchLinked({farMaxPct:v}));onNum('manualArea',v=>patchLinked({supplyAreaM2:v}));
 onNum('revAdj',v=>patchAssume({revenueAdjustmentPct:v}));onNum('landAdj',v=>patchAssume({landAdjustmentPct:v}));
 onNum('radius',v=>setInput({...input,comparisonFilters:{...input.comparisonFilters,radiusKm:v}}));
 $('projName').addEventListener('change',e=>setInput({...input,project:{...input.project,name:e.target.value}}));
 $('asOf').addEventListener('change',e=>{if(/^\d{4}-\d{2}-\d{2}$/.test(e.target.value))setInput(applyRollingPeriod({...input,project:{...input.project,asOf:e.target.value}}))});
 // '직접 입력'으로 바꾸면 지금 중앙값을 시작값으로 넣어 둔다
 document.querySelectorAll('[data-area]').forEach(b=>b.addEventListener('click',()=>{const ls={...LINKED_DEFAULTS,...input.linkedScenario},med=(shown||current()).results?.development?.unitSupplyAreaM2;patchLinked(b.dataset.area==='manual'&&ls.supplyAreaM2==null&&fin(med)?{areaMode:'manual',supplyAreaM2:Math.round(med*10)/10}:{areaMode:b.dataset.area})}));
 document.querySelectorAll('[data-method]').forEach(b=>b.addEventListener('click',()=>patchAssume({revenueMethod:b.dataset.method})));
 $('requery').addEventListener('click',()=>{autoQueryPending=true;fetchCases(true,true)});
 $('recalc').addEventListener('click',()=>{if(!input.parcels.length)return toast('필지를 먼저 선택하세요.',true);activeSample=null;scheduleAnalyze(true)});
 $('pin').addEventListener('click',()=>{baseline=summary(current());renderAll();toast('지금 값을 기준안으로 고정했습니다')});
 $('sampleSelect').addEventListener('change',e=>openSample(e.target.value));
 $('saveSample').addEventListener('click',saveSample);$('exportJson').addEventListener('click',exportJson);$('pdfBtn').addEventListener('click',exportPdf);
 $('importJson').addEventListener('change',e=>{const f=e.target.files?.[0];e.target.value='';if(f)importJson(f)});
 $('addrBtn').addEventListener('click',searchAddress);$('clearParcels').addEventListener('click',clearParcels);$('addr').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();searchAddress()}if(e.key==='Escape')$('cands').hidden=true});
 $('showExcluded').addEventListener('change',e=>{showExcluded=e.target.checked;renderComparables(current())});
 // 지도 안 '면적·단가 보기' 버튼(기존 화면 부품)은 이 신호를 보낸다 → 콘솔에서는 토지 예측·사례 쪽으로 이동
 addEventListener('pf-v3-navigate',()=>$('page2').scrollIntoView({behavior:'smooth',block:'start'}));
 document.addEventListener('click',e=>{
  const c=e.target.closest('[data-cand]');if(c){goCandidate($('cands').data[+c.dataset.cand]);return}
  if(!e.target.closest('.search'))$('cands').hidden=true;
  const rm=e.target.closest('[data-remove]');if(rm){const p=input.parcels.find(x=>x.pnu===rm.dataset.remove);if(p)toggleParcel({id:p.pnu,properties:{pnu:p.pnu},geometry:p.geometry});return}
  if(e.target.id==='retryParcels'){selection.arm(input.parcels);input.parcels.filter(p=>parcelStatus(p)[0]==='err').forEach(p=>fetchParcel(p.pnu,true));return}
  if(e.target.id==='retrySurvey'){if(confirmSelectedQuery(input.parcels,selection,{local:local(),parcelPending:parcelPending()}))runSurvey();return}
  const g=e.target.closest('[data-grp]');if(g){const k=g.dataset.grp;grpOff.has(k)?grpOff.delete(k):grpOff.add(k);renderForecast(current());return}
  const cx=e.target.closest('[data-cx]');if(cx){const include=cx.dataset.on==='1',id=cx.dataset.cx;setInput({...input,comparables:{...input.comparables,revenueCases:input.comparables.revenueCases.map(r=>String(r.complexId||r.houseManageNo||r.id)===id?(include?{...r,baseEligible:true,baseExclusionReason:'',eligible:true,exclusionReason:'',manualExclusion:false}:{...r,baseEligible:false,baseExclusionReason:'사용자 제외',manualExclusion:true}):r)}});return}
  const ld=e.target.closest('[data-land]');if(ld){const include=ld.dataset.on==='1',id=ld.dataset.land;setInput({...input,comparables:{...input.comparables,landCases:input.comparables.landCases.map(r=>r.id===id?{...r,manualExclusion:!include,manualExclusionReason:include?'':'사용자 제외'}:r)}});return}
 });
 const fin2=$('finance');
 fin2.addEventListener('change',e=>{
  const el=e.target;
  if(el.dataset.fmode){const id=el.dataset.fmode,mode=el.value,r=current(),b=currentBudget(input,r.results||{}),S=r.results?.development?.supplyAreaM2;
   const applied=id==='revenue'?b.revenueWon:id==='land'?b.landWon:id==='trust'?b.trustWon:b.allocationRows?.find(x=>x.id===id)?.amountWon;
   const base=mode==='comparablePct'?r.results?.[id]?.comparableWon:mode==='budgetPct'?b.totalExpenseWon:mode==='revenuePct'?b.revenueWon:mode==='areaUnit'&&fin(S)?S/3.3*1e4:null;
   const value=mode==='amount'?(fin(applied)?applied:null):fin(base)&&base>0&&fin(applied)?Math.round(applied/base*(mode==='areaUnit'?1:100)*100)/100:mode==='comparablePct'?100:mode==='areaUnit'?1000:null;
   setFinance(id,{mode,value});fin2.innerHTML='';renderFinance(current());return}
  if(el.dataset.fval){const id=el.dataset.fval,s=financeRowSetting(input,id),mode=s.mode==='constructionPct'?'budgetPct':s.mode,n=num(el.value);
   if(el.value.trim()!==''&&!fin(n))return toast('숫자를 입력하세요.',true);
   setFinance(id,{...s,mode,value:n==null?null:n*(mode==='amount'?1e8:1)});fin2.innerHTML='';renderFinance(current())}
 });
}
function setFinance(id,setting){
 const fe=input.financeEditor||{};
 setInput({...input,financeEditor:['revenue','land'].includes(id)?{...fe,[id]:setting}:{...fe,expenses:{...fe.expenses,[id]:setting}}});
}
/* 툴팁 */
function bindTips(){
 const tip=$('tip');
 document.addEventListener('pointermove',e=>{const t=e.target.closest?.('[data-tip]');if(!t){tip.style.opacity=0;return}tip.textContent=t.getAttribute('data-tip');tip.style.opacity=1;const x=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8),y=e.clientY+16+tip.offsetHeight>innerHeight?e.clientY-tip.offsetHeight-10:e.clientY+16;tip.style.transform=`translate(${x}px,${y}px)`});
}

/* ---------- 시작 ---------- */
async function boot(){
 bindControls();bindTips();
 // 왼쪽 가정 패널 접기·펼치기. 상태는 이 브라우저에만 기억한다 (다음에 열어도 같은 상태).
 const setAside=(off,remember=true)=>{document.body.classList.toggle('aside-off',off);const b=$('asideToggle'),t=off?'왼쪽 가정 패널 펼치기':'왼쪽 가정 패널 접기';
  b.setAttribute('aria-expanded',String(!off));b.setAttribute('aria-label',t);b.title=t;if(remember)try{localStorage.setItem('console.asideOff',off?'1':'0')}catch{}renderAll()};
 let savedOff=false;try{savedOff=localStorage.getItem('console.asideOff')==='1'}catch{}
 if(savedOff)setAside(true,false);
 $('asideToggle').addEventListener('click',()=>setAside(!document.body.classList.contains('aside-off')));
 // 창 크기가 바뀌면 차트를 새 폭으로 다시 그린다
 let resizeTimer=0;addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(renderAll,200)});
 // 상단 바 높이(버튼이 줄바꿈되면 달라짐)에 맞춰 왼쪽 패널 위치를 정한다
 new ResizeObserver(([e])=>document.documentElement.style.setProperty('--top-h',Math.ceil(e.target.getBoundingClientRect().height)+'px')).observe(document.querySelector('.top'));renderAll();
 try{status=await request('/api/status')}catch{status={mode:'offline'};toast('서버에 연결할 수 없습니다. 보기 전용으로 엽니다.',true)}
 renderAll();
 const defaultId=await loadSamples();
 const first=samples.find(s=>s.id===defaultId)||samples[0];
 if(first&&!input.parcels.length)await openSample(first.id);
}
boot();
